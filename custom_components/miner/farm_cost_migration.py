"""Disable deprecated farm_cost_* entities after energy cost migration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryDisabler

from .const import CONF_FARM_LEGACY_COST_SENSORS, CONF_IS_FARM, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _legacy_cost_unique_id_prefix(entry_id: str) -> str:
    return f"farm-{entry_id}-cost-"


def _iter_legacy_farm_cost_entities(
    registry: er.EntityRegistry, entry_id: str
) -> list[er.RegistryEntry]:
    prefix = _legacy_cost_unique_id_prefix(entry_id)
    found: list[er.RegistryEntry] = []
    for entity in er.async_entries_for_config_entry(registry, entry_id):
        if entity.platform == DOMAIN and entity.unique_id.startswith(prefix):
            found.append(entity)
    return found


async def async_apply_legacy_farm_cost_registry(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Disable legacy cost entities unless the user opted into legacy sensors."""
    if not entry.data.get(CONF_IS_FARM):
        return

    registry = er.async_get(hass)
    legacy_enabled = bool(entry.options.get(CONF_FARM_LEGACY_COST_SENSORS))
    entities = _iter_legacy_farm_cost_entities(registry, entry.entry_id)

    if legacy_enabled:
        for entity in entities:
            if entity.disabled_by != RegistryEntryDisabler.INTEGRATION:
                continue
            registry.async_update_entity(entity.entity_id, disabled_by=None)
            _LOGGER.info(
                "Re-enabled legacy farm cost entity %s (legacy option on)",
                entity.entity_id,
            )
        return

    for entity in entities:
        if entity.disabled_by is not None:
            continue
        registry.async_update_entity(
            entity.entity_id,
            disabled_by=RegistryEntryDisabler.INTEGRATION,
        )
        _LOGGER.info(
            "Disabled legacy farm cost entity %s (use energy cost sensors)",
            entity.entity_id,
        )
