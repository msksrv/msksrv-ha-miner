"""Farm electricity tariffs (optional, up to 3 currencies)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

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
    """Return [(currency, price_kwh), ...] from config entry options."""
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


def farm_energy_rates_from_user_input(user_input: dict[str, Any]) -> list[dict[str, Any]]:
    """Build stored list from options flow fields."""
    stored: list[dict[str, Any]] = []
    for i in range(1, 4):
        raw_cur = str(user_input.get(f"farm_elec_currency_{i}") or _FARM_CUR_OFF).strip()
        if raw_cur.lower() == _FARM_CUR_OFF or not raw_cur:
            continue
        c = raw_cur.upper()
        pr = user_input.get(f"farm_elec_price_kwh_{i}")
        try:
            pf = float(pr) if pr is not None else 0.0
        except (TypeError, ValueError):
            pf = 0.0
        if c and pf > 0:
            stored.append({"currency": c, "price_kwh": round(pf, 6)})
    return stored


def farm_electricity_schema_fields(
    options: dict[str, Any], user_input: dict[str, Any] | None = None
) -> dict[Any, Any]:
    """Vol schema fragment for three optional currency + price/kWh slots."""
    ui = user_input or {}
    stored_raw = options.get(CONF_FARM_ENERGY_RATES) or []
    stored: list[dict[str, Any]] = (
        [x for x in stored_raw if isinstance(x, dict)] if isinstance(stored_raw, list) else []
    )
    fields: dict[Any, Any] = {}
    for i in range(1, 4):
        cur_key = f"farm_elec_currency_{i}"
        price_key = f"farm_elec_price_kwh_{i}"
        if i - 1 < len(stored):
            def_cur = str(stored[i - 1].get("currency") or "")
            try:
                def_price = float(stored[i - 1].get("price_kwh", 0))
            except (TypeError, ValueError):
                def_price = 0.0
        else:
            def_cur = ""
            def_price = 0.0
        sug_cur = ui.get(cur_key, def_cur)
        if isinstance(sug_cur, str) and sug_cur.strip():
            select_suggested = sug_cur.strip().upper()
        else:
            select_suggested = _FARM_CUR_OFF
        sug_price = ui.get(price_key, def_price)
        try:
            price_suggested = float(sug_price) if sug_price is not None else 0.0
        except (TypeError, ValueError):
            price_suggested = 0.0
        fields[
            vol.Optional(
                cur_key,
                description={"suggested_value": select_suggested},
            )
        ] = SelectSelector(SelectSelectorConfig(options=FARM_ELECTRICITY_CURRENCY_OPTIONS))
        fields[
            vol.Optional(
                price_key,
                description={"suggested_value": price_suggested},
            )
        ] = NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=9999,
                step=0.0001,
                mode="box",
            )
        )
    return fields
