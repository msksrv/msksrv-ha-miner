"""Energy sensor entities for Energy Dashboard compatibility."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN, JOULES_PER_TERA_HASH
from ..miner_device_info import get_miner_device_info
from .definitions import RESOLVED_UNAVAILABLE, SOURCE_LABEL_KEYS

if TYPE_CHECKING:
    from ..coordinator import MinerCoordinator
    from ..farm_coordinator import MinerFarmCoordinator


def setup_miner_energy_sensors(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    from ..coordinator import MinerCoordinator

    coordinator: MinerCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        [
            MinerEnergyTotalSensor(coordinator),
            MinerEnergyTodaySensor(coordinator),
            MinerEnergyMonthSensor(coordinator),
            MinerEnergyPrevMonthSensor(coordinator),
            MinerEnergySourceSensor(coordinator),
            MinerEnergyDataQualitySensor(coordinator),
            MinerEnergyEfficiencyTodaySensor(coordinator),
            MinerEnergyEfficiencyMonthSensor(coordinator),
            MinerEnergyCostPerThHourTodaySensor(coordinator),
            MinerEnergyLostHashTodaySensor(coordinator),
            MinerEnergyLostHashMonthSensor(coordinator),
            MinerEnergyIdleSavedTodaySensor(coordinator),
            MinerEnergyIdleSavedMonthSensor(coordinator),
        ]
    )


def setup_farm_energy_sensors(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    from ..farm_coordinator import MinerFarmCoordinator

    coordinator: MinerFarmCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities: list[SensorEntity] = [
        FarmEnergyTotalSensor(coordinator),
        FarmEnergyTodaySensor(coordinator),
        FarmEnergyMonthSensor(coordinator),
        FarmEnergyPrevMonthSensor(coordinator),
        FarmEnergyEfficiencyTodaySensor(coordinator),
        FarmEnergyEfficiencyMonthSensor(coordinator),
        FarmEnergyCostPerThHourTodaySensor(coordinator),
        FarmEnergyCostPerPhDaySensor(coordinator),
        FarmEnergyLostHashTodaySensor(coordinator),
        FarmEnergyIdleSavedTodaySensor(coordinator),
    ]
    if _farm_tariff_configured(config_entry):
        entities.extend(
            [
                FarmEnergyCostTodaySensor(coordinator),
                FarmEnergyCostMonthSensor(coordinator),
                FarmEnergyCostTotalSensor(coordinator),
                FarmEnergyCostPrevMonthSensor(coordinator),
                FarmEnergyCostAtPowerSensor(coordinator),
            ]
        )
    async_add_entities(entities)


def _farm_tariff_configured(config_entry: ConfigEntry) -> bool:
    from ..const import FARM_ELEC_TARIFF_DUAL, FARM_ELEC_TARIFF_FLAT
    from ..farm_elec_tou import (
        farm_tariff_mode,
        farm_tou_currency,
        farm_tou_zones_stored,
    )
    from ..farm_energy_rates import farm_energy_rates_list

    opts = config_entry.options
    mode = farm_tariff_mode(opts)
    if mode == FARM_ELEC_TARIFF_FLAT:
        return bool(farm_energy_rates_list(opts))
    cur = farm_tou_currency(opts)
    zones = farm_tou_zones_stored(opts)
    need = 2 if mode == FARM_ELEC_TARIFF_DUAL else 3
    return bool(cur and len(zones) == need)


class _MinerEnergySensorBase(CoordinatorEntity["MinerCoordinator"], SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: MinerCoordinator,
        *,
        suffix: str,
        translation_key: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}-energy-{suffix}"
        self._attr_translation_key = translation_key

    @property
    def device_info(self) -> entity.DeviceInfo:
        return get_miner_device_info(self.coordinator)

    @property
    def available(self) -> bool:
        src = self.coordinator.energy.record.active_source
        return src is not None and src != RESOLVED_UNAVAILABLE

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class MinerEnergyTotalSensor(_MinerEnergySensorBase):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(coordinator, suffix="total", translation_key="energy_total")

    @property
    def native_value(self) -> float | None:
        if not self.available:
            return None
        return self.coordinator.energy.total_kwh

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        mgr = self.coordinator.energy
        src = mgr.record.active_source
        attrs: dict[str, Any] = {
            "energy_source": src,
            "energy_source_label_key": SOURCE_LABEL_KEYS.get(
                src or "", SOURCE_LABEL_KEYS[RESOLVED_UNAVAILABLE]
            ),
            "estimated": mgr.estimated,
        }
        if mgr.record.active_entity_id:
            attrs["source_entity"] = mgr.record.active_entity_id
        q = mgr.data_quality_pct
        if q is not None:
            attrs["data_quality_pct"] = q
        return attrs


class MinerEnergyTodaySensor(_MinerEnergySensorBase):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(coordinator, suffix="today", translation_key="energy_today")

    @property
    def native_value(self) -> float | None:
        if not self.available:
            return None
        return round(self.coordinator.energy.record.day_kwh, 3)


class MinerEnergyMonthSensor(_MinerEnergySensorBase):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(coordinator, suffix="month", translation_key="energy_month")

    @property
    def native_value(self) -> float | None:
        if not self.available:
            return None
        return round(self.coordinator.energy.record.month_kwh, 3)


class MinerEnergyPrevMonthSensor(_MinerEnergySensorBase):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(
            coordinator, suffix="prev-month", translation_key="energy_prev_month"
        )

    @property
    def native_value(self) -> float | None:
        if not self.available:
            return None
        rec = self.coordinator.energy.record
        if not rec.prev_month_key:
            return 0.0
        return round(rec.prev_month_kwh, 3)

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        return {"period_key": self.coordinator.energy.record.prev_month_key}


class MinerEnergySourceSensor(_MinerEnergySensorBase):
    _attr_icon = "mdi:meter-electric-outline"

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(coordinator, suffix="source", translation_key="energy_source")

    @property
    def native_value(self) -> str | None:
        if not self.available:
            return None
        return self.coordinator.energy.record.active_source


class MinerEnergyDataQualitySensor(_MinerEnergySensorBase):
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-donut"

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(
            coordinator, suffix="data-quality", translation_key="energy_data_quality"
        )

    @property
    def native_value(self) -> float | None:
        return self.coordinator.energy.data_quality_pct


class MinerEnergyEfficiencyTodaySensor(_MinerEnergySensorBase):
    _attr_native_unit_of_measurement = JOULES_PER_TERA_HASH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:speedometer"

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(
            coordinator,
            suffix="efficiency-today",
            translation_key="energy_efficiency_today",
        )

    @property
    def native_value(self) -> float | None:
        if not self.available:
            return None
        return self.coordinator.energy.period_metrics.get("efficiency_day_jth")


class MinerEnergyEfficiencyMonthSensor(_MinerEnergySensorBase):
    _attr_native_unit_of_measurement = JOULES_PER_TERA_HASH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:speedometer"

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(
            coordinator,
            suffix="efficiency-month",
            translation_key="energy_efficiency_month",
        )

    @property
    def native_value(self) -> float | None:
        if not self.available:
            return None
        return self.coordinator.energy.period_metrics.get("efficiency_month_jth")


class MinerEnergyCostPerThHourTodaySensor(_MinerEnergySensorBase):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cash-multiple"

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(
            coordinator,
            suffix="cost-th-hour-today",
            translation_key="energy_cost_per_th_hour_today",
        )

    @property
    def native_value(self) -> float | None:
        if not self.available:
            return None
        return self.coordinator.energy.period_metrics.get("cost_per_th_hour_day")

    @property
    def native_unit_of_measurement(self) -> str | None:
        cur = self.coordinator.energy.record.cost_currency
        if not cur:
            return None
        return f"{cur}/(TH/s·h)"


class MinerEnergyLostHashTodaySensor(_MinerEnergySensorBase):
    _attr_native_unit_of_measurement = "TH"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:chart-line-variant"

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(
            coordinator, suffix="lost-hash-today", translation_key="energy_lost_hash_today"
        )

    @property
    def native_value(self) -> float | None:
        if not self.available:
            return None
        return round(self.coordinator.energy.record.day_lost_hash_th, 1)


class MinerEnergyLostHashMonthSensor(_MinerEnergySensorBase):
    _attr_native_unit_of_measurement = "TH"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:chart-line-variant"

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(
            coordinator, suffix="lost-hash-month", translation_key="energy_lost_hash_month"
        )

    @property
    def native_value(self) -> float | None:
        if not self.available:
            return None
        return round(self.coordinator.energy.record.month_lost_hash_th, 1)


class MinerEnergyIdleSavedTodaySensor(_MinerEnergySensorBase):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:leaf"

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(
            coordinator, suffix="idle-saved-today", translation_key="energy_idle_saved_today"
        )

    @property
    def native_value(self) -> float | None:
        if not self.available:
            return None
        return round(self.coordinator.energy.record.day_idle_saved_kwh, 3)


class MinerEnergyIdleSavedMonthSensor(_MinerEnergySensorBase):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:leaf"

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(
            coordinator, suffix="idle-saved-month", translation_key="energy_idle_saved_month"
        )

    @property
    def native_value(self) -> float | None:
        if not self.available:
            return None
        return round(self.coordinator.energy.record.month_idle_saved_kwh, 3)


class _FarmEnergySensorBase(CoordinatorEntity["MinerFarmCoordinator"], SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: MinerFarmCoordinator,
        *,
        suffix: str,
        translation_key: str,
    ) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"farm-{entry.entry_id}-energy-{suffix}"
        self._attr_translation_key = translation_key

    @property
    def device_info(self) -> entity.DeviceInfo:
        entry = self.coordinator.config_entry
        return entity.DeviceInfo(
            identifiers={(DOMAIN, f"farm_{entry.entry_id}")},
            name=entry.title,
            manufacturer="MSKSRV",
            model="Farm",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class FarmEnergyTotalSensor(_FarmEnergySensorBase):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3
    _attr_translation_key = "farm_energy_total"

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(coordinator, suffix="total", translation_key="farm_energy_total")

    @property
    def native_value(self) -> float | None:
        snap = self.coordinator.energy.snapshot
        if snap.source == "unavailable":
            return None
        return snap.total_kwh

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        snap = self.coordinator.energy.snapshot
        return {
            "source": snap.source,
            "physical_meters": snap.physical_meters,
            "calculated_meters": snap.calculated_meters,
            "unmetered_miners": snap.unmetered_miners,
            "coverage": snap.coverage,
            "estimated": snap.estimated,
        }


class FarmEnergyTodaySensor(_FarmEnergySensorBase):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator, suffix="today", translation_key="farm_energy_today"
        )

    @property
    def native_value(self) -> float | None:
        return self.coordinator.energy.period.day_kwh


class FarmEnergyMonthSensor(_FarmEnergySensorBase):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator, suffix="month", translation_key="farm_energy_month"
        )

    @property
    def native_value(self) -> float | None:
        return self.coordinator.energy.period.month_kwh


class FarmEnergyPrevMonthSensor(_FarmEnergySensorBase):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator, suffix="prev-month", translation_key="farm_energy_prev_month"
        )

    @property
    def native_value(self) -> float | None:
        return self.coordinator.energy.period.prev_month_kwh


class FarmEnergyEfficiencyTodaySensor(_FarmEnergySensorBase):
    _attr_native_unit_of_measurement = JOULES_PER_TERA_HASH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:speedometer"

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            suffix="efficiency-today",
            translation_key="farm_energy_efficiency_today",
        )

    @property
    def native_value(self) -> float | None:
        return self.coordinator.energy.period.efficiency_day_jth


class FarmEnergyEfficiencyMonthSensor(_FarmEnergySensorBase):
    _attr_native_unit_of_measurement = JOULES_PER_TERA_HASH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:speedometer"

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            suffix="efficiency-month",
            translation_key="farm_energy_efficiency_month",
        )

    @property
    def native_value(self) -> float | None:
        return self.coordinator.energy.period.efficiency_month_jth


class FarmEnergyCostPerThHourTodaySensor(_FarmEnergySensorBase):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cash-multiple"

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            suffix="cost-th-hour-today",
            translation_key="farm_energy_cost_per_th_hour_today",
        )

    @property
    def native_value(self) -> float | None:
        return self.coordinator.energy.period.cost_per_th_hour_day

    @property
    def native_unit_of_measurement(self) -> str | None:
        cur = self.coordinator.energy.period.currency
        if not cur:
            return None
        return f"{cur}/(TH/s·h)"


class FarmEnergyCostPerPhDaySensor(_FarmEnergySensorBase):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cash-multiple"

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator, suffix="cost-ph-day", translation_key="farm_energy_cost_per_ph_day"
        )

    @property
    def native_value(self) -> float | None:
        return self.coordinator.energy.period.cost_per_ph_day

    @property
    def native_unit_of_measurement(self) -> str | None:
        cur = self.coordinator.energy.period.currency
        if not cur:
            return None
        return f"{cur}/PH·day"


class FarmEnergyLostHashTodaySensor(_FarmEnergySensorBase):
    _attr_native_unit_of_measurement = "TH"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:chart-line-variant"

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            suffix="lost-hash-today",
            translation_key="farm_energy_lost_hash_today",
        )

    @property
    def native_value(self) -> float | None:
        return round(self.coordinator.energy.period.day_lost_hash_th, 1)


class FarmEnergyIdleSavedTodaySensor(_FarmEnergySensorBase):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:leaf"

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            suffix="idle-saved-today",
            translation_key="farm_energy_idle_saved_today",
        )

    @property
    def native_value(self) -> float | None:
        return self.coordinator.energy.period.day_idle_saved_kwh


class _FarmEnergyMonetarySensorBase(_FarmEnergySensorBase):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 2

    @property
    def native_unit_of_measurement(self) -> str | None:
        cur = self.coordinator.energy.record.cost_currency
        if cur:
            return cur
        return self.coordinator.energy.period.currency


class FarmEnergyCostTodaySensor(_FarmEnergyMonetarySensorBase):
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            suffix="cost-today",
            translation_key="farm_energy_cost_today",
        )

    @property
    def native_value(self) -> float | None:
        return round(self.coordinator.energy.period.day_cost, 2)


class FarmEnergyCostMonthSensor(_FarmEnergyMonetarySensorBase):
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            suffix="cost-month",
            translation_key="farm_energy_cost_month",
        )

    @property
    def native_value(self) -> float | None:
        return round(self.coordinator.energy.period.month_cost, 2)


class FarmEnergyCostTotalSensor(_FarmEnergyMonetarySensorBase):
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            suffix="cost-total",
            translation_key="farm_energy_cost_total",
        )

    @property
    def native_value(self) -> float | None:
        return round(self.coordinator.energy.record.total_cost, 2)


class FarmEnergyCostPrevMonthSensor(_FarmEnergyMonetarySensorBase):
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            suffix="cost-prev-month",
            translation_key="farm_energy_cost_prev_month",
        )

    @property
    def native_value(self) -> float | None:
        return round(self.coordinator.energy.record.prev_month_cost, 2)


class FarmEnergyCostAtPowerSensor(_FarmEnergySensorBase):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:cash-clock"

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(
            coordinator,
            suffix="cost-at-power",
            translation_key="farm_energy_cost_at_power",
        )

    @property
    def native_unit_of_measurement(self) -> str | None:
        cur = self.coordinator.energy.record.cost_currency
        if not cur:
            cur = self.coordinator.energy.period.currency
        if not cur:
            return None
        return f"{cur}/h"

    @property
    def native_value(self) -> float | None:
        from homeassistant.util import dt as dt_util

        from ..const import FARM_ELEC_TARIFF_FLAT
        from ..farm_elec_tou import (
            farm_tariff_mode,
            farm_tou_zones_stored,
            price_at_local_dt,
        )
        from ..farm_energy_rates import farm_energy_rates_list

        data = self.coordinator.data
        if not data:
            return None
        try:
            kw = float(data.get("total_power_kw") or 0.0)
        except (TypeError, ValueError):
            return None
        opts = self.coordinator.config_entry.options
        if farm_tariff_mode(opts) == FARM_ELEC_TARIFF_FLAT:
            rates = farm_energy_rates_list(opts)
            if not rates:
                return None
            price = float(rates[0][1])
        else:
            zones = farm_tou_zones_stored(opts)
            if not zones:
                return None
            price = price_at_local_dt(dt_util.as_local(dt_util.utcnow()), zones)
        return round(kw * price, 2)
