"""Compute miner health score and diagnostic flags from coordinator data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Component weights (sum = 100)
WEIGHT_HASHRATE = 25
WEIGHT_BOARDS = 20
WEIGHT_TEMPERATURE = 15
WEIGHT_FANS = 10
WEIGHT_REJECT = 10
WEIGHT_POWER = 10
WEIGHT_POOL = 5
WEIGHT_SHARES = 5

# Thresholds
HASHRATE_LOW_RATIO = 0.85
CHIP_LOW_PERCENT = 90.0
TEMP_CHIP_HIGH_C = 85.0
TEMP_BOARD_HIGH_C = 75.0
REJECT_RATE_HIGH_PCT = 2.0
FAN_MIN_RPM = 1000
SHARE_STALE_SECONDS = 600
MAINTENANCE_SCORE = 70
MAINTENANCE_MIN_FLAGS = 3
POWER_OVER_LIMIT_RATIO = 1.05
POOL_STALE_HIGH_PCT = 5.0


@dataclass(frozen=True)
class HealthResult:
    """Aggregated health evaluation."""

    score: int | None
    components: dict[str, float | None]
    flags: dict[str, bool]
    seconds_since_share: float | None


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _score_hashrate(data: dict[str, Any]) -> tuple[float | None, bool]:
    ms = data.get("miner_sensors") or {}
    hr = _f(ms.get("hashrate"))
    ideal = _f(ms.get("ideal_hashrate"))
    if hr is None or ideal is None or ideal <= 0:
        return None, False
    ratio = hr / ideal
    low = ratio < HASHRATE_LOW_RATIO
    return max(0.0, min(100.0, ratio * 100.0)), low


def _score_boards(data: dict[str, Any]) -> tuple[float | None, bool]:
    boards = data.get("board_sensors") or {}
    if not boards:
        return None, False
    percents: list[float] = []
    board_problem = False
    for slot, board in boards.items():
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
            if pct < CHIP_LOW_PERCENT:
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


def _score_temperature(data: dict[str, Any]) -> tuple[float | None, bool]:
    max_chip, max_board = _max_temps(data)
    if max_chip is None and max_board is None:
        return None, False
    ref = max(v for v in (max_chip, max_board) if v is not None)
    high = (max_chip is not None and max_chip >= TEMP_CHIP_HIGH_C) or (
        max_board is not None and max_board >= TEMP_BOARD_HIGH_C
    )
    if ref <= TEMP_BOARD_HIGH_C:
        comp = 100.0
    elif ref >= TEMP_CHIP_HIGH_C:
        comp = 0.0
    else:
        span = TEMP_CHIP_HIGH_C - TEMP_BOARD_HIGH_C
        comp = max(0.0, 100.0 - ((ref - TEMP_BOARD_HIGH_C) / span) * 100.0)
    return comp, high


def _score_fans(data: dict[str, Any]) -> tuple[float | None, bool]:
    fans = data.get("fan_sensors") or {}
    if not fans:
        return None, False
    speeds = [_f(f.get("fan_speed")) for f in fans.values()]
    speeds = [s for s in speeds if s is not None]
    if not speeds:
        return None, False
    mining = bool(data.get("is_mining"))
    problem = mining and any(s <= 0 or s < FAN_MIN_RPM for s in speeds)
    if not mining:
        return 100.0, problem
    min_speed = min(speeds)
    if min_speed >= FAN_MIN_RPM:
        return 100.0, False
    if min_speed <= 0:
        return 0.0, True
    return max(0.0, (min_speed / FAN_MIN_RPM) * 100.0), True


def _score_reject(data: dict[str, Any]) -> tuple[float | None, bool]:
    rr = _f(data.get("reject_rate"))
    if rr is None:
        return None, False
    high = rr >= REJECT_RATE_HIGH_PCT
    if rr <= 0:
        return 100.0, False
    if rr >= REJECT_RATE_HIGH_PCT * 3:
        return 0.0, True
    return max(0.0, 100.0 - (rr / REJECT_RATE_HIGH_PCT) * 33.0), high


def _score_power(data: dict[str, Any]) -> tuple[float | None, bool]:
    ms = data.get("miner_sensors") or {}
    watts = _f(ms.get("miner_consumption"))
    limit = _f(ms.get("power_limit"))
    mining = bool(data.get("is_mining"))
    if watts is None:
        return None, False
    anomaly = False
    if limit and limit > 0 and watts > limit * POWER_OVER_LIMIT_RATIO:
        anomaly = True
    if mining and limit and limit > 0 and watts < limit * 0.05:
        anomaly = True
    if limit and limit > 0:
        ratio = watts / limit
        if ratio > POWER_OVER_LIMIT_RATIO:
            return 0.0, True
        if mining and ratio < 0.05:
            return 30.0, True
        return max(0.0, min(100.0, ratio * 100.0)), anomaly
    return 100.0 if not anomaly else 50.0, anomaly


def _score_pool(data: dict[str, Any]) -> tuple[float | None, bool]:
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
    if stale is not None and stale >= POOL_STALE_HIGH_PCT:
        problem = True
    if failures is not None and failures > 10:
        problem = True
    if problem:
        return 0.0, True
    if active is True and alive is True:
        return 100.0, False
    return 70.0, problem


def _score_shares(data: dict[str, Any]) -> tuple[float | None, bool]:
    secs = _f(data.get("seconds_since_share"))
    mining = bool(data.get("is_mining"))
    if not mining:
        return 100.0, False
    if secs is None:
        return None, False
    if secs <= SHARE_STALE_SECONDS / 3:
        return 100.0, False
    if secs >= SHARE_STALE_SECONDS:
        return 0.0, True
    span = SHARE_STALE_SECONDS * (2 / 3)
    elapsed = secs - SHARE_STALE_SECONDS / 3
    return max(0.0, 100.0 - (elapsed / span) * 100.0), secs >= SHARE_STALE_SECONDS


def compute_health(data: dict[str, Any]) -> HealthResult:
    """Return health score 0–100, per-component scores, and binary flags."""
    parts: list[tuple[str, float, float]] = []
    flags: dict[str, bool] = {}

    for key, weight, fn in (
        ("hashrate", WEIGHT_HASHRATE, _score_hashrate),
        ("boards", WEIGHT_BOARDS, _score_boards),
        ("temperature", WEIGHT_TEMPERATURE, _score_temperature),
        ("fans", WEIGHT_FANS, _score_fans),
        ("reject", WEIGHT_REJECT, _score_reject),
        ("power", WEIGHT_POWER, _score_power),
        ("pool", WEIGHT_POOL, _score_pool),
        ("shares", WEIGHT_SHARES, _score_shares),
    ):
        comp_score, flag = fn(data)
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
        if comp_score is not None:
            parts.append((key, comp_score, weight))

    components = {
        "hashrate": _score_hashrate(data)[0],
        "boards": _score_boards(data)[0],
        "temperature": _score_temperature(data)[0],
        "fans": _score_fans(data)[0],
        "reject": _score_reject(data)[0],
        "power": _score_power(data)[0],
        "pool": _score_pool(data)[0],
        "shares": _score_shares(data)[0],
    }

    if not parts:
        score = None
    else:
        total_w = sum(w for _, _, w in parts)
        score = round(sum(s * w for _, s, w in parts) / total_w)

    problem_count = sum(
        1 for k, v in flags.items() if v and k != "share_stale"
    )
    if data.get("fault_light"):
        problem_count += 1
    errors = data.get("errors") or []
    if errors:
        problem_count += 1

    flags["maintenance_required"] = (
        (score is not None and score < MAINTENANCE_SCORE)
        or problem_count >= MAINTENANCE_MIN_FLAGS
        or bool(data.get("fault_light"))
        or bool(errors)
    )

    secs = _f(data.get("seconds_since_share"))
    return HealthResult(
        score=score,
        components=components,
        flags=flags,
        seconds_since_share=secs,
    )
