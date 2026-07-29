"""Explainable anomaly rules against learned baselines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RULE_HASHRATE_POWER_DURATION = 180
RULE_HASHRATE_EFFICIENCY_DURATION = 300
RULE_BOARD_OUTLIER_DURATION = 300
RULE_FAN_IMBALANCE_DURATION = 300
RULE_EFFICIENCY_DURATION = 600
RULE_REJECT_DURATION = 300
RULE_SHARE_STALE_FACTOR = 8
RULE_REBOOT_RECOVERY_DURATION = 900


@dataclass
class AnomalyFinding:
    reason: str
    severity: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnomalyState:
    score: int
    confidence: int
    detected: bool
    severity: str | None
    reason: str | None
    message: str | None
    findings: list[AnomalyFinding] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    detected_at: str | None = None


def _pct_delta(current: float, baseline: float) -> float:
    if baseline == 0:
        return 0.0
    return ((current - baseline) / baseline) * 100.0


def _rule_active(timer: dict[str, float], key: str, condition: bool, now: float) -> bool:
    if condition:
        timer.setdefault(key, now)
        return True
    timer.pop(key, None)
    return False


def _rule_elapsed(timer: dict[str, float], key: str, now: float, duration: float) -> bool:
    start = timer.get(key)
    if start is None:
        return False
    return (now - start) >= duration


def detect_anomalies(
    *,
    data: dict[str, Any],
    baselines: dict[str, float],
    timers: dict[str, float],
    now: float,
    confidence: int,
    learning: bool,
    reboot_watch: bool,
) -> AnomalyState:
    """Evaluate all rules against structured coordinator data."""
    if learning or confidence < 20:
        return AnomalyState(
            score=0,
            confidence=confidence,
            detected=False,
            severity=None,
            reason=None,
            message=None,
        )

    findings: list[AnomalyFinding] = []
    ms = data.get("miner_sensors") or {}
    hr = _f(ms.get("hashrate"))
    power = _f(ms.get("miner_consumption"))
    eff = _f(ms.get("efficiency"))
    reject = _f(data.get("reject_rate"))
    share_age = _f(data.get("seconds_since_share"))
    boards = data.get("board_sensors") or {}
    fans = data.get("fan_sensors") or {}

    b_hr = baselines.get("hashrate")
    b_pwr = baselines.get("power")
    b_eff = baselines.get("efficiency")
    b_reject = baselines.get("reject_rate")
    b_share = baselines.get("share_interval")

    if hr is not None and power is not None and b_hr and b_pwr:
        cond = power >= b_pwr * 0.8 and hr < b_hr * 0.2
        if _rule_active(timers, "hashrate_power", cond, now) and _rule_elapsed(
            timers, "hashrate_power", now, RULE_HASHRATE_POWER_DURATION
        ):
            findings.append(
                AnomalyFinding(
                    reason="hashrate_power_mismatch",
                    severity="critical",
                    details={
                        "baseline_hashrate": round(b_hr, 2),
                        "current_hashrate": round(hr, 2),
                        "baseline_power": round(b_pwr, 0),
                        "current_power": round(power, 0),
                    },
                )
            )

    if hr is not None and power is not None and b_hr and b_pwr:
        cond = hr < b_hr * 0.8 and power >= b_pwr * 0.9
        if _rule_active(timers, "hashrate_eff", cond, now) and _rule_elapsed(
            timers, "hashrate_eff", now, RULE_HASHRATE_EFFICIENCY_DURATION
        ):
            findings.append(
                AnomalyFinding(
                    reason="hashrate_efficiency_drop",
                    severity="warning",
                    details={
                        "baseline_hashrate": round(b_hr, 2),
                        "current_hashrate": round(hr, 2),
                        "baseline_power": round(b_pwr, 0),
                        "current_power": round(power, 0),
                        "hashrate_drop_pct": round(abs(_pct_delta(hr, b_hr)), 0),
                        "power_change_pct": round(abs(_pct_delta(power, b_pwr)), 0),
                    },
                )
            )

    board_hrs: list[tuple[str, float]] = []
    for slot, board in boards.items():
        bhr = _f(board.get("board_hashrate"))
        if bhr is not None and bhr > 0:
            board_hrs.append((str(slot), bhr))
    if len(board_hrs) >= 2:
        vals = [v for _, v in board_hrs]
        med = sorted(vals)[len(vals) // 2]
        for slot, bhr in board_hrs:
            cond = med > 0 and bhr < med * 0.75
            key = f"board_hr_{slot}"
            if _rule_active(timers, key, cond, now) and _rule_elapsed(
                timers, key, now, RULE_BOARD_OUTLIER_DURATION
            ):
                findings.append(
                    AnomalyFinding(
                        reason="board_hashrate_outlier",
                        severity="warning",
                        details={
                            "board": slot,
                            "board_hashrate": round(bhr, 2),
                            "median_board_hashrate": round(med, 2),
                            "pct_below": round((1 - bhr / med) * 100, 0),
                        },
                    )
                )

    board_temps: list[tuple[str, float]] = []
    for slot, board in boards.items():
        ct = _f(board.get("chip_temperature")) or _f(board.get("board_temperature"))
        if ct is not None:
            board_temps.append((str(slot), ct))
    if len(board_temps) >= 2:
        vals = [v for _, v in board_temps]
        med = sorted(vals)[len(vals) // 2]
        for slot, temp in board_temps:
            cond = med - temp >= 10
            key = f"board_temp_{slot}"
            if _rule_active(timers, key, cond, now) and _rule_elapsed(
                timers, key, now, RULE_BOARD_OUTLIER_DURATION
            ):
                findings.append(
                    AnomalyFinding(
                        reason="board_temp_outlier",
                        severity="warning",
                        details={
                            "board": slot,
                            "board_temperature": round(temp, 1),
                            "median_board_temperature": round(med, 1),
                            "temp_delta": round(med - temp, 0),
                        },
                    )
                )

    fan_speeds: list[tuple[str, float]] = []
    for idx, fan in fans.items():
        spd = _f(fan.get("fan_speed"))
        if spd is not None and spd > 0:
            fan_speeds.append((str(idx), spd))
    if len(fan_speeds) >= 2:
        vals = [v for _, v in fan_speeds]
        med = sorted(vals)[len(vals) // 2]
        for idx, spd in fan_speeds:
            cond = med > 0 and spd < med * 0.7
            key = f"fan_{idx}"
            if _rule_active(timers, key, cond, now) and _rule_elapsed(
                timers, key, now, RULE_FAN_IMBALANCE_DURATION
            ):
                findings.append(
                    AnomalyFinding(
                        reason="fan_imbalance",
                        severity="warning",
                        details={
                            "fan": idx,
                            "fan_speed": round(spd, 0),
                            "median_fan_speed": round(med, 0),
                            "pct_below": round((1 - spd / med) * 100, 0),
                        },
                    )
                )

    if eff is not None and b_eff and b_eff > 0:
        cond = eff > b_eff * 1.15
        if _rule_active(timers, "efficiency", cond, now) and _rule_elapsed(
            timers, "efficiency", now, RULE_EFFICIENCY_DURATION
        ):
            findings.append(
                AnomalyFinding(
                    reason="efficiency_degraded",
                    severity="warning",
                    details={
                        "baseline_efficiency": round(b_eff, 1),
                        "current_efficiency": round(eff, 1),
                        "degradation_pct": round(_pct_delta(eff, b_eff), 0),
                    },
                )
            )

    total_shares = (_f(data.get("accepted_shares")) or 0) + (
        _f(data.get("rejected_shares")) or 0
    )
    if reject is not None and b_reject is not None and total_shares >= 100:
        cond = reject > max(b_reject + 1.0, b_reject * 2, 2.0)
        if _rule_active(timers, "reject", cond, now) and _rule_elapsed(
            timers, "reject", now, RULE_REJECT_DURATION
        ):
            findings.append(
                AnomalyFinding(
                    reason="reject_rate_high",
                    severity="warning",
                    details={
                        "baseline_reject_rate": round(b_reject, 2),
                        "current_reject_rate": round(reject, 2),
                        "total_shares": int(total_shares),
                    },
                )
            )

    if share_age is not None and b_share and b_share > 0:
        limit = max(b_share * RULE_SHARE_STALE_FACTOR, b_share + 120)
        cond = share_age >= limit
        if _rule_active(timers, "share_stale", cond, now) and cond:
            findings.append(
                AnomalyFinding(
                    reason="share_stale",
                    severity="warning",
                    details={
                        "baseline_share_interval": round(b_share, 0),
                        "seconds_since_share": round(share_age, 0),
                    },
                )
            )

    if reboot_watch and hr is not None and b_hr:
        cond = hr < b_hr * 0.85
        if _rule_active(timers, "reboot_recovery", cond, now) and _rule_elapsed(
            timers, "reboot_recovery", now, RULE_REBOOT_RECOVERY_DURATION
        ):
            findings.append(
                AnomalyFinding(
                    reason="post_reboot_slow_recovery",
                    severity="warning",
                    details={
                        "baseline_hashrate": round(b_hr, 2),
                        "current_hashrate": round(hr, 2),
                        "recovery_pct": round(hr / b_hr * 100, 0),
                    },
                )
            )

    if not findings:
        return AnomalyState(
            score=0,
            confidence=confidence,
            detected=False,
            severity=None,
            reason=None,
            message=None,
        )

    score = min(100, sum(30 if f.severity == "critical" else 18 for f in findings))
    primary = max(
        findings,
        key=lambda f: (1 if f.severity == "critical" else 0, len(f.details)),
    )
    merged_details = {**primary.details, "confidence": confidence}
    return AnomalyState(
        score=score,
        confidence=confidence,
        detected=True,
        severity=primary.severity,
        reason=primary.reason,
        message=None,
        findings=findings,
        details=merged_details,
    )


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
