"""Health scoring thresholds — defaults, storage, and merge.

Manufacturer and model profiles are starting recommendations. Firmware,
sensor placement, and chip/board temperature semantics vary — verify limits
for your hardware or use Custom thresholds in integration options.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any


@dataclass(frozen=True)
class HealthThresholds:
    """Numeric thresholds used by health scoring."""

    temp_chip_warn_c: float = 90.0
    temp_chip_high_c: float = 95.0
    temp_board_warn_c: float = 75.0
    temp_board_high_c: float = 85.0
    hashrate_low_ratio: float = 0.85
    chip_low_percent: float = 90.0
    reject_rate_high_pct: float = 2.0
    fan_min_rpm: float = 1000.0
    share_stale_seconds: float = 600.0
    maintenance_score: int = 70
    maintenance_min_flags: int = 3
    power_over_limit_ratio: float = 1.05
    pool_stale_high_pct: float = 5.0

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> HealthThresholds:
        if not data:
            return GENERIC_THRESHOLDS
        kwargs: dict[str, Any] = {}
        valid = {f.name for f in fields(cls)}
        for key in valid:
            if key in data and data[key] is not None and data[key] != "":
                try:
                    kwargs[key] = (
                        int(data[key])
                        if key in ("maintenance_score", "maintenance_min_flags")
                        else float(data[key])
                    )
                except (TypeError, ValueError):
                    pass
        return cls(**{**asdict(GENERIC_THRESHOLDS), **kwargs})


GENERIC_THRESHOLDS = HealthThresholds()

# Manufacturer defaults (normalized make substring → thresholds).
MANUFACTURER_THRESHOLDS: dict[str, HealthThresholds] = {
    "whatsminer": HealthThresholds(
        temp_chip_warn_c=90.0,
        temp_chip_high_c=95.0,
        temp_board_warn_c=75.0,
        temp_board_high_c=85.0,
    ),
    "microbt": HealthThresholds(
        temp_chip_warn_c=90.0,
        temp_chip_high_c=95.0,
        temp_board_warn_c=75.0,
        temp_board_high_c=85.0,
    ),
    "bitmain": HealthThresholds(
        temp_chip_warn_c=85.0,
        temp_chip_high_c=90.0,
        temp_board_warn_c=70.0,
        temp_board_high_c=80.0,
    ),
    "antminer": HealthThresholds(
        temp_chip_warn_c=85.0,
        temp_chip_high_c=90.0,
        temp_board_warn_c=70.0,
        temp_board_high_c=80.0,
    ),
    "canaan": HealthThresholds(
        temp_chip_warn_c=88.0,
        temp_chip_high_c=93.0,
        temp_board_warn_c=72.0,
        temp_board_high_c=82.0,
    ),
    "avalon": HealthThresholds(
        temp_chip_warn_c=88.0,
        temp_chip_high_c=93.0,
        temp_board_warn_c=72.0,
        temp_board_high_c=82.0,
    ),
    "innosilicon": HealthThresholds(
        temp_chip_warn_c=88.0,
        temp_chip_high_c=93.0,
        temp_board_warn_c=72.0,
        temp_board_high_c=82.0,
    ),
    "goldshell": HealthThresholds(
        temp_chip_warn_c=82.0,
        temp_chip_high_c=88.0,
        temp_board_warn_c=68.0,
        temp_board_high_c=78.0,
    ),
    "iceriver": HealthThresholds(
        temp_chip_warn_c=82.0,
        temp_chip_high_c=88.0,
        temp_board_warn_c=68.0,
        temp_board_high_c=78.0,
    ),
}

# Model-specific overrides: (make token, model token) after normalization.
MODEL_THRESHOLDS: dict[tuple[str, str], HealthThresholds] = {
    ("whatsminer", "m21s"): HealthThresholds(
        temp_chip_warn_c=90.0,
        temp_chip_high_c=95.0,
        temp_board_warn_c=75.0,
        temp_board_high_c=85.0,
    ),
    ("whatsminer", "m30"): HealthThresholds(
        temp_chip_warn_c=88.0,
        temp_chip_high_c=93.0,
        temp_board_warn_c=75.0,
        temp_board_high_c=85.0,
    ),
    ("whatsminer", "m50"): HealthThresholds(
        temp_chip_warn_c=88.0,
        temp_chip_high_c=93.0,
        temp_board_warn_c=75.0,
        temp_board_high_c=85.0,
    ),
    ("bitmain", "s19"): HealthThresholds(
        temp_chip_warn_c=85.0,
        temp_chip_high_c=90.0,
        temp_board_warn_c=70.0,
        temp_board_high_c=80.0,
    ),
    ("bitmain", "s21"): HealthThresholds(
        temp_chip_warn_c=85.0,
        temp_chip_high_c=90.0,
        temp_board_warn_c=70.0,
        temp_board_high_c=80.0,
    ),
    ("bitmain", "t21"): HealthThresholds(
        temp_chip_warn_c=85.0,
        temp_chip_high_c=90.0,
        temp_board_warn_c=70.0,
        temp_board_high_c=80.0,
    ),
}
