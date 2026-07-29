"""Automatic hashrate recovery finite-state machine."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ...const import (
    CONF_AUTO_RECOVERY_COOLDOWN_SECONDS,
    CONF_AUTO_RECOVERY_ENABLED,
    CONF_AUTO_RECOVERY_MAX_POWER_CYCLES,
    CONF_AUTO_RECOVERY_MAX_REBOOTS,
    CONF_AUTO_RECOVERY_POST_POWER_ON_SECONDS,
    CONF_AUTO_RECOVERY_POST_REBOOT_SECONDS,
    CONF_AUTO_RECOVERY_POWER_CYCLE_ENABLED,
    CONF_AUTO_RECOVERY_POWER_OFF_PAUSE_SECONDS,
    CONF_AUTO_RECOVERY_PRE_ACTION_SECONDS,
    DOMAIN,
)
from ...events.definitions import pool_signature, work_mode_signature, sanitize_event_data
from ...health.repairs.membership import farm_entry_ids_for_miner
from .actions import async_power_off, async_power_on, async_send_recovery_reboot
from .definitions import (
    MAX_POWER_ON_RETRIES,
    OFFLINE_TOLERANT_STATES,
    POWER_CRITICAL_STATES,
    POWER_ON_RETRY_SECONDS,
    REBOOT_RETRY_SECONDS,
    LockReason,
    RECOVERY_REASON_HASHRATE_LOW,
    RecoveryRecord,
    RecoveryState,
    recovery_settings,
)
from .policy import (
    action_event_context,
    apply_config_block,
    apply_cooldown,
    apply_manual_cooldown,
    can_start_recovery,
    event_context,
    hashrate_metrics,
    hashrate_recovered,
    in_cooldown,
    new_attempt_id,
    power_switch_entity_id,
    should_continue_recovery,
    switch_is_on,
)
from .storage import RecoveryStorage

if TYPE_CHECKING:
    from ...coordinator import MinerCoordinator
    from ...events.manager import MinerEventManager
    from ...health.repairs.manager import RepairManager

_LOGGER = logging.getLogger(__name__)

_ACTIVE_STATES = frozenset(
    {
        RecoveryState.ARMING,
        RecoveryState.WAITING_REBOOT,
        RecoveryState.POWER_OFF_WAIT,
        RecoveryState.POWER_ON_PENDING,
        RecoveryState.WAITING_POWER_RECOVERY,
    }
)


def _now() -> datetime:
    return dt_util.utcnow()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return dt_util.parse_datetime(value)


def _after(iso: str | None) -> bool:
    target = _parse_iso(iso)
    if target is None:
        return True
    return _now() >= target


class RecoveryManager:
    """Orchestrate hashrate recovery as a strict finite-state machine."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: MinerCoordinator,
        events: MinerEventManager,
        repairs: RepairManager,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self._coordinator = coordinator
        self._events = events
        self._repairs = repairs
        self._storage = RecoveryStorage(hass, entry.entry_id)
        self._last_pool: tuple[str | None, str | None, str | None] | None = None
        self._last_mode: str | None = None
        self._farm_claimed = False
        self._farm_claimed_ids: list[str] = []

    @property
    def record(self) -> RecoveryRecord:
        return self._storage.record

    async def async_load(self) -> None:
        await self._storage.async_load()
        if self.record.emergency_stop_latched:
            return
        if self.record.state in _ACTIVE_STATES and not self._claim_farm_slot():
            _LOGGER.warning(
                "Auto-recovery for %s could not reclaim farm slot after reload",
                self.entry.title,
            )

    async def async_save(self, *, force: bool = False) -> None:
        await self._storage.async_save(force=force)

    async def async_prepare_unload(self) -> None:
        """Restore power if needed, persist state, release farm slot."""
        if self.record.emergency_stop_latched:
            self._release_farm_slot()
            await self.async_save(force=True)
            return
        if self.record.state in POWER_CRITICAL_STATES:
            await self._attempt_power_on(self._coordinator.data or {})
        self._release_farm_slot()
        await self.async_save(force=True)

    async def async_remove(self) -> None:
        await self.async_prepare_unload()
        if self.record.emergency_stop_latched:
            await self._storage.async_remove()
            return
        if self.record.state in POWER_CRITICAL_STATES:
            return
        await self._storage.async_remove()

    def release_on_unload(self) -> None:
        """Release farm mutex when this miner entry unloads."""
        self._release_farm_slot()

    async def async_sync_emergency_latch(self) -> None:
        """Reload latched state from Store after farm emergency stop."""
        await self._storage.async_load()
        self._release_farm_slot()

    async def async_clear_emergency_latch(self) -> None:
        """Clear farm emergency stop latch for this miner."""
        from .emergency import async_clear_emergency_latch

        await async_clear_emergency_latch(self.hass, self.entry.entry_id)
        await self._storage.async_load()

    def reload_options(self) -> None:
        settings = recovery_settings(self.entry.options)
        if settings.get(CONF_AUTO_RECOVERY_ENABLED):
            return
        if self.record.state in POWER_CRITICAL_STATES:
            self.hass.async_create_task(
                self._handle_auto_disabled(self._coordinator.data or {})
            )
            return
        if self.record.state not in (RecoveryState.IDLE, RecoveryState.LOCKED):
            self.hass.async_create_task(self.async_cancel("disabled"))

    @staticmethod
    def notify_manual_reboot(coordinator: MinerCoordinator) -> None:
        recovery = getattr(coordinator, "recovery", None)
        if recovery is None:
            return
        recovery._on_manual_action()

    @staticmethod
    def notify_manual_power(coordinator: MinerCoordinator) -> None:
        recovery = getattr(coordinator, "recovery", None)
        if recovery is None:
            return
        recovery._on_manual_action()

    def notify_ip_changed(self) -> None:
        self._apply_config_block(force_save=True)
        if self.record.state not in (
            RecoveryState.IDLE,
            RecoveryState.LOCKED,
            *POWER_CRITICAL_STATES,
        ):
            self.hass.async_create_task(self.async_cancel("ip_changed"))

    async def async_reset_lock(self) -> None:
        record = self.record
        if record.state != RecoveryState.LOCKED:
            return
        self._release_farm_slot()
        self._storage.replace(RecoveryRecord())
        ctx = sanitize_event_data({"reason": record.reason or RECOVERY_REASON_HASHRATE_LOW})
        self._events.async_emit_recovery_event("recovery_manually_reset", ctx)
        self._repairs.clear_recovery_failed()
        self._repairs.clear_power_restore_failed()
        await self.async_save(force=True)

    def _on_manual_action(self) -> None:
        apply_manual_cooldown(self.record)
        self._storage._dirty = True
        state = self.record.state
        if state in POWER_CRITICAL_STATES:
            if switch_is_on(self.hass, power_switch_entity_id(self._coordinator)):
                self.hass.async_create_task(self.async_cancel("manual_action"))
            return
        if state not in (RecoveryState.IDLE, RecoveryState.LOCKED):
            self.hass.async_create_task(self.async_cancel("manual_action"))

    async def _handle_auto_disabled(self, data: dict[str, Any]) -> None:
        if self.record.state in POWER_CRITICAL_STATES:
            await self._attempt_power_on(data)
            return
        if self.record.state not in (RecoveryState.IDLE, RecoveryState.LOCKED):
            await self.async_cancel("disabled")

    async def async_process_update(
        self,
        data: dict[str, Any] | None,
        anomaly: Any,
        *,
        available: bool,
    ) -> None:
        record = self.record
        settings = recovery_settings(self.entry.options)

        if record.state == RecoveryState.LOCKED:
            await self.async_save()
            return

        if record.emergency_stop_latched:
            await self.async_save()
            return

        if not settings.get(CONF_AUTO_RECOVERY_ENABLED):
            await self._handle_auto_disabled(data or {})
            return

        if not available or data is None:
            if record.state == RecoveryState.ARMING:
                await self.async_cancel("offline")
                return
            if record.state in OFFLINE_TOLERANT_STATES:
                await self._process_offline_wait(anomaly)
                return
            await self.async_save()
            return

        if data and available:
            self._track_config_changes(data)

        if record.state != RecoveryState.IDLE:
            ok, reason = should_continue_recovery(
                self._coordinator, data, anomaly, record, available=available
            )
            if not ok and reason:
                await self.async_cancel(reason)
                return

        if record.state == RecoveryState.IDLE:
            if in_cooldown(record):
                await self.async_save()
                return
            if not self._claim_farm_slot():
                await self.async_save()
                return
            can, _reason = can_start_recovery(
                self._coordinator,
                data,
                anomaly,
                record,
                available=available,
                farm_slot=True,
            )
            if can:
                await self._begin_arming(data)
            else:
                self._release_farm_slot()
            return

        if record.state == RecoveryState.ARMING:
            _current, _expected, _threshold, low = hashrate_metrics(
                self._coordinator, data
            )
            if not low:
                await self.async_cancel("hashrate_ok")
                return
            if _after(record.wait_until):
                await self._execute_reboot(data)
            return

        if record.state == RecoveryState.WAITING_REBOOT:
            if hashrate_recovered(self._coordinator, data):
                await self._succeed_reboot(data)
                return
            if _after(record.wait_until):
                await self._after_reboot_timeout(data)
            return

        if record.state == RecoveryState.POWER_OFF_WAIT:
            if _after(record.wait_until):
                await self._attempt_power_on(data)
            return

        if record.state == RecoveryState.POWER_ON_PENDING:
            if _after(record.wait_until):
                await self._attempt_power_on(data)
            return

        if record.state == RecoveryState.WAITING_POWER_RECOVERY:
            if hashrate_recovered(self._coordinator, data):
                await self._succeed_power_cycle(data)
                return
            if _after(record.wait_until):
                await self._after_power_timeout(data)
            return

        await self.async_save()

    async def _process_offline_wait(self, anomaly: Any) -> None:
        """Advance wait states while miner/API is temporarily unreachable."""
        record = self.record
        data: dict[str, Any] = {}

        if record.state == RecoveryState.WAITING_REBOOT:
            if _after(record.wait_until):
                await self._after_reboot_timeout(data)
            else:
                await self.async_save()
            return

        if record.state == RecoveryState.POWER_OFF_WAIT:
            if _after(record.wait_until):
                await self._attempt_power_on(data)
            else:
                await self.async_save()
            return

        if record.state == RecoveryState.POWER_ON_PENDING:
            if _after(record.wait_until):
                await self._attempt_power_on(data)
            else:
                await self.async_save()
            return

        if record.state == RecoveryState.WAITING_POWER_RECOVERY:
            if _after(record.wait_until):
                await self._after_power_timeout(data)
            else:
                await self.async_save()
            return

        await self.async_save()

    def _apply_config_block(self, *, force_save: bool = False) -> None:
        apply_config_block(self.record, storage=self._storage)
        if force_save:
            self.hass.async_create_task(self.async_save(force=True))

    def _track_config_changes(self, data: dict[str, Any]) -> None:
        pool = pool_signature(data)
        mode = work_mode_signature(data)
        state = self.record.state
        if self._last_pool is not None and pool != self._last_pool:
            self._apply_config_block(force_save=True)
            if state not in (
                RecoveryState.IDLE,
                RecoveryState.LOCKED,
                *POWER_CRITICAL_STATES,
            ):
                self.hass.async_create_task(self.async_cancel("pool_changed"))
        if self._last_mode is not None and mode and mode != self._last_mode:
            self._apply_config_block(force_save=True)
            if state not in (
                RecoveryState.IDLE,
                RecoveryState.LOCKED,
                *POWER_CRITICAL_STATES,
            ):
                self.hass.async_create_task(self.async_cancel("work_mode_changed"))
        self._last_pool = pool
        self._last_mode = mode

    async def _begin_arming(self, data: dict[str, Any]) -> None:
        settings = recovery_settings(self.entry.options)
        current, expected, threshold, _low = hashrate_metrics(self._coordinator, data)
        now = _now()
        record = self.record
        record.state = RecoveryState.ARMING
        record.reason = RECOVERY_REASON_HASHRATE_LOW
        record.attempt_id = new_attempt_id()
        record.started_at = now.isoformat()
        record.pre_action_hashrate = current
        record.expected_hashrate = expected
        record.threshold_hashrate = threshold
        record.power_on_retries = 0
        record.wait_until = (
            now + timedelta(seconds=settings[CONF_AUTO_RECOVERY_PRE_ACTION_SECONDS])
        ).isoformat()
        self._storage._dirty = True
        ctx = sanitize_event_data(event_context(self._coordinator, data, record))
        self._events.async_emit_recovery_event("recovery_started", ctx)
        await self.async_save(force=True)

    async def _execute_reboot(self, data: dict[str, Any]) -> None:
        settings = recovery_settings(self.entry.options)
        record = self.record
        if record.reboot_attempts >= settings[CONF_AUTO_RECOVERY_MAX_REBOOTS]:
            await self._after_reboot_attempts_exhausted(data)
            return
        attempt_no = record.reboot_attempts + 1
        ctx = sanitize_event_data(
            action_event_context(
                self._coordinator, data, record, reboot_attempt=attempt_no
            )
        )
        try:
            await async_send_recovery_reboot(self._coordinator)
        except Exception:
            _LOGGER.exception("Auto-recovery reboot failed for %s", self.entry.title)
            record.reboot_attempts += 1
            self._events.async_emit_recovery_event("reboot_recovery_failed", ctx)
            if record.reboot_attempts < settings[CONF_AUTO_RECOVERY_MAX_REBOOTS]:
                now = _now()
                record.state = RecoveryState.WAITING_REBOOT
                record.wait_until = (
                    now + timedelta(seconds=REBOOT_RETRY_SECONDS)
                ).isoformat()
                record.last_action_at = now.isoformat()
                self._storage._dirty = True
                await self.async_save(force=True)
                return
            await self._after_reboot_attempts_exhausted(data)
            return
        now = _now()
        record.reboot_attempts += 1
        record.last_action_at = now.isoformat()
        record.state = RecoveryState.WAITING_REBOOT
        record.wait_until = (
            now + timedelta(seconds=settings[CONF_AUTO_RECOVERY_POST_REBOOT_SECONDS])
        ).isoformat()
        self._storage._dirty = True
        self._events.async_emit_recovery_event("recovery_reboot_command_sent", ctx)
        await self.async_save(force=True)

    async def _after_reboot_timeout(self, data: dict[str, Any]) -> None:
        record = self.record
        if data and hashrate_recovered(self._coordinator, data):
            await self._succeed_reboot(data)
            return
        settings = recovery_settings(self.entry.options)
        ctx = sanitize_event_data(event_context(self._coordinator, data, record))
        self._events.async_emit_recovery_event("reboot_recovery_failed", ctx)
        if record.reboot_attempts < settings[CONF_AUTO_RECOVERY_MAX_REBOOTS]:
            await self._execute_reboot(data)
            return
        await self._after_reboot_attempts_exhausted(data)

    async def _after_reboot_attempts_exhausted(self, data: dict[str, Any]) -> None:
        settings = recovery_settings(self.entry.options)
        record = self.record
        if (
            settings.get(CONF_AUTO_RECOVERY_POWER_CYCLE_ENABLED)
            and record.power_cycle_attempts
            < settings[CONF_AUTO_RECOVERY_MAX_POWER_CYCLES]
            and power_switch_entity_id(self._coordinator)
        ):
            await self._start_power_cycle(data)
            return
        await self._lock_exhausted(data)

    async def _start_power_cycle(self, data: dict[str, Any]) -> None:
        if self.record.emergency_stop_latched:
            _LOGGER.warning(
                "Power cycle blocked for %s — emergency stop latched",
                self.entry.title,
            )
            return
        switch_id = power_switch_entity_id(self._coordinator)
        record = self.record
        if not switch_id:
            await self._lock_exhausted(data)
            return
        cycle_no = record.power_cycle_attempts + 1
        ctx = sanitize_event_data(
            action_event_context(
                self._coordinator, data, record, power_cycle_attempt=cycle_no
            )
        )
        self._events.async_emit_recovery_event("power_cycle_started", ctx)
        try:
            ok = await async_power_off(self.hass, switch_id)
        except Exception:
            _LOGGER.exception("Auto-recovery power off failed for %s", self.entry.title)
            ok = False
        if not ok:
            self._events.async_emit_recovery_event("power_cycle_failed", ctx)
            await self._lock_exhausted(data)
            return
        self._events.async_emit_recovery_event("power_off_command_sent", ctx)
        settings = recovery_settings(self.entry.options)
        now = _now()
        record.last_action_at = now.isoformat()
        record.power_on_retries = 0
        record.state = RecoveryState.POWER_OFF_WAIT
        record.wait_until = (
            now + timedelta(seconds=settings[CONF_AUTO_RECOVERY_POWER_OFF_PAUSE_SECONDS])
        ).isoformat()
        self._storage._dirty = True
        await self.async_save(force=True)

    async def _attempt_power_on(self, data: dict[str, Any]) -> None:
        if self.record.emergency_stop_latched:
            _LOGGER.warning(
                "Power on blocked for %s — emergency stop latched",
                self.entry.title,
            )
            return
        switch_id = power_switch_entity_id(self._coordinator)
        record = self.record
        cycle_no = record.power_cycle_attempts + 1
        ctx = sanitize_event_data(
            action_event_context(
                self._coordinator, data, record, power_cycle_attempt=cycle_no
            )
        )
        if not switch_id:
            self._events.async_emit_recovery_event("power_cycle_failed", ctx)
            await self._lock_power_restore_failed(data)
            return
        try:
            ok = await async_power_on(self.hass, switch_id)
        except Exception:
            _LOGGER.exception("Auto-recovery power on failed for %s", self.entry.title)
            ok = False
        if ok:
            self._events.async_emit_recovery_event("power_on_command_sent", ctx)
            settings = recovery_settings(self.entry.options)
            now = _now()
            record.power_cycle_attempts += 1
            record.power_on_retries = 0
            record.last_action_at = now.isoformat()
            record.state = RecoveryState.WAITING_POWER_RECOVERY
            record.wait_until = (
                now
                + timedelta(seconds=settings[CONF_AUTO_RECOVERY_POST_POWER_ON_SECONDS])
            ).isoformat()
            self._storage._dirty = True
            await self.async_save(force=True)
            return

        record.power_on_retries += 1
        if record.power_on_retries >= MAX_POWER_ON_RETRIES:
            self._events.async_emit_recovery_event("power_cycle_failed", ctx)
            await self._lock_power_restore_failed(data)
            return

        now = _now()
        record.state = RecoveryState.POWER_ON_PENDING
        record.wait_until = (
            now + timedelta(seconds=POWER_ON_RETRY_SECONDS)
        ).isoformat()
        record.last_action_at = now.isoformat()
        self._storage._dirty = True
        await self.async_save(force=True)

    async def _after_power_timeout(self, data: dict[str, Any]) -> None:
        record = self.record
        if data and hashrate_recovered(self._coordinator, data):
            await self._succeed_power_cycle(data)
            return
        settings = recovery_settings(self.entry.options)
        ctx = sanitize_event_data(event_context(self._coordinator, data, record))
        self._events.async_emit_recovery_event("power_cycle_failed", ctx)
        if record.power_cycle_attempts < settings[CONF_AUTO_RECOVERY_MAX_POWER_CYCLES]:
            await self._start_power_cycle(data)
            return
        await self._lock_exhausted(data)

    async def _succeed_reboot(self, data: dict[str, Any]) -> None:
        record = self.record
        ctx = sanitize_event_data(event_context(self._coordinator, data, record))
        self._events.async_emit_recovery_event("reboot_recovery_succeeded", ctx)
        await self._finish_success()

    async def _succeed_power_cycle(self, data: dict[str, Any]) -> None:
        record = self.record
        ctx = sanitize_event_data(event_context(self._coordinator, data, record))
        self._events.async_emit_recovery_event("power_cycle_succeeded", ctx)
        await self._finish_success()

    async def _finish_success(self) -> None:
        settings = recovery_settings(self.entry.options)
        self._release_farm_slot()
        record = RecoveryRecord()
        apply_cooldown(record, settings[CONF_AUTO_RECOVERY_COOLDOWN_SECONDS])
        self._storage.replace(record)
        await self.async_save(force=True)

    async def _lock_exhausted(self, data: dict[str, Any]) -> None:
        settings = recovery_settings(self.entry.options)
        record = self.record
        record.state = RecoveryState.LOCKED
        record.locked_reason = LockReason.MAX_ATTEMPTS
        apply_cooldown(record, settings[CONF_AUTO_RECOVERY_COOLDOWN_SECONDS])
        self._storage._dirty = True
        ctx = sanitize_event_data(event_context(self._coordinator, data, record))
        self._events.async_emit_recovery_event("recovery_locked", ctx)
        self._repairs.open_recovery_failed(data, record)
        self._release_farm_slot()
        await self.async_save(force=True)

    async def _lock_power_restore_failed(self, data: dict[str, Any]) -> None:
        settings = recovery_settings(self.entry.options)
        record = self.record
        record.state = RecoveryState.LOCKED
        record.locked_reason = LockReason.POWER_RESTORE
        apply_cooldown(record, settings[CONF_AUTO_RECOVERY_COOLDOWN_SECONDS])
        self._storage._dirty = True
        ctx = sanitize_event_data(event_context(self._coordinator, data, record))
        self._events.async_emit_recovery_event("recovery_locked", ctx)
        self._repairs.open_power_restore_failed(data, record)
        self._release_farm_slot()
        await self.async_save(force=True)

    async def async_cancel(self, reason: str) -> None:
        record = self.record
        if record.state == RecoveryState.IDLE:
            return
        data = self._coordinator.data or {}
        ctx = sanitize_event_data(
            {
                **event_context(self._coordinator, data, record),
                "cancel_reason": reason,
            }
        )
        self._events.async_emit_recovery_event("recovery_cancelled", ctx)
        self._release_farm_slot()
        preserved = RecoveryRecord(cooldown_until=record.cooldown_until)
        if record.config_block_until:
            preserved.config_block_until = record.config_block_until
        if record.emergency_stop_latched:
            preserved.emergency_stop_latched = True
        self._storage.replace(preserved)
        await self.async_save(force=True)

    def _claim_farm_slot(self) -> bool:
        if self._farm_claimed:
            return True
        farm_ids = farm_entry_ids_for_miner(self.hass, self.entry.entry_id)
        if not farm_ids:
            self._farm_claimed = True
            return True
        claimed: list[str] = []
        for farm_id in farm_ids:
            farm = self.hass.data.get(DOMAIN, {}).get(farm_id)
            if farm is None or not hasattr(farm, "try_claim_recovery"):
                continue
            if not farm.try_claim_recovery(self.entry.entry_id):
                for prior_id in claimed:
                    prior = self.hass.data.get(DOMAIN, {}).get(prior_id)
                    if prior is not None and hasattr(prior, "release_recovery"):
                        prior.release_recovery(self.entry.entry_id)
                self._farm_claimed_ids = []
                self._farm_claimed = False
                return False
            claimed.append(farm_id)
        self._farm_claimed_ids = claimed
        self._farm_claimed = True
        return True

    def _release_farm_slot(self) -> None:
        if not self._farm_claimed and not self._farm_claimed_ids:
            return
        release_ids = self._farm_claimed_ids or farm_entry_ids_for_miner(
            self.hass, self.entry.entry_id
        )
        for farm_id in release_ids:
            farm = self.hass.data.get(DOMAIN, {}).get(farm_id)
            if farm is not None and hasattr(farm, "release_recovery"):
                farm.release_recovery(self.entry.entry_id)
        self._farm_claimed_ids = []
        self._farm_claimed = False
