"""Farm-level energy aggregation."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from ..const import CONF_FARM_ENERGY_PHYSICAL_SENSOR, DOMAIN
from .accumulator import (
    begin_quality_interval,
    data_quality_pct,
    period_interval_seconds,
    register_integrated_interval,
    tick_physical_meter,
)
from .definitions import (
    RESOLVED_PHYSICAL,
    RESOLVED_UNAVAILABLE,
    FarmEnergySnapshot,
    FarmPeriodSnapshot,
    ResolvedEnergySource,
)
from .metrics import (
    delta_cost_for_kwh,
    farm_period_from_members,
    farm_period_from_record,
    farm_tariff_currency,
)
from .periods import integrate_period_sample, reset_periods_if_needed
from .registry import (
    physical_sensor_in_use,
    register_physical_sensor,
    unregister_physical_sensor,
)
from .source import read_energy_kwh
from .storage import EnergyStorage
from .tariff import (
    EFFECTIVE_DATE,
    TARIFF_SCHEDULE,
    TariffHistoryError,
    corrected_cost,
    local_midnight,
    same_tariff,
    tariff_at,
    tariff_currencies,
    tariff_currency,
    with_history_adjustment,
    with_revision,
)
from .tariff_history import async_farm_meter_history

if TYPE_CHECKING:
    from typing import Any

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from ..farm_coordinator import MinerFarmCoordinator

_LOGGER = logging.getLogger(__name__)

FARM_POLL_INTERVAL_S = 15.0
FARM_SOURCE_PHYSICAL = "farm_physical"
FARM_SOURCE_SUMMED = "summed_members"


class FarmEnergyManager:
    """Canonical farm energy total — physical PDU meter or delta sum of miner totals."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._storage = EnergyStorage(hass, f"farm_{entry.entry_id}")
        self._snapshot = FarmEnergySnapshot(total_kwh=0.0, source=FARM_SOURCE_SUMMED)
        self._period = FarmPeriodSnapshot()
        self._tariff_lock = asyncio.Lock()

    @property
    def record(self):
        return self._storage.record

    @property
    def snapshot(self) -> FarmEnergySnapshot:
        return self._snapshot

    @property
    def period(self) -> FarmPeriodSnapshot:
        return self._period

    async def async_load(self) -> None:
        await self._storage.async_load()
        physical = self._available_farm_physical()
        if physical:
            register_physical_sensor(self.hass, self._farm_owner_id(), physical)

    async def async_save(self, *, force: bool = False) -> None:
        await self._storage.async_save(force=force)

    async def async_remove(self) -> None:
        unregister_physical_sensor(self.hass, self._farm_owner_id())
        await self._storage.async_remove()

    def _farm_owner_id(self) -> str:
        return f"farm_{self.entry.entry_id}"

    def _farm_physical_entity(self) -> str | None:
        raw = self.entry.options.get(CONF_FARM_ENERGY_PHYSICAL_SENSOR)
        if not raw:
            return None
        return str(raw).strip() or None

    def _available_farm_physical(self) -> str | None:
        physical = self._farm_physical_entity()
        if not physical:
            return None
        owner = physical_sensor_in_use(
            self.hass, physical, exclude_entry_id=self._farm_owner_id()
        )
        if owner:
            _LOGGER.warning(
                "Farm PDU %s already assigned to %s; farm %s ignores it",
                physical,
                owner,
                self.entry.entry_id,
            )
            return None
        return physical

    def _prune_member_baselines(self, coordinator: MinerFarmCoordinator) -> None:
        record = self._storage.record
        active_ids = {
            entry.entry_id
            for entry, member in coordinator._iter_miner_member_pairs(
                coordinator.device_ids
            )
            if member is not None and hasattr(member, "energy")
        }
        for entry_id in set(record.member_last_totals) - active_ids:
            del record.member_last_totals[entry_id]

    def _member_records(self, coordinator: MinerFarmCoordinator) -> list:
        records = []
        for _entry, member in coordinator._iter_miner_member_pairs(coordinator.device_ids):
            if member is not None and hasattr(member, "energy"):
                records.append(member.energy.record)
        return records

    def _init_member_baselines(self, coordinator: MinerFarmCoordinator) -> None:
        record = self._storage.record
        for entry, member in coordinator._iter_miner_member_pairs(coordinator.device_ids):
            if member is not None and hasattr(member, "energy"):
                record.member_last_totals.setdefault(
                    entry.entry_id, member.energy.total_kwh
                )

    def _tick_member_deltas(self, coordinator: MinerFarmCoordinator) -> float:
        record = self._storage.record
        self._prune_member_baselines(coordinator)
        total_delta = 0.0
        for entry, member in coordinator._iter_miner_member_pairs(coordinator.device_ids):
            if member is None or not hasattr(member, "energy"):
                continue
            entry_id = entry.entry_id
            current = member.energy.total_kwh
            prev = record.member_last_totals.get(entry_id)
            if prev is None:
                record.member_last_totals[entry_id] = current
                continue
            delta = max(current - prev, 0.0)
            record.member_last_totals[entry_id] = current
            total_delta += delta
        if total_delta > 0:
            record.total_kwh += total_delta
        return total_delta

    @property
    def total_cost(self) -> float:
        return corrected_cost(self.entry.options, self.record.total_cost, "total")

    @property
    def previous_month_cost(self) -> float:
        record = self.record
        return corrected_cost(
            self.entry.options, record.prev_month_cost, "months", record.prev_month_key
        )

    async def async_set_tariff(
        self, submitted: dict[str, Any], effective_date: str | None
    ) -> tuple[dict[str, Any], str | None]:
        """Commit the tariff and its historical correction in one entry update."""
        async with self._tariff_lock:
            previous = self.entry.options
            now = dt_util.utcnow()
            try:
                effective = local_midnight(effective_date) if effective_date else now
            except (TypeError, ValueError):
                return previous, "farm_tariff_invalid_date"

            if not effective_date and same_tariff(tariff_at(previous, now), submitted):
                return previous, None
            if effective_date and not tariff_currency(submitted):
                return previous, "farm_tariff_rate_required"
            proposed = with_revision(previous, submitted, effective)
            if len(tariff_currencies(proposed)) > 1:
                if effective_date or previous.get(TARIFF_SCHEDULE):
                    return previous, "farm_tariff_currency_change"
                # Preserve the legacy immediate currency change for unscheduled tariffs.
                proposed = submitted
            if effective_date:
                proposed[EFFECTIVE_DATE] = effective_date
            else:
                proposed.pop(EFFECTIVE_DATE, None)
            if proposed == previous:
                return previous, None

            if (
                effective_date
                and effective < now
                and proposed.get(TARIFF_SCHEDULE) != previous.get(TARIFF_SCHEDULE)
            ):
                record = self.record
                end = dt_util.parse_datetime(record.last_ts) if record.last_ts else None
                if end is None:
                    return previous, "farm_tariff_history_unavailable"
                if effective < end:
                    try:
                        readings = await async_farm_meter_history(
                            self.hass, self.entry.entry_id, effective, end, record.total_kwh
                        )
                        proposed = with_history_adjustment(
                            self.hass, previous, proposed, effective, readings
                        )
                    except TariffHistoryError:
                        return previous, "farm_tariff_history_unavailable"
                await self.async_save(force=True)

            coordinator = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id)
            if self.entry.options != previous or getattr(coordinator, "energy", None) is not self:
                return self.entry.options, "farm_tariff_options_changed"
            self.hass.config_entries.async_update_entry(self.entry, options=proposed)
            return proposed, None

    async def async_tick(self, coordinator: MinerFarmCoordinator) -> None:
        async with self._tariff_lock:
            await self._async_tick(coordinator)

    async def _async_tick(self, coordinator: MinerFarmCoordinator) -> None:
        now = dt_util.utcnow()
        record = self._storage.record
        reset_periods_if_needed(record, now)
        quality_dt_s = begin_quality_interval(record, now, FARM_POLL_INTERVAL_S)
        period_dt_s = period_interval_seconds(quality_dt_s, FARM_POLL_INTERVAL_S)

        members = self._member_records(coordinator)
        hash_period = farm_period_from_members(members)
        physical = self._available_farm_physical()
        raw_physical = read_energy_kwh(self.hass, physical) if physical else None

        if physical and raw_physical is not None:
            if record.farm_aggregate_mode != FARM_SOURCE_PHYSICAL:
                record.farm_aggregate_mode = FARM_SOURCE_PHYSICAL
                record.last_physical_raw_kwh = None

            total_before = record.total_kwh
            t0 = dt_util.parse_datetime(record.last_ts) if record.last_ts else None
            resolved = ResolvedEnergySource(RESOLVED_PHYSICAL, physical, False)
            tick_physical_meter(
                record,
                now=now,
                raw_kwh=raw_physical,
                resolved=resolved,
                expected_interval_s=FARM_POLL_INTERVAL_S,
            )
            if quality_dt_s > 0:
                register_integrated_interval(record, quality_dt_s)

            delta_kwh = max(record.total_kwh - total_before, 0.0)

            delta_cost = 0.0
            currency = farm_tariff_currency(self.hass, self.entry)
            if delta_kwh > 0 and t0 is not None:
                delta_cost, currency = delta_cost_for_kwh(
                    self.hass,
                    self.entry,
                    delta_kwh=delta_kwh,
                    t0=t0,
                    t1=now,
                )
                if currency:
                    record.cost_currency = currency

            if period_dt_s > 0 or delta_kwh > 0 or delta_cost > 0:
                integrate_period_sample(
                    record,
                    now=now,
                    delta_kwh=delta_kwh,
                    delta_cost=delta_cost,
                    hashrate_th_s=0.0,
                    reference_hashrate_th_s=0.0,
                    available=True,
                    dt_s=period_dt_s,
                )

            self._snapshot = FarmEnergySnapshot(
                total_kwh=round(record.total_kwh, 3),
                source=FARM_SOURCE_PHYSICAL,
                physical_meters=1,
                calculated_meters=0,
                unmetered_miners=0,
                coverage=data_quality_pct(record),
                estimated=False,
            )
        else:
            if record.farm_aggregate_mode != FARM_SOURCE_SUMMED:
                record.farm_aggregate_mode = FARM_SOURCE_SUMMED
                record.member_last_totals.clear()
                self._init_member_baselines(coordinator)

            t0 = dt_util.parse_datetime(record.last_ts) if record.last_ts else None
            delta_kwh = self._tick_member_deltas(coordinator)
            if delta_kwh > 0 and quality_dt_s > 0:
                register_integrated_interval(record, quality_dt_s)

            if period_dt_s > 0 or delta_kwh > 0:
                delta_cost = 0.0
                currency = farm_tariff_currency(self.hass, self.entry)
                if delta_kwh > 0 and t0 is not None:
                    delta_cost, currency = delta_cost_for_kwh(
                        self.hass,
                        self.entry,
                        delta_kwh=delta_kwh,
                        t0=t0,
                        t1=now,
                    )
                    if currency:
                        record.cost_currency = currency
                integrate_period_sample(
                    record,
                    now=now,
                    delta_kwh=delta_kwh,
                    delta_cost=delta_cost,
                    hashrate_th_s=0.0,
                    reference_hashrate_th_s=0.0,
                    available=delta_kwh > 0,
                    dt_s=period_dt_s,
                )

            record.last_ts = dt_util.as_utc(now).isoformat()

            self._snapshot = self._build_summed_snapshot(coordinator, record)

        options = self.entry.options
        period = farm_period_from_record(record, tariff_currency(tariff_at(options, now)))
        period = replace(
            period,
            day_cost=corrected_cost(options, record.day_cost, "days", record.day_key),
            month_cost=corrected_cost(options, record.month_cost, "months", record.month_key),
        )
        self._period = _merge_hash_into_period(period, hash_period)
        self._storage.mark_dirty()
        await self.async_save()

    def _build_summed_snapshot(
        self, coordinator: MinerFarmCoordinator, record
    ) -> FarmEnergySnapshot:
        physical = 0
        calculated = 0
        unmetered = 0
        quality_weight = 0.0
        quality_sum = 0.0

        for _entry, member in coordinator._iter_miner_member_pairs(coordinator.device_ids):
            if member is not None and hasattr(member, "energy"):
                mgr = member.energy
                src = mgr.record.active_source
                if src is None or src == RESOLVED_UNAVAILABLE:
                    unmetered += 1
                elif src == RESOLVED_PHYSICAL:
                    physical += 1
                else:
                    calculated += 1
                q = mgr.data_quality_pct
                if q is not None:
                    weight = mgr.total_kwh if mgr.total_kwh > 0 else 1.0
                    quality_weight += weight
                    quality_sum += q * weight
            else:
                unmetered += 1

        coverage = round(quality_sum / quality_weight, 1) if quality_weight > 0 else None
        members = len(list(coordinator._iter_miner_member_pairs(coordinator.device_ids)))
        if members and coverage is None:
            covered = members - unmetered
            coverage = round(100.0 * covered / members, 1)

        return FarmEnergySnapshot(
            total_kwh=round(record.total_kwh, 3),
            source=FARM_SOURCE_SUMMED,
            physical_meters=physical,
            calculated_meters=calculated,
            unmetered_miners=unmetered,
            coverage=coverage,
            estimated=calculated > 0 or unmetered > 0,
        )


