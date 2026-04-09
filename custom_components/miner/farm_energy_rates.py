"""Farm electricity tariffs (optional, up to 3 currencies)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from .const import CONF_FARM_ENERGY_RATES

# ISO 4217 codes; first "" = slot off
FARM_ELECTRICITY_CURRENCIES: tuple[str, ...] = (
    "",
    "EUR",
    "USD",
    "RUB",
    "GBP",
    "UAH",
    "PLN",
    "KZT",
    "BYN",
    "CHF",
    "CZK",
    "SEK",
    "NOK",
    "TRY",
    "CNY",
    "JPY",
    "AUD",
    "CAD",
    "BRL",
    "INR",
    "MXN",
)


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
        c = str(user_input.get(f"farm_elec_currency_{i}") or "").strip().upper()
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
    fields: dict[vol.Marker, Any] = {}
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
        sug_price = ui.get(price_key, def_price)
        fields[
            vol.Optional(
                cur_key,
                description={"suggested_value": sug_cur if sug_cur else ""},
            )
        ] = SelectSelector(SelectSelectorConfig(options=list(FARM_ELECTRICITY_CURRENCIES)))
        fields[
            vol.Optional(
                price_key,
                description={"suggested_value": sug_price},
            )
        ] = NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=9999,
                step=0.000001,
                mode="box",
            )
        )
    return fields
