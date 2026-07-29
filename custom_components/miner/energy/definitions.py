"""Energy accounting types, defaults, and persisted record."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

STORAGE_VERSION = 3
SAVE_INTERVAL_SECONDS = 60

# Max integration gap = multiplier × expected poll interval (miner 10 s, farm 15 s).
MAX_GAP_INTERVAL_MULTIPLIER = 2

ENERGY_SOURCE_AUTO = "auto"
ENERGY_SOURCE_PHYSICAL = "physical"
ENERGY_SOURCE_SWITCH_POWER = "switch_power"
ENERGY_SOURCE_MINER_POWER = "miner_power"

ENERGY_SOURCE_OPTIONS: tuple[str, ...] = (
    ENERGY_SOURCE_AUTO,
    ENERGY_SOURCE_PHYSICAL,
    ENERGY_SOURCE_SWITCH_POWER,
    ENERGY_SOURCE_MINER_POWER,
)

# Resolved runtime source (stored in record.active_source).
RESOLVED_PHYSICAL = "physical"
RESOLVED_SWITCH_POWER = "switch_power"
RESOLVED_MINER_POWER = "miner_power"
RESOLVED_UNAVAILABLE = "unavailable"

SOURCE_LABEL_KEYS: dict[str, str] = {
    RESOLVED_PHYSICAL: "energy_source_physical",
    RESOLVED_SWITCH_POWER: "energy_source_switch_power",
    RESOLVED_MINER_POWER: "energy_source_miner_power",
    RESOLVED_UNAVAILABLE: "energy_source_unavailable",
}


@dataclass
class EnergyRecord:
    """Persisted energy accumulator state for one miner or farm."""

    total_kwh: float = 0.0
    physical_offset_kwh: float = 0.0
    last_physical_raw_kwh: float | None = None
    last_power_w: float | None = None
    last_ts: str | None = None
    active_source: str | None = None
    active_entity_id: str | None = None
    expected_interval_s: float = 10.0
    integrated_seconds: float = 0.0
    expected_seconds: float = 0.0
    source_changed_at: str | None = None
    # Calendar period accumulators (local day/month).
    day_key: str | None = None
    month_key: str | None = None
    prev_month_key: str | None = None
    day_kwh: float = 0.0
    month_kwh: float = 0.0
    prev_month_kwh: float = 0.0
    day_hash_th: float = 0.0
    month_hash_th: float = 0.0
    day_energy_j: float = 0.0
    month_energy_j: float = 0.0
    day_lost_hash_th: float = 0.0
    month_lost_hash_th: float = 0.0
    day_idle_saved_kwh: float = 0.0
    month_idle_saved_kwh: float = 0.0
    day_cost: float = 0.0
    month_cost: float = 0.0
    total_cost: float = 0.0
    prev_month_cost: float = 0.0
    cost_currency: str | None = None
    last_hashrate_th_s: float | None = None
    last_reference_hashrate_th_s: float | None = None
    last_nominal_power_w: float | None = None
    day_integrated_seconds: float = 0.0
    day_expected_seconds: float = 0.0
    last_quality_ts: str | None = None
    member_last_totals: dict[str, float] = field(default_factory=dict)
    farm_aggregate_mode: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_kwh": self.total_kwh,
            "physical_offset_kwh": self.physical_offset_kwh,
            "last_physical_raw_kwh": self.last_physical_raw_kwh,
            "last_power_w": self.last_power_w,
            "last_ts": self.last_ts,
            "active_source": self.active_source,
            "active_entity_id": self.active_entity_id,
            "expected_interval_s": self.expected_interval_s,
            "integrated_seconds": self.integrated_seconds,
            "expected_seconds": self.expected_seconds,
            "source_changed_at": self.source_changed_at,
            "day_key": self.day_key,
            "month_key": self.month_key,
            "prev_month_key": self.prev_month_key,
            "day_kwh": self.day_kwh,
            "month_kwh": self.month_kwh,
            "prev_month_kwh": self.prev_month_kwh,
            "day_hash_th": self.day_hash_th,
            "month_hash_th": self.month_hash_th,
            "day_energy_j": self.day_energy_j,
            "month_energy_j": self.month_energy_j,
            "day_lost_hash_th": self.day_lost_hash_th,
            "month_lost_hash_th": self.month_lost_hash_th,
            "day_idle_saved_kwh": self.day_idle_saved_kwh,
            "month_idle_saved_kwh": self.month_idle_saved_kwh,
            "day_cost": self.day_cost,
            "month_cost": self.month_cost,
            "total_cost": self.total_cost,
            "prev_month_cost": self.prev_month_cost,
            "cost_currency": self.cost_currency,
            "last_hashrate_th_s": self.last_hashrate_th_s,
            "last_reference_hashrate_th_s": self.last_reference_hashrate_th_s,
            "last_nominal_power_w": self.last_nominal_power_w,
            "day_integrated_seconds": self.day_integrated_seconds,
            "day_expected_seconds": self.day_expected_seconds,
            "last_quality_ts": self.last_quality_ts,
            "member_last_totals": dict(self.member_last_totals),
            "farm_aggregate_mode": self.farm_aggregate_mode,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> EnergyRecord:
        if not raw:
            return cls()
        return cls(
            total_kwh=float(raw.get("total_kwh") or 0.0),
            physical_offset_kwh=float(raw.get("physical_offset_kwh") or 0.0),
            last_physical_raw_kwh=_optional_float(raw.get("last_physical_raw_kwh")),
            last_power_w=_optional_float(raw.get("last_power_w")),
            last_ts=raw.get("last_ts"),
            active_source=raw.get("active_source"),
            active_entity_id=raw.get("active_entity_id"),
            expected_interval_s=float(raw.get("expected_interval_s") or 10.0),
            integrated_seconds=float(raw.get("integrated_seconds") or 0.0),
            expected_seconds=float(raw.get("expected_seconds") or 0.0),
            source_changed_at=raw.get("source_changed_at"),
            day_key=raw.get("day_key"),
            month_key=raw.get("month_key"),
            prev_month_key=raw.get("prev_month_key"),
            day_kwh=float(raw.get("day_kwh") or 0.0),
            month_kwh=float(raw.get("month_kwh") or 0.0),
            prev_month_kwh=float(raw.get("prev_month_kwh") or 0.0),
            day_hash_th=float(raw.get("day_hash_th") or 0.0),
            month_hash_th=float(raw.get("month_hash_th") or 0.0),
            day_energy_j=float(raw.get("day_energy_j") or 0.0),
            month_energy_j=float(raw.get("month_energy_j") or 0.0),
            day_lost_hash_th=float(raw.get("day_lost_hash_th") or 0.0),
            month_lost_hash_th=float(raw.get("month_lost_hash_th") or 0.0),
            day_idle_saved_kwh=float(raw.get("day_idle_saved_kwh") or 0.0),
            month_idle_saved_kwh=float(raw.get("month_idle_saved_kwh") or 0.0),
            day_cost=float(raw.get("day_cost") or 0.0),
            month_cost=float(raw.get("month_cost") or 0.0),
            total_cost=float(raw.get("total_cost") or 0.0),
            prev_month_cost=float(raw.get("prev_month_cost") or 0.0),
            cost_currency=raw.get("cost_currency"),
            last_hashrate_th_s=_optional_float(raw.get("last_hashrate_th_s")),
            last_reference_hashrate_th_s=_optional_float(
                raw.get("last_reference_hashrate_th_s")
            ),
            last_nominal_power_w=_optional_float(raw.get("last_nominal_power_w")),
            day_integrated_seconds=float(raw.get("day_integrated_seconds") or 0.0),
            day_expected_seconds=float(raw.get("day_expected_seconds") or 0.0),
            last_quality_ts=raw.get("last_quality_ts"),
            member_last_totals={
                str(k): float(v)
                for k, v in (raw.get("member_last_totals") or {}).items()
            },
            farm_aggregate_mode=raw.get("farm_aggregate_mode"),
        )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class ResolvedEnergySource:
    """Active energy source for one tick."""

    source: str
    entity_id: str | None = None
    estimated: bool = False


@dataclass
class FarmEnergySnapshot:
    """Aggregated farm energy metadata for sensor attributes."""

    total_kwh: float
    source: str
    physical_meters: int = 0
    calculated_meters: int = 0
    unmetered_miners: int = 0
    coverage: float | None = None
    estimated: bool = False


@dataclass
class FarmPeriodSnapshot:
    """Farm period metrics (summed members or physical meter + member hash)."""

    day_kwh: float = 0.0
    month_kwh: float = 0.0
    prev_month_kwh: float = 0.0
    day_hash_th: float = 0.0
    month_hash_th: float = 0.0
    day_energy_j: float = 0.0
    month_energy_j: float = 0.0
    day_cost: float = 0.0
    month_cost: float = 0.0
    day_lost_hash_th: float = 0.0
    month_lost_hash_th: float = 0.0
    day_idle_saved_kwh: float = 0.0
    month_idle_saved_kwh: float = 0.0
    efficiency_day_jth: float | None = None
    efficiency_month_jth: float | None = None
    cost_per_th_hour_day: float | None = None
    cost_per_th_hour_month: float | None = None
    cost_per_ph_day: float | None = None
    currency: str | None = None
