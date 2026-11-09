"""Map device registry entries to miner config entries (handles missing primary)."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

from .const import CONF_IP, CONF_IS_FARM, DOMAIN


def normalize_hardware_id(value: str | None) -> str:
    """Normalize MAC / serial / unique_id for comparison."""
    if not value:
        return ""
    return str(value).strip().lower().replace(":", "").replace("-", "")


def miner_entity_unique_suffix(entry: ConfigEntry, mac: str | None) -> str:
    """Stable suffix for entity unique_id (MAC preferred, else config entry id)."""
    normalized = normalize_hardware_id(mac)
    if normalized:
        return normalized
    return entry.entry_id


def _iter_miner_config_entries(hass: HomeAssistant):
    """Yield non-farm miner config entries."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if not entry.data.get(CONF_IS_FARM) and entry.data.get(CONF_IP):
            yield entry


def is_miner_already_configured(
    hass: HomeAssistant,
    *,
    ip: str | None = None,
    mac: str | None = None,
    unique_key: str | None = None,
) -> bool:
    """True when a single-miner entry already covers this IP, MAC, or stable id."""
    ip_s = str(ip or "").strip()
    key_norm = normalize_hardware_id(unique_key)
    mac_norm = normalize_hardware_id(mac)
    if mac_norm:
        key_norm = key_norm or mac_norm

    for entry in _iter_miner_config_entries(hass):
        if ip_s and str(entry.data.get(CONF_IP, "")).strip() == ip_s:
            return True
        uid = normalize_hardware_id(entry.unique_id)
        if uid and key_norm and uid == key_norm:
            return True
        if uid and mac_norm and uid == mac_norm:
            return True
        if uid.startswith("miner_dhcp_") and mac_norm:
            dhcp_tail = normalize_hardware_id(uid.removeprefix("miner_dhcp_"))
            if dhcp_tail == mac_norm:
                return True

    dev_reg = dr.async_get(hass)

    for entry in _iter_miner_config_entries(hass):
        for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
            for conn_type, conn_id in device.connections:
                if (
                    conn_type == CONNECTION_NETWORK_MAC
                    and mac_norm
                    and normalize_hardware_id(conn_id) == mac_norm
                ):
                    return True
                if conn_type == "ip" and ip_s and str(conn_id).strip() == ip_s:
                    return True
            for domain, identifier in device.identifiers:
                if domain != DOMAIN:
                    continue
                ident_norm = normalize_hardware_id(identifier)
                if ident_norm and key_norm and ident_norm == key_norm:
                    return True
                if ident_norm and mac_norm and ident_norm == mac_norm:
                    return True

    return False


def _device_config_entry_ids(device: dr.DeviceEntry) -> tuple[str, ...]:
    entry_id = getattr(device, "config_entry_id", None)
    if entry_id:
        return (entry_id,)
    # Older supported cores can associate one device with multiple config entries.
    primary = device.primary_config_entry
    if primary:
        return tuple(dict.fromkeys((primary, *device.config_entries)))
    return tuple(device.config_entries)


def async_get_farm_config_entry_for_device(
    hass: HomeAssistant,
    device: dr.DeviceEntry,
) -> ConfigEntry | None:
    """Config entry when this device is a farm aggregate."""
    for entry_id in _device_config_entry_ids(device):
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == DOMAIN and entry.data.get(CONF_IS_FARM):
            return entry
    return None


def async_get_miner_config_entry_for_device(
    hass: HomeAssistant,
    device: dr.DeviceEntry,
) -> ConfigEntry | None:
    """Config entry for this device when it is a single miner."""
    for entry_id in _device_config_entry_ids(device):
        entry = hass.config_entries.async_get_entry(entry_id)
        if (
            entry
            and entry.domain == DOMAIN
            and not entry.data.get(CONF_IS_FARM)
            and entry.data.get(CONF_IP)
        ):
            return entry
    return None
