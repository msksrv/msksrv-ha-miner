"""Sensors for a farm (aggregated miners)."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.components.sensor import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .const import TERA_HASH_PER_SECOND
from .farm_coordinator import MinerFarmCoordinator


async def async_setup_farm_sensors(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create farm aggregate sensors."""
    coordinator: MinerFarmCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        [
            FarmTotalHashrateSensor(coordinator),
            FarmTotalPowerKwSensor(coordinator),
            FarmMinerCountSensor(coordinator),
            FarmMinersOnlineSensor(coordinator),
            FarmAlgorithmSensor(coordinator),
        ]
    )


class _FarmSensor(CoordinatorEntity[MinerFarmCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MinerFarmCoordinator,
        entity_description: SensorEntityDescription,
        key: str,
    ) -> None:
        super().__init__(coordinator=coordinator)
        self.entity_description = entity_description
        self._data_key = key
        self._attr_unique_id = (
            f"farm-{coordinator.config_entry.entry_id}-{entity_description.key}"
        )

    @property
    def device_info(self) -> entity.DeviceInfo:
        return entity.DeviceInfo(
            identifiers={(DOMAIN, f"farm_{self.coordinator.config_entry.entry_id}")},
            name=self.coordinator.config_entry.title,
            manufacturer="MSKSRV",
            model="Farm",
        )

    @property
    def native_value(self):
        return self.coordinator.data.get(self._data_key)


class FarmTotalHashrateSensor(_FarmSensor):
    """Sum of member miner hashrates (TH/s)."""

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            SensorEntityDescription(
                key="total_hashrate",
                native_unit_of_measurement=TERA_HASH_PER_SECOND,
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=2,
            ),
            "total_hashrate_th",
        )
        self._attr_translation_key = "farm_total_hashrate"


class FarmTotalPowerKwSensor(_FarmSensor):
    """Sum of member miner power draw (kW)."""

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            SensorEntityDescription(
                key="total_power_kw",
                native_unit_of_measurement="kW",
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=3,
            ),
            "total_power_kw",
        )
        self._attr_translation_key = "farm_total_power_kw"


class FarmMinerCountSensor(_FarmSensor):
    """Number of miner devices attached to the farm."""

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            SensorEntityDescription(
                key="miner_count",
                state_class=SensorStateClass.MEASUREMENT,
            ),
            "miner_count",
        )
        self._attr_translation_key = "farm_miner_count"


class FarmMinersOnlineSensor(_FarmSensor):
    """Members that responded on the last poll."""

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            SensorEntityDescription(
                key="miners_online",
                state_class=SensorStateClass.MEASUREMENT,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
            "miners_online",
        )
        self._attr_translation_key = "farm_miners_online"


class FarmAlgorithmSensor(_FarmSensor):
    """Mining algorithm (Bitcoin ASICs → SHA256d)."""

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            SensorEntityDescription(
                key="algorithm",
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
            "algorithm",
        )
        self._attr_translation_key = "farm_algorithm"
