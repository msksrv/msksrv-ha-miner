"""Threshold fields shown inside repair flows (problem-specific subset)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.helpers import selector

from ...const import (
    CONF_HEALTH_PROFILE,
    CONF_HEALTH_THRESHOLDS,
    HEALTH_PROFILE_CUSTOM,
)
from ..profiles import health_threshold_defaults_for_ui
from ..thresholds import HealthThresholds

# (field name, min, max)
THRESHOLD_FIELDS_BY_REPAIR: dict[str, tuple[tuple[str, float, float], ...]] = {
    "temperature": (
        ("temp_chip_warn_c", 60.0, 110.0),
        ("temp_chip_high_c", 60.0, 120.0),
        ("temp_board_warn_c", 50.0, 100.0),
        ("temp_board_high_c", 50.0, 110.0),
    ),
    "reject": (("reject_rate_high_pct", 0.1, 10.0),),
    "power": (
        ("power_low_ratio", 0.5, 0.99),
        ("power_high_ratio", 1.01, 1.5),
    ),
    "hashrate": (("hashrate_low_ratio", 0.5, 0.99),),
}


def threshold_fields_for_repair(repair_type: str) -> tuple[tuple[str, float, float], ...]:
    return THRESHOLD_FIELDS_BY_REPAIR.get(repair_type, ())


def build_threshold_schema(
    repair_type: str,
    defaults: HealthThresholds,
    stored_custom: dict[str, Any],
) -> vol.Schema:
    """Voluptuous schema for repair-step threshold editing."""
    default_map = defaults.as_dict()
    fields: dict[Any, Any] = {}
    for key, lo, hi in threshold_fields_for_repair(repair_type):
        raw = stored_custom.get(key, default_map.get(key))
        fields[
            vol.Required(key, description={"suggested_value": raw})
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(min=lo, max=hi, mode="box", step="any")
        )
    return vol.Schema(fields)


def validate_threshold_input(
    repair_type: str, user_input: dict[str, Any]
) -> dict[str, str]:
    errors: dict[str, str] = {}
    if repair_type == "temperature":
        try:
            chip_warn = float(user_input["temp_chip_warn_c"])
            chip_high = float(user_input["temp_chip_high_c"])
            if chip_warn >= chip_high:
                errors["temp_chip_high_c"] = "temp_warn_must_be_below_critical"
            board_warn = float(user_input["temp_board_warn_c"])
            board_high = float(user_input["temp_board_high_c"])
            if board_warn >= board_high:
                errors["temp_board_high_c"] = "temp_warn_must_be_below_critical"
        except (KeyError, TypeError, ValueError):
            errors["base"] = "invalid_threshold"
    if repair_type == "power":
        try:
            low = float(user_input["power_low_ratio"])
            high = float(user_input["power_high_ratio"])
            if low >= high:
                errors["power_high_ratio"] = "power_low_must_be_below_high"
        except (KeyError, TypeError, ValueError):
            errors["base"] = "invalid_threshold"
    return errors


def merge_threshold_options(
    current_options: dict[str, Any],
    repair_type: str,
    user_input: dict[str, Any],
    *,
    make: str | None,
    model: str | None,
) -> dict[str, Any]:
    """Return new options dict with custom thresholds applied."""
    defaults = health_threshold_defaults_for_ui(make, model, current_options)
    stored = dict(current_options.get(CONF_HEALTH_THRESHOLDS) or {})
    for key, _lo, _hi in threshold_fields_for_repair(repair_type):
        stored[key] = float(user_input[key])
    for key, value in defaults.as_dict().items():
        stored.setdefault(key, value)
    new_options = dict(current_options)
    new_options[CONF_HEALTH_PROFILE] = HEALTH_PROFILE_CUSTOM
    new_options[CONF_HEALTH_THRESHOLDS] = stored
    return new_options
