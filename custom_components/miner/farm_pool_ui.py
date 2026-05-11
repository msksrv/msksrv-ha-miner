"""Resolve farm pool preset index from the dashboard select entity state."""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .farm_coordinator import MinerFarmCoordinator
from .farm_pool_presets import farm_pool_preset_slots
from .farm_pool_presets import farm_pool_select_option_labels

_LOGGER = logging.getLogger(__name__)


def resolve_farm_pool_slot_from_dashboard(
    hass: HomeAssistant,
    coordinator: MinerFarmCoordinator,
) -> int:
    """Map select entity state to configured slot index, or -1."""
    slots = farm_pool_preset_slots(coordinator.config_entry.options)
    indices, labels = farm_pool_select_option_labels(slots)
    if not indices:
        return -1
    registry = er.async_get(hass)
    uid = f"farm-{coordinator.config_entry.entry_id}-pool-preset"
    entity_id = next(
        (e.entity_id for e in registry.entities.values() if e.unique_id == uid),
        None,
    )
    if entity_id is None:
        return indices[0]
    state = hass.states.get(entity_id)
    if state is None or state.state not in labels:
        return indices[0]
    return indices[labels.index(state.state)]
