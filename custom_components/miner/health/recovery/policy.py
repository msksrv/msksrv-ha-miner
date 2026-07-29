"""Recovery eligibility checks and blocking conditions."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ...const import CONF_AUTO_RECOVERY_ENABLED, CONF_POWER_SWITCH
from ...events.definitions import pool_signature, work_mode_signature
from ...health.profiles import resolve_health_thresholds
from ...health.repairs.manager import RepairManager
from .definitions import (
    CONFIG_BLOCK_SECONDS,
    MANUAL_ACTION_COOLDOWN_SECONDS,
    RECOVERY_REASON_HASHRATE_LOW,
    RecoveryRecord,
    RecoveryState,
    recovery_settings,
)

if TYPE_CHECKING:
    from ...coordinator import MinerCoordinator


def _now() -> datetime:
    return dt_util.utcnow()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return dt_util.parse_datetime(value)


def _after(iso: str | None) -> bool:
    target = _parse_iso(iso)
    if target is None:
        return True
    return _now() >= target


def hashrate_metrics(
    coordinator: MinerCoordinator, data: dict[str, Any]
) -> tuple[float | None, float | None, float | None, bool]:
    """Return current, expected, threshold hashrates and low flag."""
    ms = data.get("miner_sensors") or {}
    current = _f(ms.get("hashrate"))
    health = data.get("health") or {}
    learned = health.get("learned_baseline") or {}
    baseline_medians = coordinator.baseline.baseline_medians(data)
    reference = None
    if health.get("hashrate_reference") == "baseline" and baseline_medians.get("hashrate"):
        reference = _f(baseline_medians.get("hashrate"))
    if reference is None:
        reference = _f(ms.get("ideal_hashrate"))
    thresholds, _profile = resolve_health_thresholds(
        data.get("make"),
        data.get("model"),
        coordinator.config_entry.options,
    )
    threshold = None
    low = False
    if reference is not None and reference > 0 and current is not None:
        threshold = reference * thresholds.hashrate_low_ratio
        low = current < threshold
    flags = health.get("flags") or {}
    if flags.get("hashrate_low"):
        low = True
    return current, reference, threshold, low


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def has_baseline_or_ideal(
    coordinator: MinerCoordinator, data: dict[str, Any]
) -> bool:
    _current, expected, _threshold, _low = hashrate_metrics(coordinator, data)
    if expected is not None and expected > 0:
        return True
    learned = (data.get("health") or {}).get("learned_baseline") or {}
    return bool(learned.get("ready"))


def blocking_fault_active(
    data: dict[str, Any], anomaly: Any, *, ignore_mining_off: bool = False
) -> str | None:
    """Return a blocking reason when auto reboot would be unsafe."""
    if not ignore_mining_off and not data.get("is_mining"):
        return "mining_off"
    flags = (data.get("health") or {}).get("flags") or {}
    if flags.get("temperature_high"):
        return "temperature_high"
    if flags.get("maintenance_required"):
        return "maintenance_required"
    if flags.get("fan_problem"):
        return "fan_problem"
    if flags.get("board_problem"):
        return "board_problem"
    if flags.get("power_anomaly"):
        return "power_anomaly"
    if flags.get("pool_problem") or flags.get("share_stale"):
        return "pool_problem"
    if RepairManager._hashboard_raw(data, anomaly):
        return "board_problem"
    if RepairManager._fan_zero_rpm(data):
        return "fan_problem"
    return None


def in_cooldown(record: RecoveryRecord) -> bool:
    if record.state == RecoveryState.LOCKED and record.locked_reason:
        if record.cooldown_until and not _after(record.cooldown_until):
            return True
    if record.cooldown_until and not _after(record.cooldown_until):
        return True
    return False


def in_config_block(record: RecoveryRecord) -> bool:
    return bool(record.config_block_until and not _after(record.config_block_until))


def user_reboot_recent(coordinator: MinerCoordinator) -> bool:
    return coordinator.baseline.reboot_recently()


def pool_or_mode_changing(
    coordinator: MinerCoordinator,
    data: dict[str, Any],
    *,
    last_pool: tuple | None,
    last_mode: str | None,
) -> bool:
    events = coordinator.events
    pool = pool_signature(data)
    mode = work_mode_signature(data)
    if last_pool is not None and pool != last_pool:
        return True
    if last_mode is not None and mode and mode != last_mode:
        return True
    if events._pool_candidate is not None and events._pool_stable_count < 2:
        return True
    if events._work_mode_candidate is not None and events._work_mode_stable_count < 2:
        return True
    return False


def can_start_recovery(
    coordinator: MinerCoordinator,
    data: dict[str, Any],
    anomaly: Any,
    record: RecoveryRecord,
    *,
    available: bool,
    farm_slot: bool,
) -> tuple[bool, str | None]:
    """Check whether a new recovery cycle may begin."""
    settings = recovery_settings(coordinator.config_entry.options)
    if not settings.get(CONF_AUTO_RECOVERY_ENABLED):
        return False, "disabled"
    if not available:
        return False, "offline"
    if not farm_slot:
        return False, "farm_busy"
    if record.state not in (RecoveryState.IDLE,):
        return False, "active"
    if record.emergency_stop_latched:
        return False, "emergency_stop"
    if in_cooldown(record):
        return False, "cooldown"
    if in_config_block(record):
        return False, "config_change"
    if user_reboot_recent(coordinator):
        return False, "recent_reboot"
    block = blocking_fault_active(data, anomaly)
    if block:
        return False, block
    if not has_baseline_or_ideal(coordinator, data):
        return False, "no_reference"
    _current, _expected, _threshold, low = hashrate_metrics(coordinator, data)
    if not low:
        return False, "hashrate_ok"
    return True, None


def should_continue_recovery(
    coordinator: MinerCoordinator,
    data: dict[str, Any],
    anomaly: Any,
    record: RecoveryRecord,
    *,
    available: bool,
) -> tuple[bool, str | None]:
    """Check whether an in-flight recovery should proceed."""
    state = record.state
    from .definitions import OFFLINE_TOLERANT_STATES

    if state in OFFLINE_TOLERANT_STATES:
        from .definitions import POWER_CRITICAL_STATES

        if (
            state not in POWER_CRITICAL_STATES
            and in_config_block(record)
        ):
            return False, "config_change"
        if available and data:
            block = blocking_fault_active(data, anomaly, ignore_mining_off=True)
            if block and block != "mining_off":
                return False, block
        return True, None

    if not available:
        return False, "offline"
    block = blocking_fault_active(data, anomaly)
    if block:
        return False, block
    if in_config_block(record):
        return False, "config_change"
    return True, None


def hashrate_recovered(
    coordinator: MinerCoordinator, data: dict[str, Any]
) -> bool:
    current, expected, threshold, low = hashrate_metrics(coordinator, data)
    return (
        current is not None
        and expected is not None
        and threshold is not None
        and not low
    )


def power_switch_entity_id(coordinator: MinerCoordinator) -> str | None:
    raw = coordinator.config_entry.options.get(CONF_POWER_SWITCH)
    return str(raw).strip() if raw else None


def apply_config_block(
    record: RecoveryRecord,
    seconds: float = CONFIG_BLOCK_SECONDS,
    *,
    storage: Any | None = None,
) -> None:
    record.config_block_until = (_now() + timedelta(seconds=seconds)).isoformat()
    if storage is not None:
        storage._dirty = True


def apply_cooldown(record: RecoveryRecord, seconds: float) -> None:
    record.cooldown_until = (_now() + timedelta(seconds=seconds)).isoformat()


def apply_manual_cooldown(record: RecoveryRecord) -> None:
    apply_cooldown(record, MANUAL_ACTION_COOLDOWN_SECONDS)


def new_attempt_id() -> str:
    import uuid

    return uuid.uuid4().hex[:12]


def event_context(
    coordinator: MinerCoordinator,
    data: dict[str, Any],
    record: RecoveryRecord,
) -> dict[str, Any]:
    if data:
        current, expected, threshold, _low = hashrate_metrics(coordinator, data)
    else:
        current = record.pre_action_hashrate
        expected = record.expected_hashrate
        threshold = record.threshold_hashrate
    ctx: dict[str, Any] = {
        "reason": record.reason or RECOVERY_REASON_HASHRATE_LOW,
        "attempt": max(record.reboot_attempts, record.power_cycle_attempts, 1),
    }
    if current is not None:
        ctx["hashrate_before"] = round(current, 2)
    if expected is not None:
        ctx["expected_hashrate"] = round(expected, 2)
    if threshold is not None:
        ctx["threshold"] = round(threshold, 2)
    if record.cooldown_until:
        ctx["cooldown_until"] = record.cooldown_until
    if record.attempt_id:
        ctx["attempt_id"] = record.attempt_id
    return ctx


def action_event_context(
    coordinator: MinerCoordinator,
    data: dict[str, Any],
    record: RecoveryRecord,
    *,
    reboot_attempt: int | None = None,
    power_cycle_attempt: int | None = None,
) -> dict[str, Any]:
    """Build event payload with the upcoming action attempt number."""
    ctx = event_context(coordinator, data, record)
    if reboot_attempt is not None:
        ctx["attempt"] = reboot_attempt
    elif power_cycle_attempt is not None:
        ctx["attempt"] = power_cycle_attempt
    return ctx


def switch_is_on(hass: HomeAssistant, entity_id: str | None) -> bool:
    if not entity_id:
        return False
    state = hass.states.get(entity_id)
    return state is not None and state.state == "on"
