"""Aggregate data and actions for a farm (multiple miner devices)."""
from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_FARM_AMBIENT_TEMP_ENTITIES,
    CONF_FARM_DEVICE_IDS,
    CONF_IP,
    CONF_POWER_SWITCH,
    DOMAIN,
)
from .device_resolution import async_get_miner_config_entry_for_device
from .farm_health import compute_farm_health_metrics
from .events import FarmEventManager
from .energy import FarmEnergyManager
from .health.repairs.farm_manager import FarmRepairManager

_LOGGER = logging.getLogger(__name__)

# Second+ miners sometimes miss the first send_config (API busy); brief retries help.
_FARM_STRATUM_ATTEMPTS = 3
_FARM_STRATUM_RETRY_DELAY_SEC = 1.2
_FARM_STRATUM_MEMBER_GAP_SEC = 0.25


def _miner_ip_for_worker_template(coord) -> str:
    """Prefer polled IP; fall back to config entry (avoids empty {ip} on stale data)."""
    data = coord.data or {}
    ip = data.get("ip")
    if ip is not None and str(ip).strip():
        return str(ip).strip()
    return str(coord.config_entry.data.get(CONF_IP) or "").strip()


def _miner_ip_for_worker_expansion(entry: ConfigEntry, coord) -> str:
    """IP for {ip} / {ip_last} when coordinator may be missing."""
    if coord is not None:
        return _miner_ip_for_worker_template(coord)
    return str(entry.data.get(CONF_IP) or "").strip()


def expand_farm_pool_username(template: str, miner_ip: object | None) -> str:
    """Replace {ip} and {ip_last} in the worker string (farm bulk apply only)."""
    ip_s = str(miner_ip or "").strip()
    parts = ip_s.split(".")
    last_octet = ip_s
    if len(parts) == 4:
        try:
            nums = [int(x) for x in parts]
            if all(0 <= n <= 255 for n in nums):
                last_octet = parts[3]
        except ValueError:
            pass
    return template.replace("{ip}", ip_s).replace("{ip_last}", last_octet)


