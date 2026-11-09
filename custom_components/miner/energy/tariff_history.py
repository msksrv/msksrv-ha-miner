"""Read the farm's persisted meter samples for a tariff correction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING

from homeassistant.components.recorder import get_instance, history
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.helpers import entity_registry as er

from ..const import DOMAIN
from .tariff import TariffHistoryError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def async_farm_meter_history(
    hass: HomeAssistant,
    entry_id: str,
    effective: datetime,
    end: datetime,
    total_kwh: float,
) -> list[tuple[datetime, float]]:
    """Read real timestamps around the boundary and use the live meter as the end."""
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"farm-{entry_id}-energy-total"
    )
    if entity_id is None or "recorder" not in hass.config.components:
        raise TariffHistoryError
    recorder = get_instance(hass)
    rows = await recorder.async_add_executor_job(
        partial(
            history.get_significant_states,
            hass,
            effective - timedelta(days=1),
            end,
            [entity_id],
            include_start_time_state=False,
            no_attributes=True,
        )
    )

    boundary = None
    readings = []
    for row in rows.get(entity_id, ()):
        when = row.last_updated
        if when >= end:
            break
        try:
            value = float(row.state)
        except (TypeError, ValueError):
            continue
        if when <= effective:
            boundary = (when, value)
        else:
            readings.append((when, value))
    if boundary is not None:
        return [boundary, *readings, (end, round(total_kwh, 3))]

    # Fill the older portion with hourly endpoints, keeping detailed samples
    # from the first hour for which both sources are available.
    hour = timedelta(hours=1)
    first_hour = effective.replace(minute=0, second=0, microsecond=0) - hour
    last_complete = end.replace(minute=0, second=0, microsecond=0) - hour
    if readings:
        handoff = min(
            last_complete, readings[0][0].replace(minute=0, second=0, microsecond=0)
        )
    else:
        handoff = last_complete
    if handoff <= first_hour:
        raise TariffHistoryError
    hourly = await recorder.async_add_executor_job(
        statistics_during_period,
        hass,
        first_hour,
        handoff,
        {entity_id},
        "hour",
        {"energy": "kWh"},
        {"state"},
    )
    expected_hour = first_hour
    prefix = []
    for row in hourly.get(entity_id, ()):
        stamp = datetime.fromtimestamp(row["start"], UTC)
        value = row.get("state")
        if stamp != expected_hour or value is None:
            raise TariffHistoryError
        expected_hour += hour
        # A complete hourly bucket belongs to the day containing the hour,
        # even if its upper boundary is exactly midnight.
        prefix.append((expected_hour - timedelta(microseconds=1), value))
    if expected_hour != handoff:
        raise TariffHistoryError
    return [
        *prefix,
        *(sample for sample in readings if sample[0] >= handoff),
        (end, round(total_kwh, 3)),
    ]
