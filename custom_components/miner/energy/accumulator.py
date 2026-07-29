"""Trapezoidal power integration and physical-meter reset stitching."""

from __future__ import annotations

from datetime import datetime

from homeassistant.util import dt as dt_util

from .definitions import (
    MAX_GAP_INTERVAL_MULTIPLIER,
    RESOLVED_MINER_POWER,
    RESOLVED_PHYSICAL,
    RESOLVED_SWITCH_POWER,
    EnergyRecord,
    ResolvedEnergySource,
)

PHYSICAL_RESET_DROP_RATIO = 0.10


def max_gap_seconds(expected_interval_s: float) -> float:
    return max(expected_interval_s * MAX_GAP_INTERVAL_MULTIPLIER, 30.0)


def integrate_power_kwh(prev_w: float, curr_w: float, dt_s: float) -> float:
    """Trapezoidal integration: (P_prev + P_curr) / 2 × Δt."""
    if dt_s <= 0:
        return 0.0
    avg_w = (prev_w + curr_w) / 2.0
    return avg_w * dt_s / 3_600_000.0


def stitch_physical_reading(record: EnergyRecord, raw_kwh: float) -> float:
    """Return monotonic total kWh, anchoring on first read and stitching real resets."""
    if record.last_physical_raw_kwh is None:
        record.physical_offset_kwh = record.total_kwh - raw_kwh
        record.last_physical_raw_kwh = raw_kwh
        return record.total_kwh

    if raw_kwh < record.last_physical_raw_kwh:
        prev = record.last_physical_raw_kwh
        drop = prev - raw_kwh
        if prev > 0 and drop / prev > PHYSICAL_RESET_DROP_RATIO:
            record.physical_offset_kwh += prev

    record.last_physical_raw_kwh = raw_kwh
    total = record.physical_offset_kwh + raw_kwh
    if total > record.total_kwh:
        record.total_kwh = total
    return record.total_kwh


def data_quality_pct(record: EnergyRecord) -> float | None:
    if record.day_expected_seconds <= 0:
        return None
    return round(
        min(100.0, 100.0 * record.day_integrated_seconds / record.day_expected_seconds),
        1,
    )


def begin_quality_interval(
    record: EnergyRecord,
    now: datetime,
    expected_interval_s: float,
) -> float:
    """Register expected poll interval; return elapsed seconds since last quality tick."""
    had_prior = record.last_quality_ts is not None
    dt_s = 0.0
    if had_prior:
        last = dt_util.parse_datetime(record.last_quality_ts)
        if last is not None:
            elapsed = (now - last).total_seconds()
            if elapsed > 0:
                dt_s = elapsed
    else:
        dt_s = expected_interval_s

    record.last_quality_ts = dt_util.as_utc(now).isoformat()
    if dt_s > 0:
        record.expected_seconds += dt_s
        record.day_expected_seconds += dt_s
    return dt_s


def period_interval_seconds(quality_dt_s: float, expected_interval_s: float) -> float:
    """Cap hash/lost-hash integration; quality tracking may use the full elapsed gap."""
    if quality_dt_s <= 0:
        return 0.0
    if quality_dt_s <= max_gap_seconds(expected_interval_s):
        return quality_dt_s
    return 0.0


def register_integrated_interval(record: EnergyRecord, dt_s: float) -> None:
    if dt_s <= 0:
        return
    record.integrated_seconds += dt_s
    record.day_integrated_seconds += dt_s


def tick_power_integration(
    record: EnergyRecord,
    *,
    now: datetime,
    power_w: float | None,
    resolved: ResolvedEnergySource,
    expected_interval_s: float,
) -> bool:
    """Integrate polled power into total_kwh. Returns True when energy was integrated."""
    _maybe_switch_source(record, resolved, now)

    if record.last_ts is None:
        record.last_ts = dt_util.as_utc(now).isoformat()
        record.last_power_w = power_w
        record.expected_interval_s = expected_interval_s
        return False

    last = dt_util.parse_datetime(record.last_ts)
    if last is None:
        record.last_ts = dt_util.as_utc(now).isoformat()
        record.last_power_w = power_w
        return False

    dt_s = (now - last).total_seconds()
    record.last_ts = dt_util.as_utc(now).isoformat()
    record.expected_interval_s = expected_interval_s

    gap_limit = max_gap_seconds(expected_interval_s)
    if dt_s <= 0 or dt_s > gap_limit:
        record.last_power_w = power_w
        return False

    if power_w is None or record.last_power_w is None:
        record.last_power_w = power_w
        return False

    delta = integrate_power_kwh(record.last_power_w, power_w, dt_s)
    record.total_kwh += delta
    record.last_power_w = power_w
    return True


def tick_physical_meter(
    record: EnergyRecord,
    *,
    now: datetime,
    raw_kwh: float,
    resolved: ResolvedEnergySource,
    expected_interval_s: float,
) -> None:
    """Update monotonic total from a physical energy sensor reading."""
    _maybe_switch_source(record, resolved, now)
    record.expected_interval_s = expected_interval_s
    record.last_ts = dt_util.as_utc(now).isoformat()
    stitch_physical_reading(record, raw_kwh)


def _maybe_switch_source(
    record: EnergyRecord,
    resolved: ResolvedEnergySource,
    now: datetime,
) -> None:
    key = resolved.source
    entity = resolved.entity_id
    if record.active_source == key and record.active_entity_id == entity:
        return
    record.active_source = key
    record.active_entity_id = entity
    record.source_changed_at = dt_util.as_utc(now).isoformat()
    if key == RESOLVED_PHYSICAL:
        record.last_physical_raw_kwh = None
    else:
        record.last_physical_raw_kwh = None
    if key in (RESOLVED_MINER_POWER, RESOLVED_SWITCH_POWER):
        record.last_power_w = None


def preserve_total_on_source_change(
    old: EnergyRecord,
    new_source: ResolvedEnergySource,
    now: datetime,
) -> None:
    """Keep accumulated total when the configured source changes."""
    if old.active_source == new_source.source and old.active_entity_id == new_source.entity_id:
        return
    old.active_source = new_source.source
    old.active_entity_id = new_source.entity_id
    old.source_changed_at = dt_util.as_utc(now).isoformat()
    old.last_ts = None
    old.last_power_w = None
    old.last_physical_raw_kwh = None
