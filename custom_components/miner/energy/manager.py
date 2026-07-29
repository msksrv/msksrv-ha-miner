"""Per-miner energy accumulation orchestration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from .accumulator import (
    begin_quality_interval,
    data_quality_pct,
    period_interval_seconds,
    preserve_total_on_source_change,
    register_integrated_interval,
    tick_physical_meter,
    tick_power_integration,
)
from .definitions import (
    RESOLVED_MINER_POWER,
    RESOLVED_PHYSICAL,
    RESOLVED_SWITCH_POWER,
    RESOLVED_UNAVAILABLE,
    SOURCE_LABEL_KEYS,
    EnergyRecord,
    ResolvedEnergySource,
)
from .metrics import compute_delta_cost, miner_period_metrics
from .periods import (
    integrate_period_sample,
    miner_hashrate_th_s,
    miner_reference_hashrate_th_s,
    reset_periods_if_needed,
    update_nominal_power_from_telemetry,
)
from .registry import register_physical_sensor, unregister_physical_sensor
from .source import (
    miner_power_w,
    read_energy_kwh,
    read_power_w,
    resolve_miner_energy_source,
)
from .storage import EnergyStorage

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from ..coordinator import MinerCoordinator

_LOGGER = logging.getLogger(__name__)

MINER_POLL_INTERVAL_S = 10.0


class MinerEnergyManager:
    """Track canonical miner energy total with source selection and persistence."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: MinerCoordinator,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self._coordinator = coordinator
        self._storage = EnergyStorage(hass, entry.entry_id)
        self._resolved: ResolvedEnergySource | None = None

    @property
    def record(self) -> EnergyRecord:
        return self._storage.record

    @property
    def total_kwh(self) -> float:
        return round(self._storage.record.total_kwh, 3)

    @property
    def source_label_key(self) -> str:
        src = self._storage.record.active_source or RESOLVED_UNAVAILABLE
        return SOURCE_LABEL_KEYS.get(src, SOURCE_LABEL_KEYS[RESOLVED_UNAVAILABLE])

    @property
    def data_quality_pct(self) -> float | None:
        return data_quality_pct(self._storage.record)

    @property
    def estimated(self) -> bool:
        if self._resolved is None:
            return True
        return bool(self._resolved.estimated)

    @property
    def period_metrics(self) -> dict[str, float | None]:
        return miner_period_metrics(self._storage.record)

    def _sync_physical_registry(self, resolved: ResolvedEnergySource) -> None:
        if resolved.source == RESOLVED_PHYSICAL and resolved.entity_id:
            register_physical_sensor(
                self.hass, self.entry.entry_id, resolved.entity_id
            )
        else:
            unregister_physical_sensor(self.hass, self.entry.entry_id)

    def _baseline_hashrate(self, data: dict[str, Any] | None) -> float | None:
        health = (data or {}).get("health") or {}
        ref = health.get("hashrate_reference")
        if ref == "baseline":
            return self._coordinator.baseline.baseline_medians(data or {}).get(
                "hashrate"
            )
        if ref is not None:
            try:
                return float(ref) or None
            except (TypeError, ValueError):
                return None
        return None

    async def async_load(self) -> None:
        await self._storage.async_load()
        self._resolved = resolve_miner_energy_source(self.hass, self.entry)
        self._sync_physical_registry(self._resolved)

    async def async_save(self, *, force: bool = False) -> None:
        await self._storage.async_save(force=force)

    async def async_remove(self) -> None:
        unregister_physical_sensor(self.hass, self.entry.entry_id)
        await self._storage.async_remove()

    def reload_options(self) -> None:
        new_resolved = resolve_miner_energy_source(self.hass, self.entry)
        now = dt_util.utcnow()
        preserve_total_on_source_change(self._storage.record, new_resolved, now)
        self._resolved = new_resolved
        self._sync_physical_registry(new_resolved)
        self._storage.mark_dirty()

    async def async_tick(
        self,
        data: dict[str, Any] | None,
        *,
        available: bool,
    ) -> None:
        now = dt_util.utcnow()
        record = self._storage.record
        reset_periods_if_needed(record, now)
        quality_dt_s = begin_quality_interval(record, now, MINER_POLL_INTERVAL_S)
        period_dt_s = period_interval_seconds(quality_dt_s, MINER_POLL_INTERVAL_S)

        resolved = resolve_miner_energy_source(self.hass, self.entry)
        if (
            self._resolved is None
            or resolved.source != self._resolved.source
            or resolved.entity_id != self._resolved.entity_id
        ):
            preserve_total_on_source_change(record, resolved, now)
        self._resolved = resolved
        self._sync_physical_registry(resolved)

        t0 = dt_util.parse_datetime(record.last_ts) if record.last_ts else None
        total_before = record.total_kwh
        integrated = False

        if resolved.source != RESOLVED_UNAVAILABLE:
            if resolved.source == RESOLVED_PHYSICAL and resolved.entity_id:
                raw = read_energy_kwh(self.hass, resolved.entity_id)
                if raw is not None:
                    tick_physical_meter(
                        record,
                        now=now,
                        raw_kwh=raw,
                        resolved=resolved,
                        expected_interval_s=MINER_POLL_INTERVAL_S,
                    )
                    integrated = True
            else:
                power_w: float | None = None
                if resolved.source == RESOLVED_SWITCH_POWER and resolved.entity_id:
                    power_w = read_power_w(self.hass, resolved.entity_id)
                elif resolved.source == RESOLVED_MINER_POWER and available:
                    power_w = miner_power_w(data)

                if power_w is not None:
                    integrated = tick_power_integration(
                        record,
                        now=now,
                        power_w=power_w,
                        resolved=resolved,
                        expected_interval_s=MINER_POLL_INTERVAL_S,
                    )

        if integrated and quality_dt_s > 0:
            register_integrated_interval(record, quality_dt_s)

        delta_kwh = max(record.total_kwh - total_before, 0.0)

        delta_cost = 0.0
        currency = record.cost_currency
        if delta_kwh > 0 and t0 is not None:
            delta_cost, currency = compute_delta_cost(
                self.hass,
                self.entry.entry_id,
                delta_kwh=delta_kwh,
                t0=t0,
                t1=now,
            )
            if currency:
                record.cost_currency = currency

        ref_hashrate = miner_reference_hashrate_th_s(
            data, baseline_hashrate=self._baseline_hashrate(data)
        )
        update_nominal_power_from_telemetry(
            record, data, reference_hashrate_th_s=ref_hashrate
        )

        if period_dt_s > 0 or delta_kwh > 0 or delta_cost > 0:
            integrate_period_sample(
                record,
                now=now,
                delta_kwh=delta_kwh,
                delta_cost=delta_cost,
                hashrate_th_s=miner_hashrate_th_s(data),
                reference_hashrate_th_s=ref_hashrate,
                available=available and resolved.source != RESOLVED_UNAVAILABLE,
                dt_s=period_dt_s,
            )

        self._storage.mark_dirty()
        await self.async_save()
