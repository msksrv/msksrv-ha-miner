"""Time-of-use (multi-zone) electricity tariffs for farm cost sensors."""

from __future__ import annotations

import logging
from datetime import date
from datetime import datetime
from datetime import time as dt_time
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig
from homeassistant.helpers.selector import TimeSelector
from homeassistant.util import dt as dt_util

from .const import CONF_FARM_ELEC_TARIFF_MODE
from .const import CONF_FARM_ELEC_TOU_CURRENCY
from .const import CONF_FARM_ELEC_ZONES
from .const import FARM_ELEC_TARIFF_DUAL
from .const import FARM_ELEC_TARIFF_FLAT
from .const import FARM_ELEC_TARIFF_TRIPLE
from .farm_energy_rates import FARM_ELECTRICITY_CURRENCY_OPTIONS
from .farm_energy_rates import _FARM_CUR_OFF

_LOGGER = logging.getLogger(__name__)

FARM_TARIFF_MODE_OPTIONS: list[dict[str, str]] = [
    {"value": FARM_ELEC_TARIFF_FLAT, "label": "Flat (up to 3 currencies)"},
    {"value": FARM_ELEC_TARIFF_DUAL, "label": "Two zones (by local time)"},
    {"value": FARM_ELEC_TARIFF_TRIPLE, "label": "Three zones (by local time)"},
]

TOU_CURRENCY_OPTIONS: list[dict[str, str]] = [
    o for o in FARM_ELECTRICITY_CURRENCY_OPTIONS if o["value"] != _FARM_CUR_OFF
]


def farm_tariff_mode(options: dict[str, Any]) -> str:
    m = options.get(CONF_FARM_ELEC_TARIFF_MODE) or FARM_ELEC_TARIFF_FLAT
    if m not in (FARM_ELEC_TARIFF_FLAT, FARM_ELEC_TARIFF_DUAL, FARM_ELEC_TARIFF_TRIPLE):
        return FARM_ELEC_TARIFF_FLAT
    return m


def farm_tou_zones_stored(options: dict[str, Any]) -> list[dict[str, Any]]:
    raw = options.get(CONF_FARM_ELEC_ZONES)
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for z in raw:
        if not isinstance(z, dict):
            continue
        start = str(z.get("start") or "00:00").strip()
        end = str(z.get("end") or "00:00").strip()
        try:
            price = float(z.get("price_kwh", 0))
        except (TypeError, ValueError):
            price = 0.0
        if price > 0 and start and end:
            out.append({"start": start, "end": end, "price_kwh": price})
    return out


def time_selector_to_hhmm(val: Any) -> str:
    """Normalize HA TimeSelector output to HH:MM."""
    if val is None:
        return "00:00"
    if isinstance(val, dict):
        try:
            h = int(val.get("hours", 0))
            m = int(val.get("minutes", 0))
            if h == 24 and m == 0:
                return "24:00"
            return f"{h % 24:02d}:{m % 60:02d}"
        except (TypeError, ValueError):
            return "00:00"
    s = str(val).strip()
    if not s:
        return "00:00"
    if "T" in s:
        s = s.split("T", 1)[-1]
    parts = s.replace(".", ":").split(":")
    try:
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        if h == 24 and m == 0:
            return "24:00"
        return f"{h % 24:02d}:{m % 60:02d}"
    except (TypeError, ValueError):
        return "00:00"


def _hhmm_to_minutes(hhmm: str) -> int:
    hhmm = str(hhmm).strip()
    parts = hhmm.split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    if h == 24 and m == 0:
        return 1440
    if h > 24 or (h == 24 and m > 0):
        return 1440
    return min(1440, max(0, h * 60 + m))


def price_at_local_minute(minute_of_day: int, zones: list[dict[str, Any]]) -> float:
    """minute_of_day in [0, 1440). First matching zone wins."""
    m = minute_of_day % 1440
    for z in zones:
        sm = _hhmm_to_minutes(z["start"])
        em = _hhmm_to_minutes(z["end"])
        try:
            price = float(z["price_kwh"])
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        if sm <= em:
            if sm <= m < em or (em == 1440 and m >= sm):
                return price
        else:
            if m >= sm or m < em:
                return price
    return 0.0


def price_at_local_dt(local_dt: datetime, zones: list[dict[str, Any]]) -> float:
    return price_at_local_minute(local_dt.hour * 60 + local_dt.minute, zones)


