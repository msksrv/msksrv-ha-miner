"""Anomaly detection sensors (self-learning baseline)."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_IS_FARM, DOMAIN
from .coordinator import MinerCoordinator
from .health.baseline import BaselineManager
from .health.baseline.messages import format_anomaly_message
from .miner_device_info import get_miner_device_info


async def async_setup_anomaly_sensors(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Register baseline anomaly score sensors for a miner."""
    if config_entry.data.get(CONF_IS_FARM):
        return
    coordinator: MinerCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        [
            MinerAnomalyScoreSensor(coordinator),
            MinerBaselineConfidenceSensor(coordinator),
        ]
    )


class _AnomalyEntity(CoordinatorEntity[MinerCoordinator]):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(coordinator=coordinator)

    @property
    def device_info(self) -> entity.DeviceInfo:
        return get_miner_device_info(self.coordinator)

    @property
    def baseline(self) -> BaselineManager:
        return self.coordinator.baseline

    @property
    def available(self) -> bool:
        return self.coordinator.available


class MinerAnomalyScoreSensor(_AnomalyEntity, SensorEntity):
    """Aggregate anomaly score 0–100 (higher = more anomalous)."""

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}-anomaly_score"
        self._attr_translation_key = "anomaly_score"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:chart-bell-curve"

    @property
    def native_value(self) -> int | None:
        state = self.baseline.anomaly
        if state.confidence <= 0:
            return None
        return state.score

    @property
    def extra_state_attributes(self) -> dict:
        state = self.baseline.anomaly
        lang = self.hass.config.language
        attrs: dict = {
            "confidence": state.confidence,
            "baseline_mode": self.baseline.current_mode,
        }
        if state.detected:
            attrs["severity"] = state.severity
            attrs["reason"] = state.reason
            if state.message:
                attrs["message"] = state.message
            if state.detected_at:
                attrs["detected_at"] = state.detected_at
            attrs.update(state.details)
        if len(state.findings) > 1:
            attrs["findings"] = [
                {
                    "reason": f.reason,
                    "severity": f.severity,
                    "message": format_anomaly_message(f.reason, f.details, lang),
                    **f.details,
                }
                for f in state.findings
            ]
        return attrs


class MinerBaselineConfidenceSensor(_AnomalyEntity, SensorEntity):
    """How reliable the learned baseline is (0–100 %)."""

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}-baseline_confidence"
        self._attr_translation_key = "baseline_confidence"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:brain"

    @property
    def native_value(self) -> int | None:
        conf = self.baseline.anomaly.confidence
        return conf if conf > 0 else None

    @property
    def extra_state_attributes(self) -> dict:
        return {"baseline_mode": self.baseline.current_mode}
