"""Map device registry entries to miner config entries (handles missing primary)."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import CONF_IP
from .const import CONF_IS_FARM
from .const import DOMAIN


def async_get_farm_config_entry_for_device(
    hass: HomeAssistant,
    device: dr.DeviceEntry,
) -> ConfigEntry | None:
    """Config entry when this device is a farm aggregate (not a single miner)."""
    mgr = hass.config_entries
    ordered_ids: list[str] = []
    if device.primary_config_entry:
        ordered_ids.append(device.primary_config_entry)
    ordered_ids.extend(device.config_entries)
    seen: set[str] = set()
    for eid in ordered_ids:
        if not eid or eid in seen:
            continue
        seen.add(eid)
        ce = mgr.async_get_entry(eid)
        if ce and ce.domain == DOMAIN and ce.data.get(CONF_IS_FARM):
            return ce
    return None


def _is_miner_config_entry(entry: ConfigEntry | None) -> bool:
    return bool(
        entry
        and entry.domain == DOMAIN
        and not entry.data.get(CONF_IS_FARM)
        and entry.data.get(CONF_IP)
    )


def async_get_miner_config_entry_for_device(
    hass: HomeAssistant,
    device: dr.DeviceEntry,
) -> ConfigEntry | None:
    """Config entry for this device when it is a single miner (not a farm)."""
    mgr = hass.config_entries
    primary = device.primary_config_entry
    if primary:
        ce = mgr.async_get_entry(primary)
        if _is_miner_config_entry(ce):
            return ce
    for eid in device.config_entries:
        ce = mgr.async_get_entry(eid)
        if _is_miner_config_entry(ce):
            return ce
    return None
