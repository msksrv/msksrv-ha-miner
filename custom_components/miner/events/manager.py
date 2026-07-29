"""Event state tracking, deduplication, and emission."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from ..health.repairs.definitions import RepairType
from .definitions import (
    OFFLINE_FAILURE_THRESHOLD,
    STABLE_READINGS_REQUIRED,
    build_problem_payload,
    pool_signature,
    sanitize_event_data,
    work_mode_signature,
)
from .dispatcher import EventDispatcher

if TYPE_CHECKING:
    from ..health.baseline.detector import AnomalyState


class MinerEventManager:
    """Track miner state transitions and emit activity events."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._dispatcher = EventDispatcher(hass, entry, scope="miner")
        self._initialized = False
        self._failure_streak = 0
        self._offline_event_sent = False
        self._last_pool: tuple[str | None, str | None, str | None] | None = None
        self._pool_candidate: tuple[str | None, str | None, str | None] | None = None
        self._pool_stable_count = 0
        self._last_work_mode: str | None = None
        self._work_mode_candidate: str | None = None
        self._work_mode_stable_count = 0
        self._open_problems: set[str] = set()

    @property
    def dispatcher(self) -> EventDispatcher:
        return self._dispatcher

    def bind_entity(self, entity) -> None:
        self._dispatcher.bind_entity(entity)

    @callback
    def async_seed_poll(self, data: dict[str, Any] | None, *, available: bool) -> None:
        """Remember baseline state on first poll without emitting."""
        if self._initialized:
            return
        if available and data:
            self._last_pool = pool_signature(data)
            self._last_work_mode = work_mode_signature(data)
        self._failure_streak = 0 if available else 1
        self._offline_event_sent = False
        self._initialized = True

    @callback
    def async_process_poll(
        self, data: dict[str, Any] | None, *, available: bool
    ) -> None:
        """Evaluate availability and data changes after a coordinator poll."""
        if not self._initialized:
            self.async_seed_poll(data, available=available)
            return

        if available:
            if self._offline_event_sent:
                self._dispatcher.async_emit("online", {})
                self._offline_event_sent = False
            self._failure_streak = 0
            if data:
                self._maybe_emit_pool_changed(data)
                self._maybe_emit_work_mode_changed(data)
            return

        self._failure_streak += 1
        if (
            self._failure_streak >= OFFLINE_FAILURE_THRESHOLD
            and not self._offline_event_sent
        ):
            self._dispatcher.async_emit("offline", {})
            self._offline_event_sent = True

    @callback
    def async_emit_problem_detected(
        self,
        problem_type: str,
        data: dict[str, Any],
        anomaly: AnomalyState,
    ) -> None:
        if problem_type == RepairType.OFFLINE or problem_type in self._open_problems:
            return
        payload = build_problem_payload(problem_type, data, anomaly)
        self._dispatcher.async_emit("problem_detected", payload)
        self._open_problems.add(problem_type)

    @callback
    def async_emit_problem_cleared(self, problem_type: str) -> None:
        if problem_type == RepairType.OFFLINE:
            return
        if problem_type not in self._open_problems:
            return
        self._dispatcher.async_emit(
            "problem_cleared",
            sanitize_event_data({"problem_type": problem_type}),
        )
        self._open_problems.discard(problem_type)

    @callback
    def async_sync_open_problems(self, open_types: set[str]) -> None:
        """Seed open problem types after reload without emitting events."""
        self._open_problems = {
            rtype for rtype in open_types if rtype != RepairType.OFFLINE
        }

    @callback
    def async_emit_problem_acknowledged(self, problem_type: str) -> None:
        if problem_type == RepairType.OFFLINE:
            return
        self._dispatcher.async_emit(
            "problem_acknowledged",
            sanitize_event_data({"problem_type": problem_type}),
        )
        self._open_problems.discard(problem_type)

    @callback
    def async_emit_reboot_command_sent(self) -> None:
        self._dispatcher.async_emit("reboot_command_sent", {})

    @callback
    def async_emit_recovery_event(
        self, event_type: str, payload: dict[str, Any]
    ) -> None:
        self._dispatcher.async_emit(event_type, payload)

    @callback
    def async_emit_ip_changed(self, old_ip: str, new_ip: str) -> None:
        self._dispatcher.async_emit(
            "ip_changed",
            sanitize_event_data({"old_ip": old_ip, "new_ip": new_ip}),
        )

    @callback
    def async_emit_pool_changed(self, data: dict[str, Any]) -> None:
        payload = sanitize_event_data(
            {
                "pool_host": data.get("pool_host"),
                "pool_port": data.get("pool_port"),
                "pool_worker": data.get("pool_worker"),
            }
        )
        self._dispatcher.async_emit("pool_changed", payload)
        self._last_pool = pool_signature(data)
        self._pool_candidate = None
        self._pool_stable_count = 0

    def _maybe_emit_pool_changed(self, data: dict[str, Any]) -> None:
        sig = pool_signature(data)
        if not any(sig):
            return
        if self._last_pool is None:
            self._last_pool = sig
            return
        if sig == self._last_pool:
            self._pool_candidate = None
            self._pool_stable_count = 0
            return
        if sig == self._pool_candidate:
            self._pool_stable_count += 1
        else:
            self._pool_candidate = sig
            self._pool_stable_count = 1
        if self._pool_stable_count >= STABLE_READINGS_REQUIRED:
            self.async_emit_pool_changed(data)

    def _maybe_emit_work_mode_changed(self, data: dict[str, Any]) -> None:
        mode = work_mode_signature(data)
        if not mode:
            return
        if self._last_work_mode is None:
            self._last_work_mode = mode
            return
        if mode == self._last_work_mode:
            self._work_mode_candidate = None
            self._work_mode_stable_count = 0
            return
        if mode == self._work_mode_candidate:
            self._work_mode_stable_count += 1
        else:
            self._work_mode_candidate = mode
            self._work_mode_stable_count = 1
        if self._work_mode_stable_count >= STABLE_READINGS_REQUIRED:
            self._dispatcher.async_emit(
                "work_mode_changed",
                sanitize_event_data({"work_mode": mode}),
            )
            self._last_work_mode = mode
            self._work_mode_candidate = None
            self._work_mode_stable_count = 0


