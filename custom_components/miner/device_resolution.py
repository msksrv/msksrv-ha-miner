"""Map device registry entries to miner config entries (handles missing primary)."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac

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
    if mac_norm and len(mac_norm) == 12:
        formatted = format_mac(mac_norm)
        if (device := dev_reg.async_get_device(
            connections={(CONNECTION_NETWORK_MAC, formatted)}
        )) and async_get_miner_config_entry_for_device(hass, device) is not None:
            return True

    if (
        ip_s
        and (device := dev_reg.async_get_device(connections={("ip", ip_s)}))
        and async_get_miner_config_entry_for_device(hass, device) is not None
    ):
        return True

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
