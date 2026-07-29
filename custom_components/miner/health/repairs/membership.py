"""Farm membership lookups for repair deduplication."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from ...const import CONF_FARM_DEVICE_IDS, CONF_IS_FARM, DOMAIN


def miner_belongs_to_farm(hass: HomeAssistant, miner_entry_id: str) -> bool:
    """True when this miner config entry is a member of any farm."""
    return bool(farm_entry_ids_for_miner(hass, miner_entry_id))


def farm_entry_ids_for_miner(hass: HomeAssistant, miner_entry_id: str) -> list[str]:
    """Loaded farm config entry ids that include this miner."""
    dev_reg = dr.async_get(hass)
    device_ids = {
        device.id
        for device in dr.async_entries_for_config_entry(dev_reg, miner_entry_id)
    }
    if not device_ids:
        return []
    farms: list[str] = []
    domain_data = hass.data.get(DOMAIN, {})
    for entry in hass.config_entries.async_entries(DOMAIN):
        if not entry.data.get(CONF_IS_FARM):
            continue
        if entry.state != ConfigEntryState.LOADED:
            continue
        if domain_data.get(entry.entry_id) is None:
            continue
        raw = entry.data.get(CONF_FARM_DEVICE_IDS) or []
        member_ids = {raw} if isinstance(raw, str) else set(raw)
        if device_ids & member_ids:
            farms.append(entry.entry_id)
    return farms


def format_offline_miner_list(
    names: list[str], *, language: str | None, max_show: int = 3
) -> tuple[str, str]:
    """Return (miners, miners_more) placeholders for farm offline repair."""
    if not names:
        return "—", ""
    if len(names) <= max_show:
        return ", ".join(names), ""
    lang = "ru" if language and language.startswith("ru") else "en"
    shown = ", ".join(names[:max_show])
    rest = len(names) - max_show
    if lang == "ru":
        return shown, f", и ещё {rest} майнеров"
    return shown, f", and {rest} more miners"