class FarmEventManager:
    """Farm-scoped activity events."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._dispatcher = EventDispatcher(hass, entry, scope="farm")

    @property
    def dispatcher(self) -> EventDispatcher:
        return self._dispatcher

    def bind_entity(self, entity) -> None:
        self._dispatcher.bind_entity(entity)

    @callback
    def async_emit_emergency_power_off(self, switch_count: int) -> None:
        self._dispatcher.async_emit(
            "emergency_power_off",
            sanitize_event_data({"switch_count": switch_count}),
        )

    @callback
    def async_emit_emergency_power_off_partial_failure(
        self,
        *,
        success_count: int,
        failure_count: int,
        failed_switches: list[str],
    ) -> None:
        self._dispatcher.async_emit(
            "emergency_power_off_partial_failure",
            sanitize_event_data(
                {
                    "success_count": success_count,
                    "failure_count": failure_count,
                    "failed_switches": failed_switches,
                }
            ),
        )

    @callback
    def async_emit_emergency_power_off_failed(
        self,
        failed_switches: list[str] | None = None,
        *,
        reason: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {}
        if failed_switches is not None:
            payload["failure_count"] = len(failed_switches)
            payload["failed_switches"] = failed_switches
        if reason is not None:
            payload["reason"] = reason
        self._dispatcher.async_emit(
            "emergency_power_off_failed",
            sanitize_event_data(payload),
        )

    @callback
    def async_emit_emergency_stop_cleared(self, miner_count: int) -> None:
        self._dispatcher.async_emit(
            "emergency_stop_cleared",
            sanitize_event_data({"miner_count": miner_count}),
        )

    @callback
    def async_emit_preset_applied(self, preset: str, success_count: int) -> None:
        self._dispatcher.async_emit(
            "preset_applied",
            sanitize_event_data({"preset": preset, "success_count": success_count}),
        )

    @callback
    def async_emit_preset_failed(
        self,
        *,
        preset: str,
        failure_count: int,
        failed_miners: list[str],
        reason: str,
    ) -> None:
        self._dispatcher.async_emit(
            "preset_failed",
            sanitize_event_data(
                {
                    "preset": preset,
                    "failure_count": failure_count,
                    "failed_miners": failed_miners,
                    "reason": reason,
                }
            ),
        )

    @callback
    def async_emit_preset_partial_failure(
        self,
        *,
        preset: str,
        success_count: int,
        failure_count: int,
        failed_miners: list[str],
        reason: str,
    ) -> None:
        self._dispatcher.async_emit(
            "preset_partial_failure",
            sanitize_event_data(
                {
                    "preset": preset,
                    "success_count": success_count,
                    "failure_count": failure_count,
                    "failed_miners": failed_miners,
                    "reason": reason,
                }
            ),
        )