class MinerFarmCoordinator(DataUpdateCoordinator):
    """Sum metrics from linked miner coordinators; emergency stop via linked switches."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        raw_ids = entry.data.get(CONF_FARM_DEVICE_IDS) or []
        if isinstance(raw_ids, str):
            self.device_ids: list[str] = [raw_ids]
        else:
            self.device_ids = list(raw_ids)
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=entry.title,
            update_interval=timedelta(seconds=15),
            config_entry=entry,
        )
        self.events = FarmEventManager(hass, entry)
        self.repairs = FarmRepairManager(hass, entry)
        self.energy = FarmEnergyManager(hass, entry)
        self._recovery_active_miner: str | None = None
        self._emergency_stop_active = False
        self._emergency_clear_armed_until: float | None = None

    def try_claim_recovery(self, miner_entry_id: str) -> bool:
        """Allow at most one auto-recovery on this farm at a time."""
        if self._recovery_active_miner in (None, miner_entry_id):
            self._recovery_active_miner = miner_entry_id
            return True
        return False

    def release_recovery(self, miner_entry_id: str) -> None:
        if self._recovery_active_miner == miner_entry_id:
            self._recovery_active_miner = None

    def _iter_miner_member_pairs(
        self,
        device_ids: list[str],
        *,
        warn_missing: bool = False,
    ):
        """Yield (miner ConfigEntry, coordinator | None), deduped by config entry id."""
        dev_reg = dr.async_get(self.hass)
        seen: set[str] = set()
        for did in device_ids:
            device = dev_reg.async_get(did)
            if device is None:
                if warn_missing:
                    _LOGGER.warning(
                        "Farm stratum: device id not in registry (skipped): %s",
                        did,
                    )
                continue
            entry = async_get_miner_config_entry_for_device(self.hass, device)
            if entry is None:
                if warn_missing:
                    _LOGGER.warning(
                        "Farm stratum: device has no miner integration (skipped): %s",
                        did,
                    )
                continue
            if entry.entry_id in seen:
                if warn_missing:
                    _LOGGER.warning(
                        "Farm stratum: duplicate miner for two devices — only first is used (%s)",
                        entry.title,
                    )
                continue
            seen.add(entry.entry_id)
            coord = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if coord is not None and not callable(getattr(coord, "get_miner", None)):
                coord = None
            if coord is None and warn_missing:
                _LOGGER.warning(
                    "Farm stratum: no coordinator for %s (ip=%s); using config entry for API",
                    entry.title,
                    entry.data.get(CONF_IP, "?"),
                )
            yield entry, coord

    def _iter_miner_coordinators_for_ids(self, device_ids: list[str]):
        """Yield miner coordinators for each device id in the given list."""
        for _entry, coord in self._iter_miner_member_pairs(device_ids):
            if coord is not None:
                yield coord

    def _iter_miner_coordinators(self):
        """Yield miner coordinators for each configured miner device on the farm."""
        yield from self._iter_miner_coordinators_for_ids(self.device_ids)

    def _ambient_temperature_map(self) -> dict[str, dict]:
        """Linked room sensors: value, unit, friendly name (from source state)."""
        raw = self.config_entry.options.get(CONF_FARM_AMBIENT_TEMP_ENTITIES) or []
        if isinstance(raw, str):
            raw = [raw]
        out: dict[str, dict] = {}
        for eid in raw:
            eid = str(eid).strip()
            if not eid:
                continue
            state = self.hass.states.get(eid)
            friendly = eid
            unit = "°C"
            value = None
            if state is not None:
                friendly = state.attributes.get("friendly_name") or eid
                unit = state.attributes.get("unit_of_measurement") or "°C"
                try:
                    value = float(state.state)
                except (TypeError, ValueError):
                    value = None
            out[eid] = {
                "value": value,
                "unit_of_measurement": unit,
                "friendly_name": friendly,
            }
        return out

    async def _async_update_data(self) -> dict:
        member_pairs = list(self._iter_miner_member_pairs(self.device_ids))
        total_hash = 0.0
        total_w = 0.0
        miner_count = len(member_pairs)
        miners_online = 0
        chips_expected = 0
        chips_effective = 0
        algo_counts: Counter[str] = Counter()

        for _entry, coord in member_pairs:
            if coord is None or not coord.last_update_success or not coord.data:
                continue
            miners_online += 1
            ms = coord.data.get("miner_sensors") or {}
            h = ms.get("hashrate")
            if h is not None:
                try:
                    total_hash += float(h)
                except (TypeError, ValueError):
                    pass
            w = ms.get("miner_consumption")
            if w is not None:
                try:
                    total_w += float(w)
                except (TypeError, ValueError):
                    pass

            al = coord.data.get("algorithm")
            if al:
                algo_counts[str(al)] += 1

            boards = coord.data.get("board_sensors") or {}
            for board in boards.values():
                exp = board.get("board_expected_chips")
                act = board.get("board_chips")
                if exp is None or act is None:
                    continue
                try:
                    exp_i = int(exp)
                    act_i = int(act)
                except (TypeError, ValueError):
                    continue
                if exp_i <= 0:
                    continue
                chips_expected += exp_i
                chips_effective += min(act_i, exp_i)

        farm_metrics = compute_farm_health_metrics(member_pairs)
        health_scores = farm_metrics["health_scores"]
        health_issue_counts = farm_metrics["health_issue_counts"]
        health_offline = farm_metrics["health_status_counts"]["offline"]

        if algo_counts:
            if len(algo_counts) == 1:
                algorithm_summary = next(iter(algo_counts.keys()))
            else:
                algorithm_summary = ", ".join(
                    f"{name} ({count})"
                    for name, count in sorted(algo_counts.items())
                )
        else:
            algorithm_summary = None

        chips_percent = (
            round(100.0 * chips_effective / chips_expected, 2)
            if chips_expected > 0
            else None
        )
        farm_health_score = None
        health_denominator = len(health_scores) + health_offline
        if health_denominator:
            # Offline members contribute zero. Online miners with unsupported
            # health data remain unknown instead of being treated as broken.
            farm_health_score = round(sum(health_scores) / health_denominator)

        offline_names: list[str] = []
        for entry, coord in member_pairs:
            if coord is None or not coord.last_update_success:
                offline_names.append(
                    entry.title or str(entry.data.get(CONF_IP) or "Miner")
                )

        self.repairs.process_update(
            offline_count=health_offline,
            miner_count=miner_count,
            offline_names=offline_names,
        )

        data = {
            "total_hashrate_th": round(total_hash, 2),
            "total_power_w": round(total_w, 0),
            "total_power_kw": round(total_w / 1000.0, 3) if total_w else 0.0,
            "miner_count": miner_count,
            "miners_online": miners_online,
            "algorithm": algorithm_summary,
            "chips_effective_percent": chips_percent,
            "chips_effective": chips_effective if chips_expected else None,
            "chips_expected": chips_expected if chips_expected else None,
            "health_score": farm_health_score,
            "health_miners_evaluated": len(health_scores),
            "health_miners_offline": health_offline,
            "health_issues": dict(sorted(health_issue_counts.items())),
            "miners_healthy": farm_metrics["miners_healthy"],
            "miners_with_issues": farm_metrics["miners_with_issues"],
            "expected_hashrate_th": (
                None
                if farm_metrics["hashrate_metrics_mixed_algorithms"]
                else farm_metrics["expected_hashrate_th"]
            ),
            "expected_miners": farm_metrics["expected_miners"],
            "expected_miners_unknown": farm_metrics["expected_miners_unknown"],
            "expected_hashrate_reference": farm_metrics["expected_hashrate_reference"],
            "lost_hashrate_th": (
                None
                if farm_metrics["hashrate_metrics_mixed_algorithms"]
                else farm_metrics["lost_hashrate_th"]
            ),
            "lost_hashrate_percent": (
                None
                if farm_metrics["hashrate_metrics_mixed_algorithms"]
                else farm_metrics["lost_hashrate_percent"]
            ),
            "average_efficiency_jth": farm_metrics["average_efficiency_jth"],
            "hashrate_metrics_mixed_algorithms": farm_metrics[
                "hashrate_metrics_mixed_algorithms"
            ],
            "hashrate_metrics_algorithms": farm_metrics["hashrate_metrics_algorithms"],
            "hottest_miner": farm_metrics["hottest_miner"],
            "worst_reject_rate": farm_metrics["worst_reject_rate"],
            "health_status_counts": farm_metrics["health_status_counts"],
            "health_problem_devices": farm_metrics["health_problem_devices"],
            "health_problem_devices_truncated": farm_metrics[
                "health_problem_devices_truncated"
            ],
            "ambient_temperatures": self._ambient_temperature_map(),
            "emergency_stop_available": self.emergency_stop_available,
            "emergency_stop_active": self._emergency_stop_active,
        }
        await self.energy.async_tick(self)
        return data

    def linked_power_switches(self) -> list[str]:
        """Entity IDs of power switches configured on member miners."""
        dev_reg = dr.async_get(self.hass)
        found: list[str] = []
        for did in self.device_ids:
            device = dev_reg.async_get(did)
            if device is None:
                continue
            entry = async_get_miner_config_entry_for_device(self.hass, device)
            if entry is None:
                continue
            eid = entry.options.get(CONF_POWER_SWITCH)
            if eid:
                found.append(str(eid).strip())
        return list(dict.fromkeys(found))

    @property
    def emergency_stop_available(self) -> bool:
        """True if at least one linked switch exists in the state machine."""
        for eid in self.linked_power_switches():
            if self.hass.states.get(eid) is not None:
                return True
        return False

    @property
    def emergency_stop_active(self) -> bool:
        return self._emergency_stop_active

    async def async_refresh_emergency_stop_cache(self) -> None:
        """Load emergency latch state once (startup); not polled every cycle."""
        from .health.recovery.emergency import async_entry_emergency_latched

        active = False
        for entry, _coord in self._iter_miner_member_pairs(self.device_ids):
            if await async_entry_emergency_latched(self.hass, entry.entry_id):
                active = True
                break
        self._emergency_stop_active = active

    def arm_emergency_clear(self) -> None:
        import time

        self._emergency_clear_armed_until = time.monotonic() + 30.0

    @property
    def emergency_clear_armed(self) -> bool:
        import time

        if self._emergency_clear_armed_until is None:
            return False
        if time.monotonic() > self._emergency_clear_armed_until:
            self._emergency_clear_armed_until = None
            return False
        return True

    async def async_clear_emergency_stop(self) -> None:
        """Clear emergency stop latch on all farm members (explicit confirm)."""
        from .health.recovery.emergency import async_clear_emergency_latch

        pairs = list(self._iter_miner_member_pairs(self.device_ids))
        for entry, member in pairs:
            await async_clear_emergency_latch(self.hass, entry.entry_id)
            if member is not None and hasattr(member, "recovery"):
                await member.recovery.async_clear_emergency_latch()
        self._emergency_stop_active = False
        self._emergency_clear_armed_until = None
        self.events.async_emit_emergency_stop_cleared(len(pairs))
        await self.async_request_refresh()

    async def async_emergency_power_off(self) -> None:
        """Latch recovery on all members, then turn off linked switches."""
        from .health.recovery.actions import async_power_off
        from .health.recovery.emergency import async_latch_emergency_stop

        pairs = list(self._iter_miner_member_pairs(self.device_ids))
        for entry, member in pairs:
            await async_latch_emergency_stop(self.hass, entry.entry_id)
            if member is not None and hasattr(member, "recovery"):
                await member.recovery.async_sync_emergency_latch()

        self._recovery_active_miner = None
        self._emergency_stop_active = True
        self._emergency_clear_armed_until = None

        switches = [
            eid
            for eid in self.linked_power_switches()
            if self.hass.states.get(eid) is not None
        ]
        if not switches:
            _LOGGER.warning("Emergency stop: no linked switches available")
            self.events.async_emit_emergency_power_off_failed(reason="no_switches")
            await self.async_request_refresh()
            return

        async def _turn_off(entity_id: str) -> tuple[str, bool]:
            ok = await async_power_off(self.hass, entity_id)
            return entity_id, ok

        results = await asyncio.gather(*(_turn_off(eid) for eid in switches))
        failed_switches: list[str] = []
        successes = 0
        for eid, ok in results:
            if ok:
                successes += 1
            else:
                failed_switches.append(eid)
                _LOGGER.error("Emergency stop failed for %s", eid)

        failures = len(failed_switches)
        if failures == 0:
            _LOGGER.info("Emergency stop: turned off %s switch(es)", successes)
            self.events.async_emit_emergency_power_off(successes)
        elif successes == 0:
            _LOGGER.error("Emergency stop: all %s switch(es) failed", len(switches))
            self.events.async_emit_emergency_power_off_failed(failed_switches)
        else:
            _LOGGER.error(
                "Emergency stop: %s of %s switch(es) failed",
                failures,
                len(switches),
            )
            self.events.async_emit_emergency_power_off_partial_failure(
                success_count=successes,
                failure_count=failures,
                failed_switches=failed_switches,
            )
        await self.async_request_refresh()

    def _reported_algorithms_for_device_ids(self, device_ids: list[str]) -> set[str]:
        from .farm_validation import reported_algorithms_for_device_ids

        return reported_algorithms_for_device_ids(self.hass, device_ids)

    def farm_stratum_allowed_for_device_ids(self, device_ids: list[str]) -> bool:
        """False when members report two or more different algorithms."""
        return len(self._reported_algorithms_for_device_ids(device_ids)) <= 1

    def farm_stratum_allowed_by_algorithm(self) -> bool:
        """False when configured members report two or more different algorithms."""
        return self.farm_stratum_allowed_for_device_ids(self.device_ids)

    async def async_apply_stratum_to_members(
        self,
        *,
        device_ids: list[str] | None = None,
        replace_primary: bool,
        host: str,
        port: int,
        use_ssl: bool | None = None,
        username: str | None = None,
        password: str | None = None,
        preset_label: str | None = None,
    ) -> tuple[bool, str | None]:
        """Apply primary or backup stratum to every member (same as per-miner pool tools)."""
        ids = list(device_ids) if device_ids is not None else list(self.device_ids)
        if not self.farm_stratum_allowed_for_device_ids(ids):
            return False, "farm_pool_mixed_algorithms"
        pairs = list(self._iter_miner_member_pairs(ids, warn_missing=True))
        if not pairs:
            return False, "farm_pool_no_members"

        from . import pool_stratum
        from .coordinator import async_get_miner_from_config_entry

        append_ssl = bool(use_ssl) if use_ssl is not None else False
        user_template = "" if username is None else str(username)
        failures = 0
        successes = 0
        failed_miners: list[str] = []
        member_index = 0
        for entry, coord in pairs:
            per_user = expand_farm_pool_username(
                user_template, _miner_ip_for_worker_expansion(entry, coord)
            )
            entry_title = entry.title
            miner_ip = entry.data.get(CONF_IP, "?")
            success = False
            for attempt in range(_FARM_STRATUM_ATTEMPTS):
                miner = None
                if coord is not None:
                    miner = await coord.get_miner()
                if miner is None:
                    miner = await async_get_miner_from_config_entry(entry)
                if miner is None:
                    _LOGGER.warning(
                        "Farm stratum: no connection (attempt %s/%s) %s ip=%s",
                        attempt + 1,
                        _FARM_STRATUM_ATTEMPTS,
                        entry_title,
                        miner_ip,
                    )
                    if attempt + 1 < _FARM_STRATUM_ATTEMPTS:
                        await asyncio.sleep(_FARM_STRATUM_RETRY_DELAY_SEC)
                    continue
                try:
                    if replace_primary:
                        ok = await pool_stratum.async_apply_primary_stratum(
                            miner,
                            host,
                            port,
                            use_ssl,
                            per_user,
                            password,
                            force_user_password=True,
                        )
                    else:
                        ok = await pool_stratum.async_append_stratum_pool(
                            miner,
                            host,
                            port,
                            append_ssl,
                            per_user,
                            password,
                        )
                    if ok:
                        if coord is not None:
                            await coord.async_request_refresh()
                        success = True
                        break
                    _LOGGER.warning(
                        "Farm stratum: miner rejected or invalid config (attempt %s/%s) %s ip=%s",
                        attempt + 1,
                        _FARM_STRATUM_ATTEMPTS,
                        entry_title,
                        miner_ip,
                    )
                except Exception:
                    _LOGGER.exception(
                        "Farm stratum: exception (attempt %s/%s) %s ip=%s",
                        attempt + 1,
                        _FARM_STRATUM_ATTEMPTS,
                        entry_title,
                        miner_ip,
                    )
                if attempt + 1 < _FARM_STRATUM_ATTEMPTS:
                    await asyncio.sleep(_FARM_STRATUM_RETRY_DELAY_SEC)
            if not success:
                failures += 1
                failed_miners.append(entry_title)
                _LOGGER.error(
                    "Farm stratum: gave up on %s (ip=%s) after %s attempts",
                    entry_title,
                    miner_ip,
                    _FARM_STRATUM_ATTEMPTS,
                )
            else:
                successes += 1
            member_index += 1
            if member_index < len(pairs) and success:
                await asyncio.sleep(_FARM_STRATUM_MEMBER_GAP_SEC)

        label = preset_label or host
        if failures:
            if successes > 0:
                self.events.async_emit_preset_partial_failure(
                    preset=label,
                    success_count=successes,
                    failure_count=failures,
                    failed_miners=failed_miners,
                    reason="apply_failed",
                )
            else:
                self.events.async_emit_preset_failed(
                    preset=label,
                    failure_count=failures,
                    failed_miners=failed_miners,
                    reason="apply_failed",
                )
            return False, "farm_pool_apply_failed"
        self.events.async_emit_preset_applied(label, successes)
        return True, None

    async def async_apply_saved_preset_slot(
        self,
        slot_index: int,
        *,
        replace_primary: bool,
        device_ids: list[str] | None = None,
    ) -> tuple[bool, str | None]:
        """Apply a stratum preset from options by slot index (0 .. slots-1)."""
        from .farm_pool_presets import farm_pool_preset_slots

        slots = farm_pool_preset_slots(self.config_entry.options)
        if slot_index < 0 or slot_index >= len(slots):
            return False, "farm_pool_apply_slot_invalid"
        preset = slots[slot_index]
        if not preset.get("host"):
            return False, "farm_pool_apply_slot_invalid"
        preset_label = str(preset.get("host") or f"slot_{slot_index + 1}")
        return await self.async_apply_stratum_to_members(
            device_ids=device_ids,
            replace_primary=replace_primary,
            host=str(preset["host"]),
            port=int(preset["port"]),
            use_ssl=bool(preset.get("use_ssl", False)),
            username=str(preset.get("username") or ""),
            password=str(preset.get("password") or ""),
            preset_label=preset_label,
        )
