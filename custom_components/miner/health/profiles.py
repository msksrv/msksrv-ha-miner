"""Resolve health thresholds from model profiles and per-miner options."""

from __future__ import annotations

import re
from typing import Any

from ..const import (
    CONF_HEALTH_PROFILE,
    CONF_HEALTH_THRESHOLDS,
    HEALTH_PROFILE_AUTO,
    HEALTH_PROFILE_CUSTOM,
    HEALTH_PROFILE_GENERIC,
)
from .thresholds import (
    GENERIC_THRESHOLDS,
    MANUFACTURER_THRESHOLDS,
    MODEL_THRESHOLDS,
    HealthThresholds,
)

_PROFILE_LABELS: dict[str, str] = {
    HEALTH_PROFILE_AUTO: "auto",
    HEALTH_PROFILE_GENERIC: "generic",
    HEALTH_PROFILE_CUSTOM: "custom",
}


def _norm_token(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _manufacturer_key(make: str | None, model: str | None) -> str | None:
    text = f"{make or ''} {model or ''}".lower()
    for token in MANUFACTURER_THRESHOLDS:
        if token in text:
            return token
    return None


def _model_key(make: str | None, model: str | None) -> tuple[str, str] | None:
    norm_make = _norm_token(make)
    norm_model = _norm_token(model)
    if not norm_make and not norm_model:
        return None
    if not norm_make:
        norm_make = _manufacturer_key(make, model) or ""
    for mfg, mdl in MODEL_THRESHOLDS:
        if mdl in norm_model and (not mfg or mfg in norm_make or mfg in norm_model):
            return mfg, mdl
    return None


def lookup_auto_profile(
    make: str | None, model: str | None
) -> tuple[HealthThresholds, str]:
    """Return thresholds and a human-readable profile id for auto mode."""
    model_key = _model_key(make, model)
    if model_key is not None:
        mfg, mdl = model_key
        label = f"{mfg}:{mdl}"
        return MODEL_THRESHOLDS[model_key], label

    mfg = _manufacturer_key(make, model)
    if mfg is not None:
        return MANUFACTURER_THRESHOLDS[mfg], mfg

    return GENERIC_THRESHOLDS, "generic"


def resolve_health_thresholds(
    make: str | None,
    model: str | None,
    options: dict[str, Any] | None,
) -> tuple[HealthThresholds, str]:
    """Merge model database with user options."""
    opts = options or {}
    profile = str(opts.get(CONF_HEALTH_PROFILE) or HEALTH_PROFILE_AUTO)

    if profile == HEALTH_PROFILE_GENERIC:
        return GENERIC_THRESHOLDS, _PROFILE_LABELS[HEALTH_PROFILE_GENERIC]

    if profile == HEALTH_PROFILE_CUSTOM:
        custom = HealthThresholds.from_dict(opts.get(CONF_HEALTH_THRESHOLDS))
        return custom, _PROFILE_LABELS[HEALTH_PROFILE_CUSTOM]

    auto, auto_label = lookup_auto_profile(make, model)
    return auto, f"{_PROFILE_LABELS[HEALTH_PROFILE_AUTO]}:{auto_label}"


def health_threshold_defaults_for_ui(
    make: str | None,
    model: str | None,
    options: dict[str, Any] | None,
) -> HealthThresholds:
    """Suggested values for the custom thresholds form."""
    opts = options or {}
    if opts.get(CONF_HEALTH_PROFILE) == HEALTH_PROFILE_CUSTOM:
        return HealthThresholds.from_dict(opts.get(CONF_HEALTH_THRESHOLDS))
    return resolve_health_thresholds(make, model, opts)[0]
