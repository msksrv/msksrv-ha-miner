"""Support for Miner action buttons."""
from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MinerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Miner button entities."""
    coordinator: MinerCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    await coordinator.async_config_entry_first_refresh()
    async_add_entities([MinerRebootButton(coordinator=coordinator)])


class MinerRebootButton(CoordinatorEntity[MinerCoordinator], ButtonEntity):
    """Button to reboot a miner."""

    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(coordinator=coordinator)
        self._attr_unique_id = f"{self.coordinator.data['mac']}-reboot"

    @property
    def name(self) -> str | None:
        return f"{self.coordinator.config_entry.title} reboot"

    @property
    def device_info(self) -> entity.DeviceInfo:
        return entity.DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.data["mac"])},
            manufacturer=self.coordinator.data["make"],
            model=self.coordinator.data["model"],
            sw_version=self.coordinator.data["fw_ver"],
            name=f"{self.coordinator.config_entry.title}",
        )

    async def async_press(self) -> None:
        """Handle button press."""
        await self.coordinator.miner.reboot()

    @property
    def available(self) -> bool:
        return self.coordinator.available
