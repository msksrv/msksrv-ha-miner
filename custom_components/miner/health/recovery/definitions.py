"""Recovery FSM states, defaults, and persisted record shape."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...const import (
    CONF_AUTO_RECOVERY_COOLDOWN_SECONDS,
    CONF_AUTO_RECOVERY_ENABLED,
    CONF_AUTO_RECOVERY_MAX_POWER_CYCLES,
    CONF_AUTO_RECOVERY_MAX_REBOOTS,
    CONF_AUTO_RECOVERY_POST_POWER_ON_SECONDS,
    CONF_AUTO_RECOVERY_POST_REBOOT_SECONDS,
    CONF_AUTO_RECOVERY_POWER_CYCLE_ENABLED,
    CONF_AUTO_RECOVERY_POWER_OFF_PAUSE_SECONDS,
    CONF_AUTO_RECOVERY_PRE_ACTION_SECONDS,
    CONF_AUTO_RECOVERY_CONFIG_BLOCK_SECONDS,
)

STORAGE_VERSION = 1

RECOVERY_REASON_HASHRATE_LOW = "hashrate_low"

CONFIG_BLOCK_SECONDS = 1800
MANUAL_ACTION_COOLDOWN_SECONDS = 3600
EMERGENCY_STOP_COOLDOWN_SECONDS = 86400


class RecoveryState:
    IDLE = "idle"
    ARMING = "arming"
    WAITING_REBOOT = "waiting_reboot"
    POWER_OFF_WAIT = "power_off_wait"
    POWER_ON_PENDING = "power_on_pending"
    WAITING_POWER_RECOVERY = "waiting_power_recovery"
    LOCKED = "locked"


# States where miner/API offline is expected during reboot or power cycle.
OFFLINE_TOLERANT_STATES = frozenset(
    {
        RecoveryState.WAITING_REBOOT,
        RecoveryState.POWER_OFF_WAIT,
        RecoveryState.POWER_ON_PENDING,
        RecoveryState.WAITING_POWER_RECOVERY,
    }
)

# Must finish power restoration even if config changes mid-cycle.
POWER_CRITICAL_STATES = frozenset(
    {
        RecoveryState.POWER_OFF_WAIT,
        RecoveryState.POWER_ON_PENDING,
    }
)

MAX_POWER_ON_RETRIES = 5
POWER_ON_RETRY_SECONDS = 30
REBOOT_RETRY_SECONDS = 60


class LockReason:
    MAX_ATTEMPTS = "max_attempts"
    POWER_RESTORE = "power_restore_failed"
    COOLDOWN = "cooldown"
    DISABLED = "disabled"


DEFAULTS: dict[str, Any] = {
    CONF_AUTO_RECOVERY_ENABLED: False,
    CONF_AUTO_RECOVERY_PRE_ACTION_SECONDS: 600,
    CONF_AUTO_RECOVERY_POST_REBOOT_SECONDS: 900,
    CONF_AUTO_RECOVERY_POST_POWER_ON_SECONDS: 900,
    CONF_AUTO_RECOVERY_POWER_CYCLE_ENABLED: False,
    CONF_AUTO_RECOVERY_POWER_OFF_PAUSE_SECONDS: 25,
    CONF_AUTO_RECOVERY_MAX_REBOOTS: 1,
    CONF_AUTO_RECOVERY_MAX_POWER_CYCLES: 1,
    CONF_AUTO_RECOVERY_COOLDOWN_SECONDS: 21600,
    CONF_AUTO_RECOVERY_CONFIG_BLOCK_SECONDS: CONFIG_BLOCK_SECONDS,
}


@dataclass
class RecoveryRecord:
    """Persisted recovery state for one miner."""

    state: str = RecoveryState.IDLE
    reason: str | None = None
    attempt_id: str | None = None
    reboot_attempts: int = 0
    power_cycle_attempts: int = 0
    started_at: str | None = None
    last_action_at: str | None = None
    cooldown_until: str | None = None
    locked_reason: str | None = None
    pre_action_hashrate: float | None = None
    wait_until: str | None = None
    config_block_until: str | None = None
    expected_hashrate: float | None = None
    threshold_hashrate: float | None = None
    power_on_retries: int = 0
    emergency_stop_latched: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "reason": self.reason,
            "attempt_id": self.attempt_id,
            "reboot_attempts": self.reboot_attempts,
            "power_cycle_attempts": self.power_cycle_attempts,
            "started_at": self.started_at,
            "last_action_at": self.last_action_at,
            "cooldown_until": self.cooldown_until,
            "locked_reason": self.locked_reason,
            "pre_action_hashrate": self.pre_action_hashrate,
            "wait_until": self.wait_until,
            "config_block_until": self.config_block_until,
            "expected_hashrate": self.expected_hashrate,
            "threshold_hashrate": self.threshold_hashrate,
            "power_on_retries": self.power_on_retries,
            "emergency_stop_latched": self.emergency_stop_latched,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> RecoveryRecord:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            state=str(raw.get("state") or RecoveryState.IDLE),
            reason=raw.get("reason"),
            attempt_id=raw.get("attempt_id"),
            reboot_attempts=int(raw.get("reboot_attempts") or 0),
            power_cycle_attempts=int(raw.get("power_cycle_attempts") or 0),
            started_at=raw.get("started_at"),
            last_action_at=raw.get("last_action_at"),
            cooldown_until=raw.get("cooldown_until"),
            locked_reason=raw.get("locked_reason"),
            pre_action_hashrate=_f(raw.get("pre_action_hashrate")),
            wait_until=raw.get("wait_until"),
            config_block_until=raw.get("config_block_until"),
            expected_hashrate=_f(raw.get("expected_hashrate")),
            threshold_hashrate=_f(raw.get("threshold_hashrate")),
            power_on_retries=int(raw.get("power_on_retries") or 0),
            emergency_stop_latched=bool(raw.get("emergency_stop_latched")),
        )


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def recovery_settings(options: dict[str, Any]) -> dict[str, Any]:
    """Resolved per-miner auto-recovery settings."""
    out = dict(DEFAULTS)
    for key in DEFAULTS:
        if key in options:
            out[key] = options[key]
    out[CONF_AUTO_RECOVERY_ENABLED] = bool(out.get(CONF_AUTO_RECOVERY_ENABLED))
    out[CONF_AUTO_RECOVERY_POWER_CYCLE_ENABLED] = bool(
        out.get(CONF_AUTO_RECOVERY_POWER_CYCLE_ENABLED)
    )
    for key in (
        CONF_AUTO_RECOVERY_PRE_ACTION_SECONDS,
        CONF_AUTO_RECOVERY_POST_REBOOT_SECONDS,
        CONF_AUTO_RECOVERY_POST_POWER_ON_SECONDS,
        CONF_AUTO_RECOVERY_POWER_OFF_PAUSE_SECONDS,
        CONF_AUTO_RECOVERY_MAX_REBOOTS,
        CONF_AUTO_RECOVERY_MAX_POWER_CYCLES,
        CONF_AUTO_RECOVERY_COOLDOWN_SECONDS,
        CONF_AUTO_RECOVERY_CONFIG_BLOCK_SECONDS,
    ):
        try:
            out[key] = float(out[key])
        except (TypeError, ValueError):
            out[key] = float(DEFAULTS[key])
    out[CONF_AUTO_RECOVERY_MAX_REBOOTS] = int(out[CONF_AUTO_RECOVERY_MAX_REBOOTS])
    out[CONF_AUTO_RECOVERY_MAX_POWER_CYCLES] = int(out[CONF_AUTO_RECOVERY_MAX_POWER_CYCLES])
    return out