def _merge_hash_into_period(
    energy: FarmPeriodSnapshot, hash_period: FarmPeriodSnapshot
) -> FarmPeriodSnapshot:
    from .metrics import (
        cost_per_ph_day,
        cost_per_th_s_hour,
        efficiency_jth,
    )

    return FarmPeriodSnapshot(
        day_kwh=energy.day_kwh,
        month_kwh=energy.month_kwh,
        prev_month_kwh=energy.prev_month_kwh,
        day_hash_th=hash_period.day_hash_th,
        month_hash_th=hash_period.month_hash_th,
        day_energy_j=energy.day_energy_j,
        month_energy_j=energy.month_energy_j,
        day_cost=energy.day_cost,
        month_cost=energy.month_cost,
        day_lost_hash_th=hash_period.day_lost_hash_th,
        month_lost_hash_th=hash_period.month_lost_hash_th,
        day_idle_saved_kwh=hash_period.day_idle_saved_kwh,
        month_idle_saved_kwh=hash_period.month_idle_saved_kwh,
        efficiency_day_jth=efficiency_jth(energy.day_energy_j, hash_period.day_hash_th),
        efficiency_month_jth=efficiency_jth(
            energy.month_energy_j, hash_period.month_hash_th
        ),
        cost_per_th_hour_day=cost_per_th_s_hour(energy.day_cost, hash_period.day_hash_th),
        cost_per_th_hour_month=cost_per_th_s_hour(
            energy.month_cost, hash_period.month_hash_th
        ),
        cost_per_ph_day=cost_per_ph_day(energy.day_cost, hash_period.day_hash_th),
        currency=energy.currency or hash_period.currency,
    )
