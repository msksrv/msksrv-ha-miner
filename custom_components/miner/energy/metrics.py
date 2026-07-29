"""Derived energy efficiency and cost metrics."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from ..const import FARM_ELEC_TARIFF_FLAT
from ..farm_elec_tou import (
    farm_tariff_mode,
    farm_tou_currency,
    farm_tou_zones_stored,
    integrate_tou_energy_cost,
)
from ..farm_energy_rates import farm_energy_rates_list
from ..health.repairs.membership import farm_entry_ids_for_miner
from .definitions import EnergyRecord, FarmPeriodSnapshot

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


def efficiency_jth(energy_j: float, hash_th: float) -> float | None:
    """Average J/TH for a period (energy per terahash delivered)."""
    if hash_th <= 0 or energy_j <= 0:
        return None
    return round(energy_j / hash_th, 2)


def cost_per_th_s_hour(cost: float, hash_th: float) -> float | None:
    """Currency per (TH/s·hour) using integrated hash work over the period."""
    if hash_th <= 0 or cost <= 0:
        return None
    return round(cost * 3600.0 / hash_th, 4)


def cost_per_ph_day(cost: float, hash_th: float) -> float | None:
    """Currency per petahash-day (farm scale)."""
    if hash_th <= 0 or cost <= 0:
        return None
    return round(cost * 1000.0 * 86400.0 / hash_th, 2)


def miner_period_metrics(record: EnergyRecord) -> dict[str, float | None]:
    return {
        "efficiency_day_jth": efficiency_jth(record.day_energy_j, record.day_hash_th),
        "efficiency_month_jth": efficiency_jth(
            record.month_energy_j, record.month_hash_th
        ),
        "cost_per_th_hour_day": cost_per_th_s_hour(record.day_cost, record.day_hash_th),
        "cost_per_th_hour_month": cost_per_th_s_hour(
            record.month_cost, record.month_hash_th
        ),
    }


def farm_period_from_members(
    members: list[EnergyRecord],
) -> FarmPeriodSnapshot:
    day_kwh = sum(m.day_kwh for m in members)
    month_kwh = sum(m.month_kwh for m in members)
    prev_month_kwh = sum(m.prev_month_kwh for m in members)
    day_energy_j = sum(m.day_energy_j for m in members)
    month_energy_j = sum(m.month_energy_j for m in members)
    day_hash_th = sum(m.day_hash_th for m in members)
    month_hash_th = sum(m.month_hash_th for m in members)
    day_cost = sum(m.day_cost for m in members)
    month_cost = sum(m.month_cost for m in members)
    day_lost = sum(m.day_lost_hash_th for m in members)
    month_lost = sum(m.month_lost_hash_th for m in members)
    day_saved = sum(m.day_idle_saved_kwh for m in members)
    month_saved = sum(m.month_idle_saved_kwh for m in members)
    return FarmPeriodSnapshot(
        day_kwh=round(day_kwh, 3),
        month_kwh=round(month_kwh, 3),
        prev_month_kwh=round(prev_month_kwh, 3),
        day_hash_th=day_hash_th,
        month_hash_th=month_hash_th,
        day_energy_j=day_energy_j,
        month_energy_j=month_energy_j,
        day_cost=day_cost,
        month_cost=month_cost,
        day_lost_hash_th=day_lost,
        month_lost_hash_th=month_lost,
        day_idle_saved_kwh=round(day_saved, 3),
        month_idle_saved_kwh=round(month_saved, 3),
        efficiency_day_jth=efficiency_jth(day_energy_j, day_hash_th),
        efficiency_month_jth=efficiency_jth(month_energy_j, month_hash_th),
        cost_per_th_hour_day=cost_per_th_s_hour(day_cost, day_hash_th),
        cost_per_th_hour_month=cost_per_th_s_hour(month_cost, month_hash_th),
        cost_per_ph_day=cost_per_ph_day(day_cost, day_hash_th),
        currency=_primary_currency_from_records(members),
    )


def farm_period_from_record(record: EnergyRecord, currency: str | None) -> FarmPeriodSnapshot:
    return FarmPeriodSnapshot(
        day_kwh=round(record.day_kwh, 3),
        month_kwh=round(record.month_kwh, 3),
        prev_month_kwh=round(record.prev_month_kwh, 3),
        day_hash_th=record.day_hash_th,
        month_hash_th=record.month_hash_th,
        day_energy_j=record.day_energy_j,
        month_energy_j=record.month_energy_j,
        day_cost=record.day_cost,
        month_cost=record.month_cost,
        day_lost_hash_th=record.day_lost_hash_th,
        month_lost_hash_th=record.month_lost_hash_th,
        day_idle_saved_kwh=round(record.day_idle_saved_kwh, 3),
        month_idle_saved_kwh=round(record.month_idle_saved_kwh, 3),
        efficiency_day_jth=efficiency_jth(record.day_energy_j, record.day_hash_th),
        efficiency_month_jth=efficiency_jth(record.month_energy_j, record.month_hash_th),
        cost_per_th_hour_day=cost_per_th_s_hour(record.day_cost, record.day_hash_th),
        cost_per_th_hour_month=cost_per_th_s_hour(record.month_cost, record.month_hash_th),
        cost_per_ph_day=cost_per_ph_day(record.day_cost, record.day_hash_th),
        currency=currency,
    )


def _primary_currency_from_records(members: list[EnergyRecord]) -> str | None:
    for rec in members:
        if rec.cost_currency:
            return rec.cost_currency
    return None


def delta_cost_for_kwh(
    hass: HomeAssistant,
    farm_entry: ConfigEntry,
    *,
    delta_kwh: float,
    t0: datetime,
    t1: datetime,
) -> tuple[float, str | None]:
    """Return incremental cost and currency for an energy delta using farm tariff."""
    if delta_kwh <= 0:
        return 0.0, None
    opts = farm_entry.options
    mode = farm_tariff_mode(opts)
    if mode == FARM_ELEC_TARIFF_FLAT:
        rates = farm_energy_rates_list(opts)
        if not rates:
            return 0.0, None
        currency, price = rates[0]
        return delta_kwh * float(price), currency
    zones = farm_tou_zones_stored(opts)
    currency = farm_tou_currency(opts)
    if not zones or not currency:
        return 0.0, None
    kw = delta_kwh / max((t1 - t0).total_seconds() / 3600.0, 1e-9)
    cost = integrate_tou_energy_cost(hass, kw, t0, t1, zones)
    return cost, currency


def compute_delta_cost(
    hass: HomeAssistant,
    miner_entry_id: str,
    *,
    delta_kwh: float,
    t0: datetime,
    t1: datetime,
) -> tuple[float, str | None]:
    """Return incremental cost and currency for an energy delta using farm tariff."""
    if delta_kwh <= 0:
        return 0.0, None
    farm = farm_entry_for_miner(hass, miner_entry_id)
    if farm is None:
        return 0.0, None
    return delta_cost_for_kwh(hass, farm, delta_kwh=delta_kwh, t0=t0, t1=t1)


def farm_entry_for_miner(hass: HomeAssistant, miner_entry_id: str) -> ConfigEntry | None:
    for farm_id in farm_entry_ids_for_miner(hass, miner_entry_id):
        entry = hass.config_entries.async_get_entry(farm_id)
        if entry is not None:
            return entry
    return None


def farm_tariff_currency(hass: HomeAssistant, farm_entry: ConfigEntry) -> str | None:
    opts = farm_entry.options
    if farm_tariff_mode(opts) == FARM_ELEC_TARIFF_FLAT:
        rates = farm_energy_rates_list(opts)
        if rates:
            return rates[0][0]
    return farm_tou_currency(opts)
