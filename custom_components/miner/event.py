"""Event entities for miner and farm activity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_IS_FARM, DOMAIN
from .events.definitions import FARM_EVENT_TYPES, MINER_EVENT_TYPES
from .events.manager import FarmEventManager, MinerEventManager
from .farm_coordinator import MinerFarmCoordinator
from .miner_device_info import get_miner_device_info

if TYPE_CHECKING:
    from .coordinator import MinerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up activity event entities."""
    if config_entry.data.get(CONF_IS_FARM):
        coordinator: MinerFarmCoordinator = hass.data[DOMAIN][config_entry.entry_id]
        async_add_entities([FarmActivityEventEntity(coordinator)])
        return

    coordinator: MinerCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([MinerActivityEventEntity(coordinator)])


class _ActivityEventMixin:
    """Shared trigger helper for miner/farm activity event entities."""

    @callback
    def async_trigger(self, event_type: str, data: dict) -> None:
        """Record an activity event on the entity and update HA state."""
        self._trigger_event(event_type, data)
        self.async_write_ha_state()


class MinerActivityEventEntity(_ActivityEventMixin, EventEntity):
    """Miner device activity log for automations."""

    _attr_has_entity_name = True
    _attr_translation_key = "activity"
    _attr_event_types = list(MINER_EVENT_TYPES)

    def __init__(self, coordinator: MinerCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}-activity"
        coordinator.events.bind_entity(self)

    @property
    def device_info(self) -> entity.DeviceInfo:
        return get_miner_device_info(self._coordinator)


class FarmActivityEventEntity(_ActivityEventMixin, EventEntity):
    """Farm device activity log for automations."""

    _attr_has_entity_name = True
    _attr_translation_key = "farm_activity"
    _attr_event_types = list(FARM_EVENT_TYPES)

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        self._coordinator = coordinator
        entry = coordinator.config_entry
        self._attr_unique_id = f"farm-{entry.entry_id}-activity"
        coordinator.events.bind_entity(self)

    @property
    def device_info(self) -> entity.DeviceInfo:
        entry = self._coordinator.config_entry
        return entity.DeviceInfo(
            identifiers={(DOMAIN, f"farm_{entry.entry_id}")},
            name=entry.title,
            manufacturer="MSKSRV",
            model="Farm",
        )
