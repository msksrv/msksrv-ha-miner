"""Select entities for a farm device (saved pool preset picker)."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .farm_coordinator import MinerFarmCoordinator
from .farm_pool_presets import farm_pool_preset_slots
from .farm_pool_presets import farm_pool_select_option_labels

_LOGGER = logging.getLogger(__name__)


async def async_setup_farm_selects(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MinerFarmCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([FarmPoolPresetSelect(coordinator)])


class FarmPoolPresetSelect(CoordinatorEntity[MinerFarmCoordinator], SelectEntity):
    """Choose which saved stratum preset buttons apply to the farm."""

    _attr_has_entity_name = True
    _attr_translation_key = "farm_pool_preset"
    _attr_icon = "mdi:server-network"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(coordinator=coordinator)
        self._attr_unique_id = f"farm-{coordinator.config_entry.entry_id}-pool-preset"
        self._current: str | None = None

    def _labels(self) -> list[str]:
        slots = farm_pool_preset_slots(self.coordinator.config_entry.options)
        _, labels = farm_pool_select_option_labels(slots)
        return labels if labels else ["—"]

    @property
    def device_info(self) -> entity.DeviceInfo:
        return entity.DeviceInfo(
            identifiers={(DOMAIN, f"farm_{self.coordinator.config_entry.entry_id}")},
            name=self.coordinator.config_entry.title,
            manufacturer="MSKSRV",
            model="Farm",
        )

    @property
    def options(self) -> list[str]:
        return self._labels()

    @property
    def current_option(self) -> str | None:
        opts = self.options
        if self._current in opts:
            return self._current
        return opts[0] if opts else None

    @property
    def available(self) -> bool:
        slots = farm_pool_preset_slots(self.coordinator.config_entry.options)
        return any(s.get("host") for s in slots)

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            return
        self._current = option
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        opts = self.options
        if self._current not in opts:
            self._current = opts[0] if opts else None
        super()._handle_coordinator_update()
