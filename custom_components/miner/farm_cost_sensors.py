"""Farm electricity cost sensors (optional tariffs, integrate power over time)."""

from __future__ import annotations

from typing import Literal

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.components.sensor import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.helpers import entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .farm_coordinator import MinerFarmCoordinator
from .farm_energy_rates import farm_energy_rates_list

PeriodKind = Literal["hour", "day", "month", "all"]


def _period_key_local(kind: PeriodKind, when) -> str | None:
    """Stable string for calendar period (local time)."""
    local = dt_util.as_local(when)
    if kind == "hour":
        return f"{local.year:04d}-{local.month:02d}-{local.day:02d}T{local.hour:02d}"
    if kind == "day":
        return f"{local.year:04d}-{local.month:02d}-{local.day:02d}"
    if kind == "month":
        return f"{local.year:04d}-{local.month:02d}"
    return None


class FarmCostSensorBase(
    CoordinatorEntity[MinerFarmCoordinator], RestoreEntity, SensorEntity
):
    """Integrate Σ(kW × Δh) × price; optional calendar reset + restore."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: MinerFarmCoordinator,
        currency: str,
        price_per_kwh: float,
        period: PeriodKind,
        translation_key: str,
        entity_key_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._currency = currency
        self._price_per_kwh = price_per_kwh
        self._period = period
        cur_safe = currency.lower()
        self._attr_unique_id = (
            f"farm-{coordinator.config_entry.entry_id}-cost-{entity_key_suffix}-{cur_safe}"
        )
        self.entity_description = SensorEntityDescription(
            key=f"farm_cost_{entity_key_suffix}_{cur_safe}",
            translation_key=translation_key,
            device_class=SensorDeviceClass.MONETARY,
            native_unit_of_measurement=currency,
            state_class=(
                SensorStateClass.TOTAL_INCREASING
                if period == "all"
                else SensorStateClass.TOTAL
            ),
            suggested_display_precision=2,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        self._attr_translation_placeholders = {"currency": currency}
        self._accumulated: float = 0.0
        self._period_key_active: str | None = _period_key_local(period, dt_util.utcnow())
        self._last_ts = None

    @property
    def device_info(self) -> entity.DeviceInfo:
        return entity.DeviceInfo(
            identifiers={(DOMAIN, f"farm_{self.coordinator.config_entry.entry_id}")},
            name=self.coordinator.config_entry.title,
            manufacturer="MSKSRV",
            model="Farm",
        )

    def _current_price(self) -> float:
        for cur, price in farm_energy_rates_list(self.coordinator.config_entry.options):
            if cur == self._currency:
                return float(price)
        return float(self._price_per_kwh)

    async def async_added_to_hass(self) -> None:
        await RestoreEntity.async_added_to_hass(self)
        last = await self.async_get_last_state()
        now = dt_util.utcnow()
        pk_now = _period_key_local(self._period, now)

        if self._period == "all":
            if last and last.state not in ("unknown", "unavailable", ""):
                try:
                    self._accumulated = float(last.state)
                except ValueError:
                    self._accumulated = 0.0
            self._period_key_active = None
        else:
            old_pk = last.attributes.get("period_key") if last else None
            if (
                last
                and last.state not in ("unknown", "unavailable", "")
                and old_pk == pk_now
            ):
                try:
                    self._accumulated = float(last.state)
                except ValueError:
                    self._accumulated = 0.0
            else:
                self._accumulated = 0.0
            self._period_key_active = pk_now

        self._last_ts = None
        self._update_native_from_accum()
        await SensorEntity.async_added_to_hass(self)
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self._tick()
        super()._handle_coordinator_update()

    def _tick(self) -> None:
        data = self.coordinator.data
        if not data:
            return
        try:
            kw = float(data.get("total_power_kw") or 0.0)
        except (TypeError, ValueError):
            kw = 0.0
        price = self._current_price()
        now = dt_util.utcnow()

        if self._last_ts is None:
            self._last_ts = now
            self._update_native_from_accum()
            return

        dt_h = (now - self._last_ts).total_seconds() / 3600.0
        self._last_ts = now
        if dt_h <= 0:
            self._update_native_from_accum()
            return

        d_kwh = kw * dt_h
        d_cost = d_kwh * price

        if self._period != "all":
            pk_now = _period_key_local(self._period, now)
            if pk_now != self._period_key_active:
                self._accumulated = 0.0
                self._period_key_active = pk_now

        self._accumulated += d_cost
        self._update_native_from_accum()

    def _update_native_from_accum(self) -> None:
        self._attr_native_value = round(self._accumulated, 4)

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        attrs: dict[str, str] = {}
        pk = _period_key_local(self._period, dt_util.utcnow())
        if pk is not None:
            attrs["period_key"] = pk
        return attrs


class FarmCostAtCurrentPowerSensor(CoordinatorEntity[MinerFarmCoordinator], SensorEntity):
    """Instantaneous cost rate: current kW × price = cost if power stayed 1 h."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, coordinator: MinerFarmCoordinator, currency: str, price_per_kwh: float
    ) -> None:
        super().__init__(coordinator)
        self._currency = currency
        self._price_per_kwh = price_per_kwh
        cur_safe = currency.lower()
        self._attr_unique_id = (
            f"farm-{coordinator.config_entry.entry_id}-cost-now-{cur_safe}"
        )
        self.entity_description = SensorEntityDescription(
            key=f"farm_cost_now_{cur_safe}",
            translation_key="farm_cost_now",
            device_class=SensorDeviceClass.MONETARY,
            native_unit_of_measurement=currency,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=2,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        self._attr_translation_placeholders = {"currency": currency}

    @property
    def device_info(self) -> entity.DeviceInfo:
        return entity.DeviceInfo(
            identifiers={(DOMAIN, f"farm_{self.coordinator.config_entry.entry_id}")},
            name=self.coordinator.config_entry.title,
            manufacturer="MSKSRV",
            model="Farm",
        )

    def _current_price(self) -> float:
        for cur, price in farm_energy_rates_list(self.coordinator.config_entry.options):
            if cur == self._currency:
                return float(price)
        return float(self._price_per_kwh)

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if not data:
            return None
        try:
            kw = float(data.get("total_power_kw") or 0.0)
        except (TypeError, ValueError):
            return None
        return round(kw * self._current_price(), 4)


def setup_farm_cost_sensors(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add cost sensors when at least one tariff is configured."""
    coordinator: MinerFarmCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    rates = farm_energy_rates_list(config_entry.options)
    if not rates:
        return

    entities: list[SensorEntity] = []
    for currency, price in rates:
        entities.append(FarmCostAtCurrentPowerSensor(coordinator, currency, price))
        entities.append(
            FarmCostSensorBase(
                coordinator,
                currency,
                price,
                "hour",
                "farm_cost_hour",
                "hour",
            )
        )
        entities.append(
            FarmCostSensorBase(
                coordinator,
                currency,
                price,
                "day",
                "farm_cost_day",
                "day",
            )
        )
        entities.append(
            FarmCostSensorBase(
                coordinator,
                currency,
                price,
                "month",
                "farm_cost_month",
                "month",
            )
        )
        entities.append(
            FarmCostSensorBase(
                coordinator,
                currency,
                price,
                "all",
                "farm_cost_total",
                "total",
            )
        )
    async_add_entities(entities)
