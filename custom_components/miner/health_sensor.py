"""Health score sensor for a miner device."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.helpers import entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import MinerCoordinator
from .miner_device_info import get_miner_device_info

HEALTH_SCORE_DESCRIPTION = SensorEntityDescription(
    key="health_score",
    translation_key="health_score",
    native_unit_of_measurement=PERCENTAGE,
    state_class=SensorStateClass.MEASUREMENT,
    icon="mdi:heart-pulse",
)


class MinerHealthScoreSensor(CoordinatorEntity[MinerCoordinator], SensorEntity):
    """Overall miner health score (0–100 %)."""

    _attr_has_entity_name = True
    entity_description = HEALTH_SCORE_DESCRIPTION

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(coordinator=coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}-health_score"

    @property
    def device_info(self) -> entity.DeviceInfo:
        return get_miner_device_info(self.coordinator)

    @property
    def native_value(self) -> int | None:
        health = self.coordinator.data.get("health") or {}
        return health.get("score")

    @property
    def extra_state_attributes(self) -> dict:
        health = self.coordinator.data.get("health") or {}
        attrs: dict = {}
        components = health.get("components")
        if components:
            attrs["components"] = {
                k: round(v, 1) if v is not None else None
                for k, v in components.items()
            }
        flags = health.get("flags")
        if flags:
            attrs["issues"] = [
                k
                for k, v in flags.items()
                if v
                and k
                not in ("share_stale", "temperature_warning", "maintenance_required")
            ]
        if flags and flags.get("temperature_high"):
            attrs["temperature_status"] = "critical"
        elif flags and flags.get("temperature_warning"):
            attrs["temperature_status"] = "warning"
        else:
            attrs["temperature_status"] = "ok"
        attrs["data_coverage"] = health.get("data_coverage", 0)
        profile = health.get("threshold_profile")
        if profile:
            attrs["threshold_profile"] = profile
        attrs["operating_state"] = (
            "mining" if self.coordinator.data.get("is_mining") else "stopped"
        )
        secs = self.coordinator.data.get("seconds_since_share")
        if secs is not None:
            attrs["seconds_since_share"] = round(float(secs), 0)
        errors = self.coordinator.data.get("errors") or []
        if errors:
            attrs["errors"] = errors
        if self.coordinator.data.get("fault_light"):
            attrs["fault_light"] = True
        return attrs

    @property
    def available(self) -> bool:
        return self.coordinator.available
