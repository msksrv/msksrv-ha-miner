"""Diagnostic binary sensors for miner health."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_IS_FARM, DOMAIN
from .coordinator import MinerCoordinator
from .miner_device_info import get_miner_device_info

HEALTH_BINARY_KEYS: tuple[tuple[str, BinarySensorDeviceClass | None], ...] = (
    ("hashrate_low", BinarySensorDeviceClass.PROBLEM),
    ("temperature_high", BinarySensorDeviceClass.HEAT),
    ("fan_problem", BinarySensorDeviceClass.PROBLEM),
    ("board_problem", BinarySensorDeviceClass.PROBLEM),
    ("reject_rate_high", BinarySensorDeviceClass.PROBLEM),
    ("pool_problem", BinarySensorDeviceClass.CONNECTIVITY),
    ("power_anomaly", BinarySensorDeviceClass.PROBLEM),
    ("maintenance_required", BinarySensorDeviceClass.PROBLEM),
)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up miner health binary sensors."""
    if config_entry.data.get(CONF_IS_FARM):
        return

    coordinator: MinerCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        [
            MinerHealthBinarySensor(coordinator, key, device_class)
            for key, device_class in HEALTH_BINARY_KEYS
        ]
    )


class MinerHealthBinarySensor(CoordinatorEntity[MinerCoordinator], BinarySensorEntity):
    """Binary diagnostic derived from health evaluation."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: MinerCoordinator,
        flag_key: str,
        device_class: BinarySensorDeviceClass | None,
    ) -> None:
        super().__init__(coordinator=coordinator)
        self._flag_key = flag_key
        self.entity_description = BinarySensorEntityDescription(
            key=f"health_{flag_key}",
            translation_key=f"health_{flag_key}",
            device_class=device_class,
        )
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}-health-{flag_key}"
        )

    @property
    def device_info(self) -> entity.DeviceInfo:
        return get_miner_device_info(self.coordinator)

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.available:
            return None
        health = self.coordinator.data.get("health") or {}
        flags = health.get("flags") or {}
        return bool(flags.get(self._flag_key))

    @property
    def available(self) -> bool:
        return self.coordinator.available
