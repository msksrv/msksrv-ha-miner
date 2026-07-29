"""Farm electricity flat tariff (single currency + price per kWh)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import CONF_FARM_ENERGY_RATES

# SelectSelector must not use "" as option value — frontend returns 400 Bad Request.
_FARM_CUR_OFF = "none"

FARM_ELECTRICITY_CURRENCY_OPTIONS: list[dict[str, str]] = [
    {"value": _FARM_CUR_OFF, "label": "—"},
    {"value": "EUR", "label": "EUR"},
    {"value": "USD", "label": "USD"},
    {"value": "RUB", "label": "RUB"},
    {"value": "GBP", "label": "GBP"},
    {"value": "UAH", "label": "UAH"},
    {"value": "PLN", "label": "PLN"},
    {"value": "KZT", "label": "KZT"},
    {"value": "BYN", "label": "BYN"},
    {"value": "CHF", "label": "CHF"},
    {"value": "CZK", "label": "CZK"},
    {"value": "SEK", "label": "SEK"},
    {"value": "NOK", "label": "NOK"},
    {"value": "TRY", "label": "TRY"},
    {"value": "CNY", "label": "CNY"},
    {"value": "JPY", "label": "JPY"},
    {"value": "AUD", "label": "AUD"},
    {"value": "CAD", "label": "CAD"},
    {"value": "BRL", "label": "BRL"},
    {"value": "INR", "label": "INR"},
    {"value": "MXN", "label": "MXN"},
]


def farm_energy_rates_list(options: dict[str, Any]) -> list[tuple[str, float]]:
    """Return [(currency, price_kwh), ...] — energy accounting uses the first entry only."""
    raw = options.get(CONF_FARM_ENERGY_RATES)
    if not raw or not isinstance(raw, list):
        return []
    out: list[tuple[str, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        c = str(item.get("currency") or "").strip().upper()
        try:
            p = float(item.get("price_kwh", 0))
        except (TypeError, ValueError):
            continue
        if c and p > 0:
            out.append((c, p))
    return out


def farm_primary_energy_rate(options: dict[str, Any]) -> tuple[str, float] | None:
    """Primary (only) flat tariff used by energy cost integration."""
    rates = farm_energy_rates_list(options)
    if not rates:
        return None
    return rates[0]


def farm_energy_rates_from_user_input(user_input: dict[str, Any]) -> list[dict[str, Any]]:
    """Build stored list from options flow fields (single currency slot)."""
    raw_cur = str(user_input.get("farm_elec_currency_1") or _FARM_CUR_OFF).strip()
    if raw_cur.lower() in (_FARM_CUR_OFF, "none") or not raw_cur:
        return []
    c = raw_cur.upper()
    pr = user_input.get("farm_elec_price_kwh_1")
    try:
        pf = float(pr) if pr is not None else 0.0
    except (TypeError, ValueError):
        pf = 0.0
    if c and pf > 0:
        return [{"currency": c, "price_kwh": round(pf, 6)}]
    return []


def farm_electricity_schema_fields(
    options: dict[str, Any], user_input: dict[str, Any] | None = None
) -> dict[Any, Any]:
    """Vol schema for optional currency + price/kWh (flat tariff, one slot)."""
    ui = user_input or {}
    stored_raw = options.get(CONF_FARM_ENERGY_RATES) or []
    stored: list[dict[str, Any]] = (
        [x for x in stored_raw if isinstance(x, dict)] if isinstance(stored_raw, list) else []
    )
    if stored:
        def_cur = str(stored[0].get("currency") or "")
        try:
            def_price = float(stored[0].get("price_kwh", 0))
        except (TypeError, ValueError):
            def_price = 0.0
    else:
        def_cur = ""
        def_price = 0.0

    sug_cur = ui.get("farm_elec_currency_1", def_cur)
    if isinstance(sug_cur, str) and sug_cur.strip():
        select_suggested = sug_cur.strip().upper()
    else:
        select_suggested = _FARM_CUR_OFF
    sug_price = ui.get("farm_elec_price_kwh_1", def_price)
    try:
        price_suggested = float(sug_price) if sug_price is not None else 0.0
    except (TypeError, ValueError):
        price_suggested = 0.0

    return {
        vol.Optional(
            "farm_elec_currency_1",
            description={"suggested_value": select_suggested},
        ): SelectSelector(SelectSelectorConfig(options=FARM_ELECTRICITY_CURRENCY_OPTIONS)),
        vol.Optional(
            "farm_elec_price_kwh_1",
            description={"suggested_value": price_suggested},
        ): NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=9999,
                step="any",
                mode="box",
            )
        ),
    }
