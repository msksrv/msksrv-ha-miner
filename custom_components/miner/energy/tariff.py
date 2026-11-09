"""Date-effective tariff pricing and historical cost adjustments."""

from __future__ import annotations

import math
from datetime import date, datetime, time
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from ..const import (
    CONF_FARM_ELEC_TARIFF_MODE,
    CONF_FARM_ELEC_TOU_CURRENCY,
    CONF_FARM_ELEC_ZONES,
    CONF_FARM_ENERGY_RATES,
    FARM_ELEC_TARIFF_DUAL,
    FARM_ELEC_TARIFF_FLAT,
)
from ..farm_elec_tou import (
    farm_tariff_mode,
    farm_tou_currency,
    farm_tou_zones_stored,
    integrate_tou_energy_cost,
    price_at_local_dt,
)
from ..farm_energy_rates import farm_primary_energy_rate
from .periods import day_key_local, month_key_local

if TYPE_CHECKING:
    from collections.abc import Iterator

    from homeassistant.core import HomeAssistant

TARIFF_SCHEDULE = "farm_tariff_schedule"
COST_ADJUSTMENTS = "farm_tariff_cost_adjustments"
EFFECTIVE_DATE = "farm_tariff_effective_date"
_TARIFF_KEYS = (
    CONF_FARM_ELEC_TARIFF_MODE,
    CONF_FARM_ENERGY_RATES,
    CONF_FARM_ELEC_TOU_CURRENCY,
    CONF_FARM_ELEC_ZONES,
)


class TariffHistoryError(ValueError):
    """Recorder cannot reconstruct the requested period."""


def local_midnight(value: str) -> datetime:
    return dt_util.as_utc(
        datetime.combine(date.fromisoformat(value), time.min, dt_util.DEFAULT_TIME_ZONE)
    )


def _revisions(options: dict[str, Any]) -> Iterator[tuple[datetime, dict[str, Any]]]:
    changes = options.get(TARIFF_SCHEDULE, {}).get("changes", {})
    for stamp, tariff in sorted(changes.items()):
        effective = dt_util.parse_datetime(stamp)
        if effective is not None:
            yield effective, tariff


def tariff_at(options: dict[str, Any], when: datetime) -> dict[str, Any]:
    """Resolve the tariff active at an instant, including older saved schedules."""
    schedule = options.get(TARIFF_SCHEDULE)
    if not schedule:
        return options
    current = schedule["base"]
    for effective, tariff in _revisions(options):
        if effective > when:
            break
        current = tariff
    return current


def _snapshot(options: dict[str, Any]) -> dict[str, Any]:
    return {key: options[key] for key in _TARIFF_KEYS if key in options}


def tariff_currency(options: dict[str, Any]) -> str | None:
    if farm_tariff_mode(options) == FARM_ELEC_TARIFF_FLAT:
        rate = farm_primary_energy_rate(options)
        return rate[0] if rate else None
    required = 2 if farm_tariff_mode(options) == FARM_ELEC_TARIFF_DUAL else 3
    return (
        farm_tou_currency(options)
        if len(farm_tou_zones_stored(options)) == required
        else None
    )


def tariff_currencies(options: dict[str, Any]) -> set[str]:
    schedule = options.get(TARIFF_SCHEDULE)
    tariffs = (
        [schedule["base"], *schedule["changes"].values()] if schedule else [options]
    )
    return {currency for tariff in tariffs if (currency := tariff_currency(tariff))}


def same_tariff(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return _snapshot(left) == _snapshot(right)


def with_revision(
    previous: dict[str, Any], submitted: dict[str, Any], effective: datetime
) -> dict[str, Any]:
    """Add or replace a revision; keep any other explicitly dated revisions."""
    schedule = previous.get(TARIFF_SCHEDULE, {})
    changes = dict(schedule.get("changes", {}))
    changes[effective.isoformat()] = _snapshot(submitted)
    return {
        **previous,
        **_snapshot(submitted),
        TARIFF_SCHEDULE: {
            "base": schedule.get("base", _snapshot(previous)),
            "changes": changes,
        },
    }


def current_price(options: dict[str, Any], when: datetime) -> float | None:
    tariff = tariff_at(options, when)
    if farm_tariff_mode(tariff) == FARM_ELEC_TARIFF_FLAT:
        rate = farm_primary_energy_rate(tariff)
        return rate[1] if rate else None
    zones = farm_tou_zones_stored(tariff)
    return price_at_local_dt(dt_util.as_local(when), zones) if zones else None


def cost_for_interval(
    hass: HomeAssistant,
    options: dict[str, Any],
    delta_kwh: float,
    start: datetime,
    end: datetime,
) -> float:
    """Price the energy delta, prorating at tariff and zone boundaries."""
    if delta_kwh <= 0 or end <= start:
        return 0.0
    current = tariff_at(options, start)
    boundaries = [
        (when, tariff) for when, tariff in _revisions(options) if start < when < end
    ]
    kw = delta_kwh * 3600 / (end - start).total_seconds()
    total = 0.0
    for stop, next_tariff in [*boundaries, (end, None)]:
        if farm_tariff_mode(current) == FARM_ELEC_TARIFF_FLAT:
            rate = farm_primary_energy_rate(current)
            if rate:
                total += kw * (stop - start).total_seconds() / 3600 * rate[1]
        else:
            zones = farm_tou_zones_stored(current)
            if zones and farm_tou_currency(current):
                total += integrate_tou_energy_cost(hass, kw, start, stop, zones)
        if next_tariff is not None:
            current = next_tariff
        start = stop
    return total


def with_history_adjustment(
    hass: HomeAssistant,
    previous: dict[str, Any],
    updated: dict[str, Any],
    effective: datetime,
    readings: list[tuple[datetime, float]],
) -> dict[str, Any]:
    """Reprice saved meter deltas and persist the difference with the schedule."""
    if len(readings) < 2 or readings[0][0] > effective or readings[-1][0] < effective:
        raise TariffHistoryError
    adjustments = previous.get(COST_ADJUSTMENTS, {})
    days = dict(adjustments.get("days", {}))
    months = dict(adjustments.get("months", {}))
    total = adjustments.get("total", 0.0)
    for (start, old), (end, new) in pairwise(readings):
        if end <= effective:
            continue
        if not (
            math.isfinite(old)
            and math.isfinite(new)
            and 0 <= old <= new
            and start < end
        ):
            raise TariffHistoryError
        kwh = new - old
        if not kwh:
            continue
        change = cost_for_interval(hass, updated, kwh, start, end) - cost_for_interval(
            hass, previous, kwh, start, end
        )
        if abs(change) < 1e-12:
            continue
        # The existing accumulator books a sample to the day/month of its end.
        day = day_key_local(end)
        month = month_key_local(end)
        days[day] = days.get(day, 0.0) + change
        months[month] = months.get(month, 0.0) + change
        total += change
    return {
        **updated,
        COST_ADJUSTMENTS: {"total": total, "days": days, "months": months},
    }


def corrected_cost(
    options: dict[str, Any], cost: float, period: str, key: str | None = None
) -> float:
    adjustments = options.get(COST_ADJUSTMENTS, {})
    difference = (
        adjustments.get("total", 0.0)
        if period == "total"
        else adjustments.get(period, {}).get(key, 0.0)
    )
    return max(cost + difference, 0.0)
