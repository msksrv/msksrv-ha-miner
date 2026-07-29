"""Support for Miner sensors."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from homeassistant.components.sensor import (
    EntityCategory,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import REVOLUTIONS_PER_MINUTE, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_IS_FARM, DOMAIN, JOULES_PER_TERA_HASH, TERA_HASH_PER_SECOND
from .farm_sensor import async_setup_farm_sensors
from .miner_device_info import get_miner_device_info

if TYPE_CHECKING:
    from .coordinator import MinerCoordinator

_LOGGER = logging.getLogger(__name__)


def _sensor_desc(
    sensor_id: str,
    *,
    translation_key: str | None = None,
    **kwargs,
) -> SensorEntityDescription:
    """Build a sensor description with native HA translation_key."""
    return SensorEntityDescription(
        key=sensor_id,
        translation_key=translation_key or sensor_id,
        **kwargs,
    )


ENTITY_DESCRIPTION_KEY_MAP: dict[str, SensorEntityDescription] = {
    "temperature": _sensor_desc(
        "temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "board_temperature": _sensor_desc(
        "board_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "chip_temperature": _sensor_desc(
        "chip_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "hashrate": _sensor_desc(
        "hashrate",
        native_unit_of_measurement=TERA_HASH_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "ideal_hashrate": _sensor_desc(
        "ideal_hashrate",
        native_unit_of_measurement=TERA_HASH_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "active_preset_name": _sensor_desc(
        "active_preset_name",
        icon="mdi:tune-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "board_hashrate": _sensor_desc(
        "board_hashrate",
        native_unit_of_measurement=TERA_HASH_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "board_chips": _sensor_desc(
        "board_chips",
        icon="mdi:chip",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "board_expected_chips": _sensor_desc(
        "board_expected_chips",
        icon="mdi:chip-outline",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "board_effective_chips": _sensor_desc(
        "board_effective_chips",
        icon="mdi:check-decagram-outline",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "board_effective_chips_percent": _sensor_desc(
        "board_effective_chips_percent",
        icon="mdi:percent",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "power_limit": _sensor_desc(
        "power_limit",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "miner_consumption": _sensor_desc(
        "miner_consumption",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "efficiency": _sensor_desc(
        "efficiency",
        native_unit_of_measurement=JOULES_PER_TERA_HASH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "fan_speed": _sensor_desc(
        "fan_speed",
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "ip": _sensor_desc(
        "ip",
        icon="mdi:ip-network",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "mac": _sensor_desc(
        "mac",
        icon="mdi:ethernet",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "model": _sensor_desc(
        "model",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "fw_ver": _sensor_desc(
        "fw_ver",
        translation_key="firmware",
        icon="mdi:memory",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "uptime_formatted": _sensor_desc(
        "uptime_formatted",
        translation_key="uptime",
        icon="mdi:clock-time-eight-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "boards_count": _sensor_desc(
        "boards_count",
        translation_key="boards",
        icon="mdi:view-grid-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "pool_host": _sensor_desc(
        "pool_host",
        icon="mdi:server-network",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "pool_port": _sensor_desc(
        "pool_port",
        icon="mdi:numeric",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "pool_worker": _sensor_desc(
        "pool_worker",
        icon="mdi:account",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "accepted_shares": _sensor_desc(
        "accepted_shares",
        icon="mdi:check-circle-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "rejected_shares": _sensor_desc(
        "rejected_shares",
        icon="mdi:close-circle-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "reject_rate": _sensor_desc(
        "reject_rate",
        icon="mdi:percent",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    if config_entry.data.get(CONF_IS_FARM):
        await async_setup_farm_sensors(hass, config_entry, async_add_entities)
        return

    from .coordinator import MinerCoordinator

    coordinator = cast(
        MinerCoordinator, hass.data[DOMAIN][config_entry.entry_id]
    )

    def _create_miner_entity(sensor: str) -> MinerSensor:
        """Create a miner sensor entity."""
        description = ENTITY_DESCRIPTION_KEY_MAP.get(
            sensor, SensorEntityDescription(key="base_sensor")
        )
        return MinerSensor(
            coordinator=coordinator,
            sensor=sensor,
            entity_description=description,
        )

    def _create_board_entity(board_num: int, sensor: str) -> MinerBoardSensor:
        """Create a board sensor entity."""
        description = ENTITY_DESCRIPTION_KEY_MAP.get(
            sensor, SensorEntityDescription(key="base_sensor")
        )
        return MinerBoardSensor(
            coordinator=coordinator,
            board_num=board_num,
            sensor=sensor,
            entity_description=description,
        )

    def _create_fan_entity(fan_num: int, sensor: str) -> MinerFanSensor:
        """Create a fan sensor entity."""
        description = ENTITY_DESCRIPTION_KEY_MAP.get(
            sensor, SensorEntityDescription(key="base_sensor")
        )
        return MinerFanSensor(
            coordinator=coordinator,
            fan_num=fan_num,
            sensor=sensor,
            entity_description=description,
        )

    sensors = []

    for s in coordinator.data["miner_sensors"]:
        sensors.append(_create_miner_entity(s))

    for s in [
        "ip",
        "mac",
        "model",
        "fw_ver",
        "uptime_formatted",
        "boards_count",
        "pool_host",
        "pool_port",
        "pool_worker",
        "accepted_shares",
        "rejected_shares",
        "reject_rate",
    ]:
        sensors.append(_create_miner_entity(s))

    board_keys = []
    try:
        board_keys = sorted(coordinator.data.get("board_sensors", {}).keys())
    except Exception:
        _LOGGER.debug("Failed to read board sensor keys", exc_info=True)
        board_keys = []

    if not board_keys:
        expected_hashboards = (
            getattr(coordinator.miner, "expected_hashboards", None)
            if coordinator.miner
            else None
        )
        if expected_hashboards:
            board_keys = list(range(int(expected_hashboards)))

    for board in board_keys:
        for s in [
            "board_temperature",
            "chip_temperature",
            "board_hashrate",
            "board_chips",
            "board_expected_chips",
            "board_effective_chips",
            "board_effective_chips_percent",
        ]:
            sensors.append(_create_board_entity(board, s))

    fan_keys = []
    try:
        fan_keys = sorted(coordinator.data.get("fan_sensors", {}).keys())
    except Exception:
        _LOGGER.debug("Failed to read fan sensor keys", exc_info=True)
        fan_keys = []

    if not fan_keys:
        expected_fans = getattr(coordinator.miner, "expected_fans", None) if coordinator.miner else None
        if expected_fans:
            fan_keys = list(range(int(expected_fans)))

    for fan in fan_keys:
        for s in ["fan_speed"]:
            sensors.append(_create_fan_entity(fan, s))

    from .health_sensor import MinerHealthScoreSensor

    sensors.append(MinerHealthScoreSensor(coordinator))

    from .anomaly_sensor import async_setup_anomaly_entities

    async_add_entities(sensors)
    await async_setup_anomaly_entities(hass, config_entry, async_add_entities)


class MinerSensor(CoordinatorEntity["MinerCoordinator"], SensorEntity):
    """Defines a Miner Sensor."""

    _attr_has_entity_name = True

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: MinerCoordinator,
        sensor: str,
        entity_description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator=coordinator)
        self._attr_unique_id = f"{self.coordinator.config_entry.entry_id}-{sensor}"
        self._sensor = sensor
        self.entity_description = entity_description

    @property
    def _sensor_data(self):
        """Return sensor data."""
        try:
            if self._sensor in self.coordinator.data["miner_sensors"]:
                return self.coordinator.data["miner_sensors"][self._sensor]

            return self.coordinator.data.get(self._sensor)
        except LookupError:
            return None

    @property
    def device_info(self) -> entity.DeviceInfo:
        """Return device info."""
        return get_miner_device_info(self.coordinator)

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        return self._sensor_data

    @property
    def extra_state_attributes(self) -> dict | None:
        if self._sensor != "uptime_formatted":
            return None
        raw = self.coordinator.data.get("uptime")
        if raw is None:
            return None
        try:
            return {"uptime_seconds": int(raw)}
        except (TypeError, ValueError):
            return None

    @property
    def available(self) -> bool:
        """Return if entity is available or not."""
        return self.coordinator.available


class MinerBoardSensor(CoordinatorEntity["MinerCoordinator"], SensorEntity):
    """Defines a Miner Board Sensor."""

    _attr_has_entity_name = True

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: MinerCoordinator,
        board_num: int,
        sensor: str,
        entity_description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator=coordinator)
        self._attr_unique_id = (
            f"{self.coordinator.config_entry.entry_id}-board-{board_num}-{sensor}"
        )
        self._board_num = board_num
        self._sensor = sensor
        self.entity_description = entity_description
        self._attr_translation_placeholders = {"board": str(board_num)}

    @property
    def _sensor_data(self):
        """Return sensor data."""
        try:
            return self.coordinator.data["board_sensors"][self._board_num][self._sensor]
        except LookupError:
            return None

    @property
    def device_info(self) -> entity.DeviceInfo:
        """Return device info."""
        return get_miner_device_info(self.coordinator)

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        return self._sensor_data

    @property
    def available(self) -> bool:
        """Return if entity is available or not."""
        return self.coordinator.available


class MinerFanSensor(CoordinatorEntity["MinerCoordinator"], SensorEntity):
    """Defines a Miner Fan Sensor."""

    _attr_has_entity_name = True

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: MinerCoordinator,
        fan_num: int,
        sensor: str,
        entity_description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator=coordinator)
        self._attr_unique_id = (
            f"{self.coordinator.config_entry.entry_id}-fan-{fan_num}-{sensor}"
        )
        self._fan_num = fan_num
        self._sensor = sensor
        self.entity_description = entity_description
        self._attr_translation_placeholders = {"fan": str(fan_num)}
        self._attr_force_update = True

    @property
    def _sensor_data(self):
        """Return sensor data."""
        try:
            return self.coordinator.data["fan_sensors"][self._fan_num][self._sensor]
        except LookupError:
            return None

    @property
    def device_info(self) -> entity.DeviceInfo:
        """Return device info."""
        return get_miner_device_info(self.coordinator)

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        return self._sensor_data

    @property
    def available(self) -> bool:
        """Return if entity is available or not."""
        return self.coordinator.available