def _local_dt_for_zone_boundary_on_date(cur: date, hhmm: str, tz) -> datetime:
    minutes = _hhmm_to_minutes(str(hhmm).strip())
    if minutes >= 1440:
        return datetime.combine(cur + timedelta(days=1), dt_time(0, 0), tzinfo=tz)
    return datetime.combine(
        cur, dt_time(minutes // 60, minutes % 60), tzinfo=tz
    )


def integrate_tou_energy_cost(
    hass,
    kw: float,
    t0_utc: datetime,
    t1_utc: datetime,
    zones: list[dict[str, Any]],
) -> float:
    """Σ (kW × Δh × price) with price from local TOU zones; split at zone/midnight boundaries."""
    if t1_utc <= t0_utc or kw <= 0 or not zones:
        return 0.0
    tz = dt_util.get_time_zone(hass.config.time_zone)
    splits: list[datetime] = []
    d0 = dt_util.as_local(t0_utc).date()
    d1 = dt_util.as_local(t1_utc).date()
    cur = d0
    while cur <= d1:
        for z in zones:
            for key in ("start", "end"):
                lt = _local_dt_for_zone_boundary_on_date(
                    cur, str(z.get(key, "00:00")), tz
                )
                utc = lt.astimezone(dt_util.UTC)
                if t0_utc < utc < t1_utc:
                    splits.append(utc)
        cur += timedelta(days=1)

    splits = sorted(set(splits))
    points = [t0_utc] + splits + [t1_utc]
    total = 0.0
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        if b <= a:
            continue
        mid = a + (b - a) / 2
        loc = dt_util.as_local(mid)
        p = price_at_local_dt(loc, zones)
        dt_h = (b - a).total_seconds() / 3600.0
        total += kw * dt_h * p
    return total


def farm_tou_currency(options: dict[str, Any]) -> str | None:
    c = str(options.get(CONF_FARM_ELEC_TOU_CURRENCY) or "").strip().upper()
    return c if c and c != _FARM_CUR_OFF.upper() else None


def tou_zones_from_user_input(
    user_input: dict[str, Any], mode: str
) -> list[dict[str, Any]]:
    zones: list[dict[str, Any]] = []
    n = 2 if mode == FARM_ELEC_TARIFF_DUAL else 3 if mode == FARM_ELEC_TARIFF_TRIPLE else 0
    for i in range(1, n + 1):
        start = time_selector_to_hhmm(user_input.get(f"farm_elec_z{i}_start"))
        end = time_selector_to_hhmm(user_input.get(f"farm_elec_z{i}_end"))
        pr = user_input.get(f"farm_elec_z{i}_price")
        try:
            pf = float(pr) if pr is not None else 0.0
        except (TypeError, ValueError):
            pf = 0.0
        if pf > 0:
            zones.append({"start": start, "end": end, "price_kwh": round(pf, 6)})
    return zones


def farm_tariff_schema_fields(
    options: dict[str, Any], user_input: dict[str, Any] | None = None
) -> dict[Any, Any]:
    """Tariff mode + TOU time/price fields (flat slots stay in farm_energy_rates)."""
    ui = user_input or {}
    stored_mode = farm_tariff_mode(options)
    sug_mode = ui.get(CONF_FARM_ELEC_TARIFF_MODE, stored_mode)
    if sug_mode not in (FARM_ELEC_TARIFF_FLAT, FARM_ELEC_TARIFF_DUAL, FARM_ELEC_TARIFF_TRIPLE):
        sug_mode = FARM_ELEC_TARIFF_FLAT

    fields: dict[Any, Any] = {
        vol.Optional(
            CONF_FARM_ELEC_TARIFF_MODE,
            description={"suggested_value": sug_mode},
        ): SelectSelector(SelectSelectorConfig(options=FARM_TARIFF_MODE_OPTIONS))
    }

    stored_z = farm_tou_zones_stored(options)
    stored_cur = farm_tou_currency(options) or "EUR"

    fields[
        vol.Optional(
            CONF_FARM_ELEC_TOU_CURRENCY,
            description={"suggested_value": ui.get(CONF_FARM_ELEC_TOU_CURRENCY, stored_cur)},
        )
    ] = SelectSelector(SelectSelectorConfig(options=TOU_CURRENCY_OPTIONS))

    _def_start = {1: "00:00", 2: "12:00", 3: "16:00"}
    _def_end = {1: "12:00", 2: "16:00", 3: "24:00"}
    for i in range(1, 4):
        zi = stored_z[i - 1] if i - 1 < len(stored_z) else {}
        z_start = zi.get("start", _def_start[i])
        z_end = zi.get("end", _def_end[i])
        try:
            z_price = float(zi.get("price_kwh", 0))
        except (TypeError, ValueError):
            z_price = 0.0
        sk = f"farm_elec_z{i}_start"
        ek = f"farm_elec_z{i}_end"
        pk = f"farm_elec_z{i}_price"
        fields[
            vol.Optional(
                sk,
                description={"suggested_value": ui.get(sk, z_start)},
            )
        ] = TimeSelector()
        fields[
            vol.Optional(
                ek,
                description={"suggested_value": ui.get(ek, z_end)},
            )
        ] = TimeSelector()
        fields[
            vol.Optional(
                pk,
                description={"suggested_value": ui.get(pk, z_price)},
            )
        ] = NumberSelector(
            NumberSelectorConfig(min=0, max=9999, step="any", mode="box")
        )

    return fields


def validate_tou_submission(mode: str, zones: list[dict[str, Any]]) -> str | None:
    if mode == FARM_ELEC_TARIFF_DUAL:
        if len(zones) != 2:
            return "farm_tou_zones_dual"
    elif mode == FARM_ELEC_TARIFF_TRIPLE:
        if len(zones) != 3:
            return "farm_tou_zones_triple"
    return None
