"""Resolve repair confirm/recovery timers from config entry options."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry

from ...const import (
    CONF_REPAIR_CONFIRM_DEFAULT,
    CONF_REPAIR_CONFIRM_OVERRIDES,
    CONF_REPAIR_RECOVERY,
)
from .definitions import RepairType

# Types that never use the general delay (safety or instant anomaly).
_FIXED_CONFIRM_SECONDS: dict[str, float] = {
    RepairType.TEMPERATURE: 180,
    RepairType.FAN: 180,
    RepairType.OFFLINE: 600,
    RepairType.RECOVERY: 0,
}

DEFAULT_CONFIRM_SECONDS = 300.0
DEFAULT_RECOVERY_SECONDS = 240.0


def resolve_recovery_seconds(entry: ConfigEntry) -> float:
    opts = entry.options or {}
    try:
        return float(opts.get(CONF_REPAIR_RECOVERY, DEFAULT_RECOVERY_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_RECOVERY_SECONDS


def resolve_confirm_seconds(entry: ConfigEntry, repair_type: str) -> float:
    """Return confirm delay for a repair type (seconds)."""
    opts = entry.options or {}
    overrides = opts.get(CONF_REPAIR_CONFIRM_OVERRIDES) or {}
    if repair_type in overrides and overrides[repair_type] is not None:
        try:
            return float(overrides[repair_type])
        except (TypeError, ValueError):
            pass
    if repair_type in _FIXED_CONFIRM_SECONDS:
        return _FIXED_CONFIRM_SECONDS[repair_type]
    try:
        return float(opts.get(CONF_REPAIR_CONFIRM_DEFAULT, DEFAULT_CONFIRM_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_CONFIRM_SECONDS
