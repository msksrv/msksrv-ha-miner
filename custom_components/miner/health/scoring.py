"""Compute miner health score and diagnostic flags from coordinator data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .thresholds import GENERIC_THRESHOLDS, HealthThresholds

# Component weights (sum = 100)
WEIGHT_HASHRATE = 25
WEIGHT_BOARDS = 20
WEIGHT_TEMPERATURE = 15
WEIGHT_FANS = 10
WEIGHT_REJECT = 10
WEIGHT_POWER = 10
WEIGHT_POOL = 5
WEIGHT_SHARES = 5


@dataclass(frozen=True)
class HealthResult:
    """Aggregated health evaluation."""

    score: int | None
    components: dict[str, float | None]
    flags: dict[str, bool]
    seconds_since_share: float | None
    data_coverage: int
    threshold_profile: str | None = None
    learned_baseline: dict[str, float | str | int | bool | None] | None = None
    hashrate_reference: str | None = None


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _score_hashrate(
    data: dict[str, Any],
    thresholds: HealthThresholds,
    *,
    hashrate_baseline: dict[str, float] | None = None,
) -> tuple[float | None, bool]:
    if not data.get("is_mining"):
        return None, False
    ms = data.get("miner_sensors") or {}
    hr = _f(ms.get("hashrate"))
    if hr is None:
        return None, False
    reference = None
    if hashrate_baseline and hashrate_baseline.get("hashrate"):
        reference = hashrate_baseline["hashrate"]
    else:
        reference = _f(ms.get("ideal_hashrate"))
    if reference is None or reference <= 0:
        return None, False
    ratio = hr / reference
    low = ratio < thresholds.hashrate_low_ratio
    return max(0.0, min(100.0, ratio * 100.0)), low


def _score_boards(
    data: dict[str, Any], thresholds: HealthThresholds
) -> tuple[float | None, bool]:
    boards = data.get("board_sensors") or {}
    if not boards:
        return None, False
    percents: list[float] = []
    board_problem = False
    for board in boards.values():
        if board.get("board_missing"):
            board_problem = True
            percents.append(0.0)
            continue
        pct = _f(board.get("board_effective_chips_percent"))
        hr = _f(board.get("board_hashrate"))
        expected = board.get("board_expected_chips")
        chips = board.get("board_chips")
        if pct is not None:
            percents.append(pct)
            if pct < thresholds.chip_low_percent:
                board_problem = True
        elif expected and chips is not None:
            try:
                if int(expected) > 0 and int(chips) < int(expected) * 0.9:
                    board_problem = True
            except (TypeError, ValueError):
                pass
        if hr is not None and hr <= 0 and data.get("is_mining"):
            board_problem = True
    if not percents:
        return None, board_problem
    avg = sum(percents) / len(percents)
    return max(0.0, min(100.0, avg)), board_problem


def _max_temps(data: dict[str, Any]) -> tuple[float | None, float | None]:
    ms = data.get("miner_sensors") or {}
    avg = _f(ms.get("temperature"))
    max_chip: float | None = None
    max_board: float | None = avg
    for board in (data.get("board_sensors") or {}).values():
        ct = _f(board.get("chip_temperature"))
        bt = _f(board.get("board_temperature"))
        if ct is not None:
            max_chip = ct if max_chip is None else max(max_chip, ct)
        if bt is not None:
            max_board = bt if max_board is None else max(max_board, bt)
    return max_chip, max_board


def _temperature_status(
    max_chip: float | None,
    max_board: float | None,
    thresholds: HealthThresholds,
) -> tuple[bool, bool]:
    """Return (warning, critical) for chip and board peaks."""
    critical = (
        max_chip is not None and max_chip >= thresholds.temp_chip_high_c
    ) or (max_board is not None and max_board >= thresholds.temp_board_high_c)
    if critical:
        return False, True
    warning = (
        max_chip is not None and max_chip >= thresholds.temp_chip_warn_c
    ) or (max_board is not None and max_board >= thresholds.temp_board_warn_c)
    return warning, False


def _score_temperature(
    data: dict[str, Any], thresholds: HealthThresholds
) -> tuple[float | None, bool]:
    max_chip, max_board = _max_temps(data)
    if max_chip is None and max_board is None:
        return None, False
    _warning, critical = _temperature_status(max_chip, max_board, thresholds)

    def _temperature_score(value: float, warn: float, critical_c: float) -> float:
        if value <= warn:
            return 100.0
        if value >= critical_c:
            return 0.0
        return 100.0 - ((value - warn) / (critical_c - warn)) * 100.0

    scores: list[float] = []
    if max_chip is not None:
        scores.append(
            _temperature_score(
                max_chip, thresholds.temp_chip_warn_c, thresholds.temp_chip_high_c
            )
        )
    if max_board is not None:
        scores.append(
            _temperature_score(
                max_board, thresholds.temp_board_warn_c, thresholds.temp_board_high_c
            )
        )
    return min(scores), critical


def _score_fans(
    data: dict[str, Any], thresholds: HealthThresholds
) -> tuple[float | None, bool]:
    fans = data.get("fan_sensors") or {}
    if not fans:
        return None, False
    speeds = [_f(f.get("fan_speed")) for f in fans.values()]
    speeds = [s for s in speeds if s is not None]
    if not speeds:
        return None, False
    mining = bool(data.get("is_mining"))
    problem = mining and any(
        s <= 0 or s < thresholds.fan_min_rpm for s in speeds
    )
    if not mining:
        return None, False
    min_speed = min(speeds)
    if min_speed >= thresholds.fan_min_rpm:
        return 100.0, False
    if min_speed <= 0:
        return 0.0, True
    return max(0.0, (min_speed / thresholds.fan_min_rpm) * 100.0), True


def _score_reject(
    data: dict[str, Any], thresholds: HealthThresholds
) -> tuple[float | None, bool]:
    rr = _f(data.get("reject_rate"))
    if rr is None:
        return None, False
    high = rr >= thresholds.reject_rate_high_pct
    if rr <= 0:
        return 100.0, False
    if rr >= thresholds.reject_rate_high_pct * 3:
        return 0.0, True
    return (
        max(0.0, 100.0 - (rr / thresholds.reject_rate_high_pct) * 33.0),
        high,
    )


def _score_power(
    data: dict[str, Any],
    thresholds: HealthThresholds,
    baseline: dict[str, float] | None = None,
) -> tuple[float | None, bool]:
    ms = data.get("miner_sensors") or {}
    watts = _f(ms.get("miner_consumption"))
    limit = _f(ms.get("power_limit"))
    mining = bool(data.get("is_mining"))
    if watts is None:
        return None, False
    if not mining:
        return None, False

    baseline_power = (baseline or {}).get("power")
    if baseline_power is not None and baseline_power > 0:
        low = baseline_power * thresholds.power_low_ratio
        high = baseline_power * thresholds.power_high_ratio
        anomaly = watts < low or watts > high
        if watts >= high:
            return 0.0, True
        if watts <= low:
            return 30.0, True
        if anomaly:
            return 50.0, True
        ratio = watts / baseline_power
        return max(0.0, min(100.0, 100.0 - abs(1.0 - ratio) * 50.0)), False

    if limit and limit > 0:
        low = limit * thresholds.power_low_ratio
        high = limit * thresholds.power_high_ratio
        anomaly = watts < low or watts > high
        if watts >= high:
            return 0.0, True
        if watts <= low:
            return 30.0, True
        if anomaly:
            return 50.0, True
        ratio = watts / limit
        if ratio > thresholds.power_high_ratio:
            return 0.0, True
        if ratio < thresholds.power_low_ratio:
            return 30.0, True
        return 100.0, anomaly
    return 100.0, False


def _score_pool(
    data: dict[str, Any], thresholds: HealthThresholds
) -> tuple[float | None, bool]:
    ph = data.get("pool_health") or {}
    if not ph:
        return None, False
    active = ph.get("active")
    alive = ph.get("alive")
    stale = _f(ph.get("pool_stale_percent"))
    failures = _f(ph.get("get_failures"))
    problem = False
    if active is False or alive is False:
        problem = True
    if stale is not None and stale >= thresholds.pool_stale_high_pct:
        problem = True
    if failures is not None and failures > 10:
        problem = True
    if problem:
        return 0.0, True
    if active is True and alive is True:
        return 100.0, False
    return 70.0, problem


def _score_shares(
    data: dict[str, Any], thresholds: HealthThresholds
) -> tuple[float | None, bool]:
    secs = _f(data.get("seconds_since_share"))
    mining = bool(data.get("is_mining"))
    if not mining:
        return None, False
    if secs is None:
        return None, False
    stale = thresholds.share_stale_seconds
    if secs <= stale / 3:
        return 100.0, False
    if secs >= stale:
        return 0.0, True
    span = stale * (2 / 3)
    elapsed = secs - stale / 3
    return max(0.0, 100.0 - (elapsed / span) * 100.0), secs >= stale


def compute_health(
    data: dict[str, Any],
    thresholds: HealthThresholds | None = None,
    *,
    threshold_profile: str | None = None,
    power_baseline: dict[str, float] | None = None,
    hashrate_baseline: dict[str, float] | None = None,
    learned_baseline: dict[str, float | str | int | bool | None] | None = None,
) -> HealthResult:
    """Return health score 0–100, per-component scores, and binary flags."""
    t = thresholds or GENERIC_THRESHOLDS
    parts: list[tuple[str, float, float]] = []
    flags: dict[str, bool] = {}

    hashrate_reference = (
        "baseline"
        if hashrate_baseline and hashrate_baseline.get("hashrate")
        else "ideal"
    )

    scorers = (
        (
            "hashrate",
            WEIGHT_HASHRATE,
            lambda d, th: _score_hashrate(d, th, hashrate_baseline=hashrate_baseline),
        ),
        ("boards", WEIGHT_BOARDS, _score_boards),
        ("temperature", WEIGHT_TEMPERATURE, _score_temperature),
        ("fans", WEIGHT_FANS, _score_fans),
        ("reject", WEIGHT_REJECT, _score_reject),
        (
            "power",
            WEIGHT_POWER,
            lambda d, th: _score_power(d, th, baseline=power_baseline),
        ),
        ("pool", WEIGHT_POOL, _score_pool),
        ("shares", WEIGHT_SHARES, _score_shares),
    )

    components: dict[str, float | None] = {}
    for key, weight, fn in scorers:
        comp_score, flag = fn(data, t)
        flag_key = {
            "hashrate": "hashrate_low",
            "boards": "board_problem",
            "temperature": "temperature_high",
            "fans": "fan_problem",
            "reject": "reject_rate_high",
            "power": "power_anomaly",
            "pool": "pool_problem",
            "shares": "share_stale",
        }[key]
        flags[flag_key] = flag
        components[key] = comp_score
        if comp_score is not None:
            parts.append((key, comp_score, weight))

    max_chip, max_board = _max_temps(data)
    temp_warning, _temp_critical = _temperature_status(max_chip, max_board, t)
    flags["temperature_warning"] = temp_warning

    if not parts:
        score = None
        data_coverage = 0
    else:
        total_w = sum(w for _, _, w in parts)
        score = round(sum(s * w for _, s, w in parts) / total_w)
        data_coverage = round(total_w)

        if data.get("fault_light"):
            score = min(score, 50)
        elif data.get("errors"):
            score = min(score, 65)

    problem_count = sum(
        1 for k, v in flags.items() if v and k != "share_stale"
    )
    if data.get("fault_light"):
        problem_count += 1
    errors = data.get("errors") or []
    if errors:
        problem_count += 1

    flags["maintenance_required"] = (
        (score is not None and score < t.maintenance_score)
        or problem_count >= t.maintenance_min_flags
        or bool(data.get("fault_light"))
        or bool(errors)
        or flags.get("temperature_high")
    )

    secs = _f(data.get("seconds_since_share"))
    return HealthResult(
        score=score,
        components=components,
        flags=flags,
        seconds_since_share=secs,
        data_coverage=data_coverage,
        threshold_profile=threshold_profile,
        learned_baseline=learned_baseline,
        hashrate_reference=hashrate_reference,
    )
