"""Farm-level health aggregation and miner classification."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import CONF_IP

PROBLEM_FLAGS = frozenset(
    {
        "hashrate_low",
        "temperature_high",
        "fan_problem",
        "board_problem",
        "reject_rate_high",
        "pool_problem",
        "power_anomaly",
    }
)

ISSUE_COUNT_EXCLUDED = frozenset(
    {
        "share_stale",
        "temperature_warning",
        "maintenance_required",
    }
)

MIN_SHARES_FOR_REJECT = 100
MAX_PROBLEM_DEVICES = 20
ATTENTION_STATUSES = frozenset({"warning", "problem", "offline"})


@dataclass
class MinerMemberSnapshot:
    """Per-miner farm health snapshot."""

    name: str
    ip: str
    status: str
    issues: list[str] = field(default_factory=list)
    health_score: int | None = None
    algorithm: str | None = None
    actual_hashrate_th: float = 0.0
    expected_hashrate_th: float | None = None
    expected_source: str = "unknown"
    max_temperature: float | None = None
    temperature_source: str | None = None
    reject_rate: float | None = None
    accepted_shares: int | None = None
    rejected_shares: int | None = None
    is_online: bool = False


def compute_farm_health_metrics(
    member_pairs: list[tuple[ConfigEntry, Any]],
) -> dict[str, Any]:
    """Aggregate farm health metrics from miner member pairs."""
    snapshots = [_classify_member(entry, coord) for entry, coord in member_pairs]
    status_counts = Counter(s.status for s in snapshots)

    algorithms = sorted({s.algorithm for s in snapshots if s.algorithm})
    mixed_algorithms = len(algorithms) > 1

    health_scores: list[int] = []
    health_issue_counts: Counter[str] = Counter()
    for entry, coord in member_pairs:
        if coord is None or not coord.last_update_success:
            continue
        health = coord.data.get("health") or {}
        member_score = health.get("score")
        if member_score is not None:
            try:
                health_scores.append(int(member_score))
            except (TypeError, ValueError):
                pass
        for issue, active in (health.get("flags") or {}).items():
            if active and issue not in ISSUE_COUNT_EXCLUDED:
                health_issue_counts[str(issue)] += 1

    expected_total = 0.0
    expected_known = 0
    expected_unknown = 0
    actual_for_known = 0.0
    total_power_w = 0.0

    for snap in snapshots:
        if snap.expected_hashrate_th is not None:
            expected_total += snap.expected_hashrate_th
            actual_for_known += snap.actual_hashrate_th
            expected_known += 1
        else:
            expected_unknown += 1

    for _entry, coord in member_pairs:
        if coord is None or not coord.last_update_success:
            continue
        ms = coord.data.get("miner_sensors") or {}
        w = _try_float(ms.get("miner_consumption"))
        if w is not None:
            total_power_w += w

    lost_hashrate = max(expected_total - actual_for_known, 0.0)
    lost_percent = (
        round(100.0 * lost_hashrate / expected_total, 1)
        if expected_total > 0
        else None
    )

    actual_total = sum(s.actual_hashrate_th for s in snapshots)
    average_efficiency = None
    if not mixed_algorithms and actual_total > 0 and total_power_w > 0:
        average_efficiency = round(total_power_w / actual_total, 1)

    hottest = _pick_hottest(snapshots)
    worst_reject = _pick_worst_reject(snapshots)
    problem_devices, problem_truncated = _problem_devices(snapshots)

    hashrate_metrics_unavailable = mixed_algorithms

    return {
        "miners_healthy": status_counts.get("healthy", 0),
        "miners_warning": status_counts.get("warning", 0),
        "miners_problem": status_counts.get("problem", 0),
        "miners_unknown": status_counts.get("unknown", 0),
        "miners_with_issues": status_counts.get("warning", 0)
        + status_counts.get("problem", 0),
        "expected_hashrate_th": round(expected_total, 2) if expected_known else None,
        "expected_miners": len(snapshots),
        "expected_miners_unknown": expected_unknown,
        "expected_hashrate_reference": "baseline_and_ideal",
        "lost_hashrate_th": round(lost_hashrate, 2) if expected_known else None,
        "lost_hashrate_percent": lost_percent,
        "average_efficiency_jth": average_efficiency,
        "hashrate_metrics_mixed_algorithms": hashrate_metrics_unavailable,
        "hashrate_metrics_algorithms": algorithms,
        "hottest_miner": hottest,
        "worst_reject_rate": worst_reject,
        "health_status_counts": {
            "healthy": status_counts.get("healthy", 0),
            "warning": status_counts.get("warning", 0),
            "problem": status_counts.get("problem", 0),
            "offline": status_counts.get("offline", 0),
            "unknown": status_counts.get("unknown", 0),
        },
        "health_problem_devices": problem_devices,
        "health_problem_devices_truncated": problem_truncated,
        "health_scores": health_scores,
        "health_issue_counts": health_issue_counts,
        "total_power_w_for_efficiency": round(total_power_w, 0),
    }


def _classify_member(entry: ConfigEntry, coord) -> MinerMemberSnapshot:
    name = _member_name(entry)
    ip = _member_ip(entry, coord)
    online = coord is not None and coord.last_update_success
    data = (coord.data or {}) if coord is not None else {}

    expected, source = _expected_hashrate(data)
    actual = _actual_hashrate(data) if online else 0.0
    max_temp, temp_source = _max_temperature(data)
    reject_rate, accepted, rejected = _reject_stats(data)
    algorithm = data.get("algorithm")
    algo_s = str(algorithm).strip() if algorithm else None

    if not online:
        return MinerMemberSnapshot(
            name=name,
            ip=ip,
            status="offline",
            issues=["offline"],
            health_score=None,
            algorithm=algo_s,
            actual_hashrate_th=0.0,
            expected_hashrate_th=expected,
            expected_source=source,
            max_temperature=max_temp,
            temperature_source=temp_source,
            reject_rate=reject_rate,
            accepted_shares=accepted,
            rejected_shares=rejected,
            is_online=False,
        )

    health = data.get("health") or {}
    flags = health.get("flags") or {}
    anomaly = data.get("anomaly") or {}
    score = health.get("score")
    health_score = int(score) if score is not None else None

    issues = _member_issues(flags, anomaly)
    has_warning = bool(flags.get("temperature_warning"))

    if health_score is None or (health.get("data_coverage") or 0) <= 0:
        status = "unknown"
    elif issues:
        status = "problem"
    elif has_warning:
        status = "warning"
        issues = ["temperature_warning"]
    else:
        status = "healthy"

    return MinerMemberSnapshot(
        name=name,
        ip=ip,
        status=status,
        issues=issues,
        health_score=health_score,
        algorithm=algo_s,
        actual_hashrate_th=actual,
        expected_hashrate_th=expected,
        expected_source=source,
        max_temperature=max_temp,
        temperature_source=temp_source,
        reject_rate=reject_rate,
        accepted_shares=accepted,
        rejected_shares=rejected,
        is_online=True,
    )


def _member_issues(flags: dict[str, Any], anomaly: dict[str, Any]) -> list[str]:
    issues = [flag for flag in PROBLEM_FLAGS if flags.get(flag)]
    if anomaly.get("detected"):
        issues.append(str(anomaly.get("reason") or "anomaly"))
    return issues


def _member_name(entry: ConfigEntry) -> str:
    return entry.title or str(entry.data.get(CONF_IP) or "Miner")


def _member_ip(entry: ConfigEntry, coord) -> str:
    if coord is not None:
        ip = coord.data.get("ip")
        if ip is not None and str(ip).strip():
            return str(ip).strip()
    return str(entry.data.get(CONF_IP) or "").strip()


def _expected_hashrate(data: dict[str, Any]) -> tuple[float | None, str]:
    learned = (data.get("health") or {}).get("learned_baseline") or {}
    if learned.get("ready"):
        hr = _try_float(learned.get("hashrate_th"))
        if hr is not None and hr > 0:
            return hr, "baseline"
    ms = data.get("miner_sensors") or {}
    ideal = _try_float(ms.get("ideal_hashrate"))
    if ideal is not None and ideal > 0:
        return ideal, "ideal"
    return None, "unknown"


def _actual_hashrate(data: dict[str, Any]) -> float:
    ms = data.get("miner_sensors") or {}
    hr = _try_float(ms.get("hashrate"))
    return hr if hr is not None else 0.0


def _max_temperature(data: dict[str, Any]) -> tuple[float | None, str | None]:
    max_chip: float | None = None
    max_board: float | None = None
    for board in (data.get("board_sensors") or {}).values():
        chip = _try_float(board.get("chip_temperature"))
        if chip is not None:
            max_chip = chip if max_chip is None else max(max_chip, chip)
        board_t = _try_float(board.get("board_temperature"))
        if board_t is not None:
            max_board = board_t if max_board is None else max(max_board, board_t)
    if max_chip is not None:
        return max_chip, "chip"
    if max_board is not None:
        return max_board, "board"
    ms = data.get("miner_sensors") or {}
    miner_t = _try_float(ms.get("temperature"))
    if miner_t is not None:
        return miner_t, "miner"
    return None, None


def _reject_stats(
    data: dict[str, Any],
) -> tuple[float | None, int | None, int | None]:
    accepted = _try_int(data.get("accepted_shares"))
    rejected = _try_int(data.get("rejected_shares"))
    total = (accepted or 0) + (rejected or 0)
    if total < MIN_SHARES_FOR_REJECT:
        return None, accepted, rejected
    rate = _try_float(data.get("reject_rate"))
    return rate, accepted, rejected


def _pick_hottest(snapshots: list[MinerMemberSnapshot]) -> dict[str, Any] | None:
    candidates = [
        s
        for s in snapshots
        if s.is_online and s.max_temperature is not None
    ]
    if not candidates:
        return None
    hottest = max(candidates, key=lambda s: s.max_temperature or 0.0)
    return {
        "temperature": round(hottest.max_temperature, 1),
        "miner": hottest.name,
        "ip": hottest.ip,
        "temperature_source": hottest.temperature_source,
    }


def _pick_worst_reject(snapshots: list[MinerMemberSnapshot]) -> dict[str, Any] | None:
    candidates = [
        s
        for s in snapshots
        if s.is_online and s.reject_rate is not None
    ]
    if not candidates:
        return None
    worst = max(candidates, key=lambda s: s.reject_rate or 0.0)
    return {
        "reject_rate": round(worst.reject_rate, 2),
        "miner": worst.name,
        "accepted_shares": worst.accepted_shares,
        "rejected_shares": worst.rejected_shares,
    }


def _problem_devices(
    snapshots: list[MinerMemberSnapshot],
) -> tuple[list[dict[str, Any]], int]:
    status_rank = {"problem": 0, "warning": 1, "offline": 2}
    problems = [
        {
            "name": s.name,
            "status": s.status,
            "health_score": s.health_score,
            "issues": list(s.issues),
        }
        for s in snapshots
        if s.status in ATTENTION_STATUSES
    ]
    problems.sort(
        key=lambda item: (
            status_rank.get(str(item["status"]), 9),
            item["health_score"] is None,
            item["health_score"] or 0,
        )
    )
    truncated = max(0, len(problems) - MAX_PROBLEM_DEVICES)
    return problems[:MAX_PROBLEM_DEVICES], truncated


def _try_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _try_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
