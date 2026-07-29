"""Track physical energy sensor assignments across miners and farm PDU."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from ..const import (
    CONF_ENERGY_PHYSICAL_SENSOR,
    CONF_FARM_ENERGY_PHYSICAL_SENSOR,
    CONF_IS_FARM,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
_REGISTRY_KEY = "energy_physical_registry"


def _registry(hass: HomeAssistant) -> dict[str, str]:
    root = hass.data.setdefault(DOMAIN, {})
    reg = root.get(_REGISTRY_KEY)
    if not isinstance(reg, dict):
        reg = {}
        root[_REGISTRY_KEY] = reg
    return reg


def register_physical_sensor(
    hass: HomeAssistant, entry_id: str, entity_id: str | None
) -> None:
    reg = _registry(hass)
    for eid, owner in list(reg.items()):
        if owner == entry_id:
            del reg[eid]
    if entity_id:
        reg[str(entity_id).strip()] = entry_id


def unregister_physical_sensor(hass: HomeAssistant, entry_id: str) -> None:
    reg = _registry(hass)
    for eid, owner in list(reg.items()):
        if owner == entry_id:
            del reg[eid]


def physical_sensor_owner(hass: HomeAssistant, entity_id: str) -> str | None:
    return _registry(hass).get(str(entity_id).strip())


def _entry_owner_id(entry) -> str:
    if entry.data.get(CONF_IS_FARM):
        return f"farm_{entry.entry_id}"
    return entry.entry_id


def _is_excluded_owner(entry, exclude_entry_id: str | None) -> bool:
    if not exclude_entry_id:
        return False
    owner_id = _entry_owner_id(entry)
    return exclude_entry_id in (entry.entry_id, owner_id)


def physical_entity_owner(
    hass: HomeAssistant,
    entity_id: str,
    *,
    exclude_entry_id: str | None = None,
) -> str | None:
    """Return config/runtime owner of a physical energy entity, if any."""
    eid = str(entity_id).strip()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if _is_excluded_owner(entry, exclude_entry_id):
            continue
        if entry.data.get(CONF_IS_FARM):
            farm_phys = (entry.options.get(CONF_FARM_ENERGY_PHYSICAL_SENSOR) or "").strip()
            if farm_phys == eid:
                return f"farm_{entry.entry_id}"
        else:
            phys = (entry.options.get(CONF_ENERGY_PHYSICAL_SENSOR) or "").strip()
            if phys == eid:
                return entry.entry_id

    owner = physical_sensor_owner(hass, eid)
    if owner and owner != exclude_entry_id:
        return owner
    return None


def physical_sensor_in_use(
    hass: HomeAssistant, entity_id: str, *, exclude_entry_id: str | None = None
) -> str | None:
    return physical_entity_owner(hass, entity_id, exclude_entry_id=exclude_entry_id)
