"""Calendar period keys and accumulators for energy metrics."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .definitions import EnergyRecord

KWH_TO_J = 3_600_000.0
IDLE_HASHRATE_RATIO = 0.05
IDLE_POWER_W = 15.0
NOMINAL_HASHRATE_RATIO = 0.75


def day_key_local(when: datetime) -> str:
    local = dt_util.as_local(when)
    return f"{local.year:04d}-{local.month:02d}-{local.day:02d}"


def month_key_local(when: datetime) -> str:
    local = dt_util.as_local(when)
    return f"{local.year:04d}-{local.month:02d}"


def reset_periods_if_needed(record: EnergyRecord, now: datetime) -> None:
    """Reset day/month buckets on calendar boundaries (local time)."""
    dk = day_key_local(now)
    mk = month_key_local(now)
    if record.day_key != dk:
        record.day_key = dk
        record.day_kwh = 0.0
        record.day_hash_th = 0.0
        record.day_energy_j = 0.0
        record.day_lost_hash_th = 0.0
        record.day_idle_saved_kwh = 0.0
        record.day_cost = 0.0
        record.day_integrated_seconds = 0.0
        record.day_expected_seconds = 0.0
    if record.month_key != mk:
        if record.month_key:
            record.prev_month_key = record.month_key
            record.prev_month_kwh = record.month_kwh
            record.prev_month_cost = record.month_cost
        record.month_key = mk
        record.month_kwh = 0.0
        record.month_hash_th = 0.0
        record.month_energy_j = 0.0
        record.month_lost_hash_th = 0.0
        record.month_idle_saved_kwh = 0.0
        record.month_cost = 0.0


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def miner_hashrate_th_s(data: dict[str, Any] | None) -> float | None:
    if not data:
        return None
    return _parse_float((data.get("miner_sensors") or {}).get("hashrate"))


def miner_reference_hashrate_th_s(
    data: dict[str, Any] | None,
    *,
    baseline_hashrate: float | None = None,
) -> float | None:
    if baseline_hashrate and baseline_hashrate > 0:
        return baseline_hashrate
    if not data:
        return None
    ideal = _parse_float((data.get("miner_sensors") or {}).get("ideal_hashrate"))
    if ideal and ideal > 0:
        return ideal
    return None


def update_nominal_power_from_telemetry(
    record: EnergyRecord,
    data: dict[str, Any] | None,
    *,
    reference_hashrate_th_s: float | None = None,
) -> None:
    """Keep nominal power from miner telemetry when hashrate is near reference."""
    if not data:
        return
    power = _parse_float((data.get("miner_sensors") or {}).get("miner_consumption"))
    if not power or power <= IDLE_POWER_W:
        return
    ref = reference_hashrate_th_s or record.last_reference_hashrate_th_s
    if not ref or ref <= 0:
        return
    hashrate = miner_hashrate_th_s(data)
    if hashrate and hashrate >= ref * NOMINAL_HASHRATE_RATIO:
        record.last_nominal_power_w = power


def integrate_period_sample(
    record: EnergyRecord,
    *,
    now: datetime,
    delta_kwh: float,
    delta_cost: float,
    hashrate_th_s: float | None,
    reference_hashrate_th_s: float | None,
    available: bool,
    dt_s: float,
) -> None:
    """Add one integration step to day/month period accumulators."""
    if dt_s <= 0 and delta_kwh <= 0 and delta_cost <= 0:
        return
    reset_periods_if_needed(record, now)

    if delta_kwh > 0:
        record.day_kwh += delta_kwh
        record.month_kwh += delta_kwh
        joules = delta_kwh * KWH_TO_J
        record.day_energy_j += joules
        record.month_energy_j += joules

    if delta_cost > 0:
        record.day_cost += delta_cost
        record.month_cost += delta_cost
        record.total_cost += delta_cost

    curr_h = hashrate_th_s if available else 0.0

    if reference_hashrate_th_s and reference_hashrate_th_s > 0:
        record.last_reference_hashrate_th_s = reference_hashrate_th_s

    if dt_s <= 0:
        if curr_h is not None:
            record.last_hashrate_th_s = curr_h
        return

    prev_h = record.last_hashrate_th_s
    if prev_h is not None and curr_h is not None:
        avg_h = (prev_h + curr_h) / 2.0
        if avg_h > 0:
            d_hash = avg_h * dt_s
            record.day_hash_th += d_hash
            record.month_hash_th += d_hash

    ref = reference_hashrate_th_s or record.last_reference_hashrate_th_s
    if ref and ref > 0:
        active_h = curr_h if curr_h is not None else 0.0
        if not available or active_h < ref * IDLE_HASHRATE_RATIO:
            lost = ref * dt_s
            record.day_lost_hash_th += lost
            record.month_lost_hash_th += lost
            nominal_w = record.last_nominal_power_w
            if nominal_w and nominal_w > IDLE_POWER_W:
                actual_kwh = max(delta_kwh, 0.0)
                expected_kwh = nominal_w * dt_s / KWH_TO_J
                saved = expected_kwh - actual_kwh
                if saved > 0:
                    record.day_idle_saved_kwh += saved
                    record.month_idle_saved_kwh += saved

    if curr_h is not None:
        record.last_hashrate_th_s = curr_h
