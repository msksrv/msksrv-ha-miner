"""Buttons for a farm device."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .farm_coordinator import MinerFarmCoordinator


async def async_setup_farm_buttons(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create farm action buttons."""
    coordinator: MinerFarmCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([FarmEmergencyStopButton(coordinator)])


class FarmEmergencyStopButton(CoordinatorEntity[MinerFarmCoordinator], ButtonEntity):
    """Turn off all smart switches linked on member miners (power cut)."""

    _attr_has_entity_name = True
    _attr_translation_key = "farm_emergency_stop"
    _attr_icon = "mdi:electric-switch-closed"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(coordinator=coordinator)
        self._attr_unique_id = f"farm-{coordinator.config_entry.entry_id}-emergency-stop"

    @property
    def device_info(self) -> entity.DeviceInfo:
        return entity.DeviceInfo(
            identifiers={(DOMAIN, f"farm_{self.coordinator.config_entry.entry_id}")},
            name=self.coordinator.config_entry.title,
            manufacturer="MSKSRV",
            model="Farm",
        )

    @property
    def available(self) -> bool:
        return bool(self.coordinator.data.get("emergency_stop_available"))

    async def async_press(self) -> None:
        await self.coordinator.async_emergency_power_off()
