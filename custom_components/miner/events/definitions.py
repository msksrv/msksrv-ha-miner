"""Event type constants and problem payload helpers."""

from __future__ import annotations

from typing import Any

MINER_EVENT_TYPES = [
    "offline",
    "online",
    "problem_detected",
    "problem_cleared",
    "problem_acknowledged",
    "pool_changed",
    "work_mode_changed",
    "reboot_command_sent",
    "recovery_reboot_command_sent",
    "ip_changed",
    "recovery_started",
    "recovery_cancelled",
    "reboot_recovery_succeeded",
    "reboot_recovery_failed",
    "power_cycle_started",
    "power_off_command_sent",
    "power_on_command_sent",
    "power_cycle_succeeded",
    "power_cycle_failed",
    "recovery_locked",
    "recovery_manually_reset",
]

FARM_EVENT_TYPES = [
    "emergency_power_off",
    "emergency_power_off_partial_failure",
    "emergency_power_off_failed",
    "emergency_stop_cleared",
    "preset_applied",
    "preset_partial_failure",
    "preset_failed",
]

PROBLEM_TYPES = frozenset(
    {
        "hashboard",
        "hashrate",
        "temperature",
        "fan",
        "pool",
        "reject",
        "power",
        "recovery",
        "recovery_failed",
        "power_restore_failed",
    }
)

SECRET_EVENT_KEYS = frozenset(
    {
        "password",
        "pool_password",
        "rpc_password",
        "web_password",
        "ssh_password",
    }
)

OFFLINE_FAILURE_THRESHOLD = 3
STABLE_READINGS_REQUIRED = 2


def sanitize_event_data(data: dict[str, Any]) -> dict[str, Any]:
    """Remove secret-like keys from event payloads."""
    return {
        key: value
        for key, value in data.items()
        if key not in SECRET_EVENT_KEYS and value is not None
    }


def pool_signature(data: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Stable pool identity without secrets."""
    return (
        data.get("pool_host"),
        str(data.get("pool_port")) if data.get("pool_port") is not None else None,
        data.get("pool_worker"),
    )


def work_mode_signature(data: dict[str, Any]) -> str | None:
    """Stable work-mode label for change detection."""
    ms = data.get("miner_sensors") or {}
    preset = ms.get("active_preset_name")
    if preset is not None and str(preset).strip():
        return str(preset).strip()
    return None


def build_problem_payload(
    problem_type: str,
    data: dict[str, Any],
    anomaly: Any,
) -> dict[str, Any]:
    """Build problem_detected event data from repair context."""
    from ..health.repairs.definitions import (
        BOARD_ANOMALY_REASONS,
        FAN_ANOMALY_REASONS,
        HASHRATE_ANOMALY_REASONS,
        POOL_ANOMALY_REASONS,
        RECOVERY_ANOMALY_REASONS,
        REJECT_ANOMALY_REASONS,
        RepairType,
    )

    repair_anomaly_reasons: dict[str, frozenset[str]] = {
        RepairType.HASHBOARD: BOARD_ANOMALY_REASONS,
        RepairType.HASHRATE: HASHRATE_ANOMALY_REASONS,
        RepairType.FAN: FAN_ANOMALY_REASONS,
        RepairType.REJECT: REJECT_ANOMALY_REASONS,
        RepairType.POOL: POOL_ANOMALY_REASONS,
        RepairType.RECOVERY: RECOVERY_ANOMALY_REASONS,
        "recovery_failed": HASHRATE_ANOMALY_REASONS,
    }
    repair_health_flags: dict[str, tuple[str, ...]] = {
        RepairType.TEMPERATURE: ("temperature_high",),
        RepairType.POWER: ("power_anomaly",),
        RepairType.HASHRATE: ("hashrate_low",),
        RepairType.HASHBOARD: ("board_problem",),
        RepairType.FAN: ("fan_problem",),
        RepairType.POOL: ("pool_problem",),
        RepairType.REJECT: ("reject_rate_high",),
        "recovery_failed": ("hashrate_low",),
    }

    payload: dict[str, Any] = {
        "problem_type": problem_type,
        "severity": "error",
    }
    reason = None
    details: dict[str, Any] = {}

    allowed_reasons = repair_anomaly_reasons.get(problem_type, frozenset())
    if anomaly is not None and allowed_reasons:
        for finding in getattr(anomaly, "findings", None) or []:
            finding_reason = getattr(finding, "reason", None)
            if finding_reason and finding_reason in allowed_reasons:
                reason = str(finding_reason)
                details = dict(getattr(finding, "details", None) or {})
                finding_severity = getattr(finding, "severity", None)
                if finding_severity:
                    payload["severity"] = str(finding_severity)
                break

    if not reason and data:
        flags = (data.get("health") or {}).get("flags") or {}
        for flag in repair_health_flags.get(problem_type, ()):
            if flags.get(flag):
                reason = flag
                break

    if reason:
        payload["reason"] = reason
    for key, value in details.items():
        if key in SECRET_EVENT_KEYS or value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            payload[key] = value
        elif isinstance(value, (list, tuple)):
            payload[key] = list(value)
    return sanitize_event_data(payload)
