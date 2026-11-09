"""Capture the readings available when a miner problem is reported."""

from __future__ import annotations

import math
from typing import Any

from ..health.repairs.definitions import RepairType
from ..health.scoring import max_temperatures
from ..health.thresholds import HealthThresholds


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _hashboard_metrics(boards: dict, thresholds: HealthThresholds) -> dict[str, Any]:
    for slot, board in boards.items():
        chips = _number(board.get("board_chips"))
        expected = _number(board.get("board_expected_chips"))
        percent = _number(board.get("board_effective_chips_percent"))
        hashrate = _number(board.get("board_hashrate"))
        missing = board.get("board_missing") is True
        low_chips = (
            percent < thresholds.chip_low_percent
            if percent is not None
            else bool(expected and chips is not None and chips < expected * 0.9)
        )
        if missing or low_chips or (hashrate is not None and hashrate <= 0):
            return {
                "board": str(slot),
                "board_missing": missing,
                "board_hashrate": hashrate,
                "working_chips": chips,
                "expected_chips": expected,
            }
    return {}


def _fan_metrics(fans: dict, thresholds: HealthThresholds) -> dict[str, Any]:
    measured = [
        (rpm, str(slot))
        for slot, fan in fans.items()
        if (rpm := _number(fan.get("fan_speed"))) is not None
    ]
    if not measured:
        return {}
    rpm, slot = min(measured)
    return {
        "fan": slot,
        "fan_speed": rpm,
        "fan_speed_limit_rpm": thresholds.fan_min_rpm,
    }


def problem_metrics(
    problem: str, data: dict[str, Any], thresholds: HealthThresholds
) -> dict[str, Any]:
    """Return supporting readings without changing how problems are detected."""
    sensors = data.get("miner_sensors") or {}
    health = data.get("health") or {}
    flags = health.get("flags") or {}
    baseline = health.get("learned_baseline") or {}

    match problem:
        case RepairType.TEMPERATURE:
            chip, board = max_temperatures(data)
            return {
                "max_chip_temperature_c": chip,
                "chip_temperature_limit_c": thresholds.temp_chip_high_c
                if chip is not None
                else None,
                "max_board_temperature_c": board,
                "board_temperature_limit_c": thresholds.temp_board_high_c
                if board is not None
                else None,
            }
        case RepairType.HASHBOARD:
            return _hashboard_metrics(data.get("board_sensors") or {}, thresholds)
        case RepairType.HASHRATE:
            reference = _number(
                baseline.get("hashrate_th")
                if health.get("hashrate_reference") == "baseline"
                else sensors.get("ideal_hashrate")
            )
            return {
                "current_hashrate": sensors.get("hashrate"),
                "expected_hashrate": reference if reference and reference > 0 else None,
                "hashrate_limit": round(reference * thresholds.hashrate_low_ratio, 2)
                if flags.get("hashrate_low") and reference and reference > 0
                else None,
            }
        case RepairType.FAN:
            return _fan_metrics(data.get("fan_sensors") or {}, thresholds)
        case RepairType.POOL:
            pool = data.get("pool_health") or {}
            return {
                "pool_active": pool.get("active"),
                "pool_alive": pool.get("alive"),
                "pool_get_failures": pool.get("get_failures"),
                "pool_stale_percent": pool.get("pool_stale_percent"),
                "pool_stale_limit_percent": thresholds.pool_stale_high_pct
                if pool.get("pool_stale_percent") is not None
                else None,
                "seconds_since_share": data.get("seconds_since_share"),
                "share_stale_limit_seconds": thresholds.share_stale_seconds
                if flags.get("share_stale")
                else None,
            }
        case RepairType.REJECT:
            return {
                "current_reject_rate": data.get("reject_rate"),
                "reject_rate_limit_percent": thresholds.reject_rate_high_pct
                if flags.get("reject_rate_high")
                else None,
                "accepted_shares": data.get("accepted_shares"),
                "rejected_shares": data.get("rejected_shares"),
            }
        case RepairType.POWER:
            baseline_power = (
                _number(baseline.get("power_w"))
                if baseline.get("ready")
                and str(health.get("threshold_profile", "")).startswith("auto:")
                else None
            )
            configured_limit = _number(sensors.get("power_limit"))
            reference = (
                baseline_power
                if baseline_power and baseline_power > 0
                else configured_limit
            )
            return {
                "current_power": sensors.get("miner_consumption"),
                "baseline_power": baseline_power,
                "configured_power_limit_w": configured_limit,
                "power_lower_bound_w": round(reference * thresholds.power_low_ratio, 1)
                if reference and reference > 0
                else None,
                "power_upper_bound_w": round(reference * thresholds.power_high_ratio, 1)
                if reference and reference > 0
                else None,
            }
        case RepairType.RECOVERY | RepairType.RECOVERY_FAILED:
            return {
                "current_hashrate": sensors.get("hashrate"),
                "expected_hashrate": sensors.get("ideal_hashrate"),
            }
        case _:
            return {}
