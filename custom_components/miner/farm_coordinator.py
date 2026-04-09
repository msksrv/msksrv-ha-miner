"""Aggregate data and actions for a farm (multiple miner devices)."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_FARM_DEVICE_IDS
from .const import CONF_POWER_SWITCH
from .const import DOMAIN
from .device_resolution import async_get_miner_config_entry_for_device

_LOGGER = logging.getLogger(__name__)


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

    def _iter_miner_coordinators(self):
        """Yield miner coordinators for each configured miner device on the farm."""
        dev_reg = dr.async_get(self.hass)
        for did in self.device_ids:
            device = dev_reg.async_get(did)
            if device is None:
                continue
            entry = async_get_miner_config_entry_for_device(self.hass, device)
            if entry is None:
                continue
            coord = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if coord is not None and callable(getattr(coord, "get_miner", None)):
                yield coord

    async def _async_update_data(self) -> dict:
        total_hash = 0.0
        total_w = 0.0
        miner_count = 0
        miners_online = 0

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

        return {
            "total_hashrate_th": round(total_hash, 2),
            "total_power_w": round(total_w, 0),
            "total_power_kw": round(total_w / 1000.0, 3) if total_w else 0.0,
            "miner_count": miner_count,
            "miners_online": miners_online,
            "algorithm": "SHA256d",
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
