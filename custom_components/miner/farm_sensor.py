"""Sensors for a farm (aggregated miners)."""
from __future__ import annotations

import hashlib

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.components.sensor import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_FARM_AMBIENT_TEMP_ENTITIES
from .const import DOMAIN
from .const import TERA_HASH_PER_SECOND
from .farm_coordinator import MinerFarmCoordinator


def _farm_ambient_entity_ids(entry: ConfigEntry) -> list[str]:
    raw = entry.options.get(CONF_FARM_AMBIENT_TEMP_ENTITIES) or []
    if isinstance(raw, str):
        return [raw] if raw else []
    return list(raw)


async def async_setup_farm_sensors(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create farm aggregate sensors."""
    coordinator: MinerFarmCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities: list[SensorEntity] = [
        FarmTotalHashrateSensor(coordinator),
        FarmTotalPowerKwSensor(coordinator),
        FarmMinerCountSensor(coordinator),
        FarmMinersOnlineSensor(coordinator),
        FarmAlgorithmSensor(coordinator),
        FarmEffectiveChipsPercentSensor(coordinator),
    ]
    for eid in _farm_ambient_entity_ids(config_entry):
        eid = str(eid).strip()
        if eid:
            entities.append(FarmAmbientTemperatureSensor(coordinator, eid))
    async_add_entities(entities)


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
    """Mining algorithm(s) reported by online members."""

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


class FarmEffectiveChipsPercentSensor(_FarmSensor):
    """Weighted effective ASIC chips vs expected across online members."""

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            SensorEntityDescription(
                key="chips_effective_percent",
                native_unit_of_measurement="%",
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=2,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
            "chips_effective_percent",
        )
        self._attr_translation_key = "farm_effective_chips_percent"


class FarmAmbientTemperatureSensor(
    CoordinatorEntity[MinerFarmCoordinator], SensorEntity
):
    """Mirrors a linked sensor state; name follows the source entity."""

    _attr_has_entity_name = False

    def __init__(self, coordinator: MinerFarmCoordinator, source_entity_id: str) -> None:
        super().__init__(coordinator=coordinator)
        self._source_entity_id = source_entity_id
        slug = hashlib.sha256(source_entity_id.encode()).hexdigest()[:12]
        self._attr_unique_id = (
            f"farm-{coordinator.config_entry.entry_id}-amb-{slug}"
        )
        self.entity_description = SensorEntityDescription(
            key=f"amb_{slug}",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        )

    @property
    def device_info(self) -> entity.DeviceInfo:
        return entity.DeviceInfo(
            identifiers={(DOMAIN, f"farm_{self.coordinator.config_entry.entry_id}")},
            name=self.coordinator.config_entry.title,
            manufacturer="MSKSRV",
            model="Farm",
        )

    def _ambient_block(self) -> dict | None:
        return (self.coordinator.data.get("ambient_temperatures") or {}).get(
            self._source_entity_id
        )

    @property
    def name(self) -> str | None:
        block = self._ambient_block()
        if block and block.get("friendly_name"):
            return str(block["friendly_name"])
        return self._source_entity_id

    @property
    def native_value(self):
        block = self._ambient_block()
        if not block:
            return None
        return block.get("value")

    @property
    def native_unit_of_measurement(self) -> str | None:
        block = self._ambient_block()
        if block and block.get("unit_of_measurement"):
            return str(block["unit_of_measurement"])
        return "°C"
