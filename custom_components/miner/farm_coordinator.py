"""Aggregate data and actions for a farm (multiple miner devices)."""
from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_FARM_AMBIENT_TEMP_ENTITIES
from .const import CONF_FARM_DEVICE_IDS
from .const import CONF_POWER_SWITCH
from .const import DOMAIN
from .device_resolution import async_get_miner_config_entry_for_device

_LOGGER = logging.getLogger(__name__)


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

    def _iter_miner_coordinators_for_ids(self, device_ids: list[str]):
        """Yield miner coordinators for each device id in the given list."""
        dev_reg = dr.async_get(self.hass)
        for did in device_ids:
            device = dev_reg.async_get(did)
            if device is None:
                continue
            entry = async_get_miner_config_entry_for_device(self.hass, device)
            if entry is None:
                continue
            coord = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if coord is not None and callable(getattr(coord, "get_miner", None)):
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
        total_hash = 0.0
        total_w = 0.0
        miner_count = 0
        miners_online = 0
        chips_expected = 0
        chips_effective = 0
        algo_counts: Counter[str] = Counter()

        for coord in self._iter_miner_coordinators():
            miner_count += 1
            if not coord.last_update_success:
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

        if algo_counts:
            if len(algo_counts) == 1:
                algorithm_summary = next(iter(algo_counts.keys()))
            else:
                algorithm_summary = ", ".join(
                    f"{name} ({count})"
                    for name, count in sorted(algo_counts.items())
                )
        else:
            algorithm_summary = "SHA256d"

        chips_percent = (
            round(100.0 * chips_effective / chips_expected, 2)
            if chips_expected > 0
            else None
        )

        return {
            "total_hashrate_th": round(total_hash, 2),
            "total_power_w": round(total_w, 0),
            "total_power_kw": round(total_w / 1000.0, 3) if total_w else 0.0,
            "miner_count": miner_count,
            "miners_online": miners_online,
            "algorithm": algorithm_summary,
            "chips_effective_percent": chips_percent,
            "chips_effective": chips_effective if chips_expected else None,
            "chips_expected": chips_expected if chips_expected else None,
            "ambient_temperatures": self._ambient_temperature_map(),
            "emergency_stop_available": self.emergency_stop_available,
        }

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

    async def async_emergency_power_off(self) -> None:
        """Turn off every linked smart switch (miner power strips)."""
        for eid in self.linked_power_switches():
            if self.hass.states.get(eid) is None:
                continue
            await self.hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": eid},
                blocking=False,
            )

    def _reported_algorithms_for_device_ids(self, device_ids: list[str]) -> set[str]:
        """Non-empty algorithm strings from members (last successful poll) for these devices."""
        distinct: set[str] = set()
        for coord in self._iter_miner_coordinators_for_ids(device_ids):
            if not coord.last_update_success:
                continue
            algo = coord.data.get("algorithm")
            if algo and str(algo).strip():
                distinct.add(str(algo).strip())
        return distinct

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
    ) -> tuple[bool, str | None]:
        """Apply primary or backup stratum to every member (same as per-miner pool tools)."""
        ids = list(device_ids) if device_ids is not None else list(self.device_ids)
        if not self.farm_stratum_allowed_for_device_ids(ids):
            return False, "farm_pool_mixed_algorithms"
        members = list(self._iter_miner_coordinators_for_ids(ids))
        if not members:
            return False, "farm_pool_no_members"

        from . import pool_stratum

        append_ssl = bool(use_ssl) if use_ssl is not None else False
        user_template = "" if username is None else str(username)
        failures = 0
        for coord in members:
            miner = await coord.get_miner()
            if miner is None:
                failures += 1
                _LOGGER.warning(
                    "Farm stratum: miner unreachable (entry %s)",
                    coord.config_entry.entry_id,
                )
                continue
            per_user = expand_farm_pool_username(
                user_template, coord.data.get("ip")
            )
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
                if not ok:
                    failures += 1
                else:
                    await coord.async_request_refresh()
            except Exception:
                _LOGGER.exception(
                    "Farm stratum apply failed (entry %s)",
                    coord.config_entry.entry_id,
                )
                failures += 1

        if failures:
            return False, "farm_pool_apply_failed"
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
        return await self.async_apply_stratum_to_members(
            device_ids=device_ids,
            replace_primary=replace_primary,
            host=str(preset["host"]),
            port=int(preset["port"]),
            use_ssl=bool(preset.get("use_ssl", False)),
            username=str(preset.get("username") or ""),
            password=str(preset.get("password") or ""),
        )
