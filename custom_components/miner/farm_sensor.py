"""Sensors for a farm (aggregated miners)."""
from __future__ import annotations

import hashlib

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_FARM_AMBIENT_TEMP_ENTITIES, DOMAIN, JOULES_PER_TERA_HASH, TERA_HASH_PER_SECOND
from .farm_coordinator import MinerFarmCoordinator
from .farm_cost_sensors import setup_farm_cost_sensors


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
        FarmMinersHealthySensor(coordinator),
        FarmMinersWithIssuesSensor(coordinator),
        FarmExpectedHashrateSensor(coordinator),
        FarmLostHashrateSensor(coordinator),
        FarmAverageEfficiencySensor(coordinator),
        FarmHottestMinerSensor(coordinator),
        FarmWorstRejectRateSensor(coordinator),
        FarmAlgorithmSensor(coordinator),
        FarmEffectiveChipsPercentSensor(coordinator),
        FarmHealthScoreSensor(coordinator),
    ]
    for eid in _farm_ambient_entity_ids(config_entry):
        eid = str(eid).strip()
        if eid:
            entities.append(FarmAmbientTemperatureSensor(coordinator, eid))
    async_add_entities(entities)
    setup_farm_cost_sensors(hass, config_entry, async_add_entities)


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
                device_class=SensorDeviceClass.POWER,
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


class FarmMinersHealthySensor(_FarmSensor):
    """Online miners without active health flags or anomalies."""

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            SensorEntityDescription(
                key="miners_healthy",
                state_class=SensorStateClass.MEASUREMENT,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
            "miners_healthy",
        )
        self._attr_translation_key = "farm_miners_healthy"


class FarmMinersWithIssuesSensor(_FarmSensor):
    """Online miners with warning or problem status."""

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            SensorEntityDescription(
                key="miners_with_issues",
                state_class=SensorStateClass.MEASUREMENT,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
            "miners_with_issues",
        )
        self._attr_translation_key = "farm_miners_with_issues"


class _FarmHashrateMetricSensor(_FarmSensor):
    """Base for farm hashrate metrics that disable on mixed algorithms."""

    @property
    def available(self) -> bool:
        if self.coordinator.data.get("hashrate_metrics_mixed_algorithms"):
            return False
        return super().available


class FarmExpectedHashrateSensor(_FarmHashrateMetricSensor):
    """Sum of expected hashrate per member (baseline or ideal)."""

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            SensorEntityDescription(
                key="expected_hashrate",
                native_unit_of_measurement=TERA_HASH_PER_SECOND,
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=2,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
            "expected_hashrate_th",
        )
        self._attr_translation_key = "farm_expected_hashrate"

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        attrs = {
            "expected_miners": data.get("expected_miners", 0),
            "expected_miners_unknown": data.get("expected_miners_unknown", 0),
            "reference": data.get("expected_hashrate_reference"),
        }
        if data.get("hashrate_metrics_mixed_algorithms"):
            attrs["reason"] = "mixed_algorithms"
            attrs["algorithms"] = data.get("hashrate_metrics_algorithms") or []
        return attrs


class FarmLostHashrateSensor(_FarmHashrateMetricSensor):
    """Expected minus actual farm hashrate."""

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            SensorEntityDescription(
                key="lost_hashrate",
                native_unit_of_measurement=TERA_HASH_PER_SECOND,
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=2,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
            "lost_hashrate_th",
        )
        self._attr_translation_key = "farm_lost_hashrate"

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        attrs = {
            "expected_miners": data.get("expected_miners", 0),
            "expected_miners_unknown": data.get("expected_miners_unknown", 0),
            "lost_percent": data.get("lost_hashrate_percent"),
            "reference": data.get("expected_hashrate_reference"),
        }
        if data.get("hashrate_metrics_mixed_algorithms"):
            attrs["reason"] = "mixed_algorithms"
            attrs["algorithms"] = data.get("hashrate_metrics_algorithms") or []
        return attrs


class FarmAverageEfficiencySensor(_FarmSensor):
    """Weighted farm efficiency: total power / total hashrate."""

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            SensorEntityDescription(
                key="average_efficiency",
                native_unit_of_measurement=JOULES_PER_TERA_HASH,
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=1,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
            "average_efficiency_jth",
        )
        self._attr_translation_key = "farm_average_efficiency"

    @property
    def available(self) -> bool:
        if self.coordinator.data.get("hashrate_metrics_mixed_algorithms"):
            return False
        return super().available

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if not data.get("hashrate_metrics_mixed_algorithms"):
            return {}
        return {
            "reason": "mixed_algorithms",
            "algorithms": data.get("hashrate_metrics_algorithms") or [],
        }


class FarmHottestMinerSensor(_FarmSensor):
    """Highest chip/board temperature among online miners."""

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            SensorEntityDescription(
                key="hottest_miner",
                device_class=SensorDeviceClass.TEMPERATURE,
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=0,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
            "hottest_miner",
        )
        self._attr_translation_key = "farm_hottest_miner"

    @property
    def native_value(self):
        block = self.coordinator.data.get("hottest_miner") or {}
        return block.get("temperature")

    @property
    def native_unit_of_measurement(self) -> str | None:
        return "°C"

    @property
    def extra_state_attributes(self) -> dict:
        block = self.coordinator.data.get("hottest_miner") or {}
        attrs: dict = {}
        if block.get("miner"):
            attrs["miner"] = block["miner"]
        if block.get("ip"):
            attrs["ip"] = block["ip"]
        if block.get("temperature_source"):
            attrs["temperature_source"] = block["temperature_source"]
        return attrs


class FarmWorstRejectRateSensor(_FarmSensor):
    """Highest reject rate among miners with enough share statistics."""

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            SensorEntityDescription(
                key="worst_reject_rate",
                native_unit_of_measurement=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=1,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
            "worst_reject_rate",
        )
        self._attr_translation_key = "farm_worst_reject_rate"

    @property
    def native_value(self):
        block = self.coordinator.data.get("worst_reject_rate") or {}
        return block.get("reject_rate")

    @property
    def extra_state_attributes(self) -> dict:
        block = self.coordinator.data.get("worst_reject_rate") or {}
        attrs: dict = {}
        if block.get("miner"):
            attrs["miner"] = block["miner"]
        if block.get("accepted_shares") is not None:
            attrs["accepted_shares"] = block["accepted_shares"]
        if block.get("rejected_shares") is not None:
            attrs["rejected_shares"] = block["rejected_shares"]
        return attrs


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


class FarmHealthScoreSensor(_FarmSensor):
    """Aggregate health score of farm members."""

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            SensorEntityDescription(
                key="health_score",
                native_unit_of_measurement="%",
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=0,
                entity_category=EntityCategory.DIAGNOSTIC,
                icon="mdi:heart-pulse",
            ),
            "health_score",
        )
        self._attr_translation_key = "farm_health_score"

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        status = data.get("health_status_counts") or {}
        attrs = {
            "healthy": status.get("healthy", 0),
            "warning": status.get("warning", 0),
            "problem": status.get("problem", 0),
            "offline": status.get("offline", 0),
            "unknown": status.get("unknown", 0),
            "miners_evaluated": data.get("health_miners_evaluated", 0),
            "miners_offline": data.get("health_miners_offline", 0),
            "issues": data.get("health_issues") or {},
        }
        problem_devices = data.get("health_problem_devices") or []
        if problem_devices:
            attrs["problem_devices"] = problem_devices
        truncated = data.get("health_problem_devices_truncated") or 0
        if truncated:
            attrs["problem_devices_truncated"] = truncated
        return attrs


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
