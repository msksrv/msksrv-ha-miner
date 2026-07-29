"""Entity registry cleanup after the 1.6.7 MAC-based unique_id change."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .device_resolution import normalize_hardware_id

_LOGGER = logging.getLogger(__name__)

# Buttons / pool select used MAC suffix before 1.6.7 as well — do not touch.
_MAC_SUFFIX_KEEP = (
    "-reboot",
    "-power-off",
    "-power-on",
    "-pool-priority",
)

# 1.6.7 used hyphen; 1.6.5 / 1.6.9 use underscore for power limit number entity.
_LEGACY_TAIL_ALIASES = {
    "power-limit": "power_limit",
}


def _legacy_unique_id(entry_id: str, mac_tail: str) -> str:
    """Map MAC-suffixed tail back to the pre-1.6.7 entry_id unique_id form."""
    legacy_tail = _LEGACY_TAIL_ALIASES.get(mac_tail, mac_tail)
    return f"{entry_id}-{legacy_tail}"


async def async_migrate_mac_unique_id_duplicates(
    hass: HomeAssistant,
    entry: ConfigEntry,
    mac: str | None,
) -> None:
    """Drop or rename MAC-suffixed entities created in 1.6.7–1.6.8.

    Sensors, switch, number and power-mode select used config_entry.entry_id
    before 1.6.7. After revert, restore the legacy row and remove duplicates.
    """
    mac_suffix = normalize_hardware_id(mac)
    if not mac_suffix or mac_suffix == entry.entry_id:
        return

    registry = er.async_get(hass)
    entry_id = entry.entry_id
    prefix = f"{mac_suffix}-"

    for entity in list(registry.entities.values()):
        if entity.config_entry_id != entry.entry_id or entity.platform != DOMAIN:
            continue
        uid = entity.unique_id
        if not uid or not uid.startswith(prefix):
            continue
        if any(uid.endswith(suffix) for suffix in _MAC_SUFFIX_KEEP):
            continue

        legacy_uid = _legacy_unique_id(entry_id, uid[len(prefix):])
        legacy_eid = registry.async_get_entity_id(DOMAIN, entity.domain, legacy_uid)
        if legacy_eid is not None:
            _LOGGER.info(
                "Removing duplicate entity %s (restoring %s)",
                entity.entity_id,
                legacy_eid,
            )
            registry.async_remove(entity.entity_id)
            continue

        _LOGGER.info(
            "Migrating entity %s unique_id to legacy entry_id form",
            entity.entity_id,
        )
        registry.async_update_entity(entity.entity_id, new_unique_id=legacy_uid)
