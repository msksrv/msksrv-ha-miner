"""Repair issue types, stable IDs, and timing constants."""

from __future__ import annotations

from dataclasses import dataclass

MINER_ISSUE_PREFIX = "miner"
FARM_ISSUE_PREFIX = "farm"

# Seconds the condition must hold before creating a repair.
CONFIRM_SECONDS: dict[str, float] = {
    "hashboard": 300,
    "hashrate": 0,
    "temperature": 180,
    "fan": 180,
    "offline": 600,
    "pool": 300,
    "recovery": 0,
    "reject": 300,
    "power": 300,
}

RECOVERY_SECONDS = 240
FARM_OFFLINE_MAX_NAMES = 3

HASHRATE_ANOMALY_REASONS = frozenset(
    {"hashrate_power_mismatch", "hashrate_efficiency_drop"}
)
BOARD_ANOMALY_REASONS = frozenset(
    {"board_hashrate_outlier", "board_temp_outlier"}
)
FAN_ANOMALY_REASONS = frozenset({"fan_imbalance"})
RECOVERY_ANOMALY_REASONS = frozenset({"post_reboot_slow_recovery"})
REJECT_ANOMALY_REASONS = frozenset({"reject_rate_high"})
POOL_ANOMALY_REASONS = frozenset({"share_stale"})

LEARN_MORE_URL = (
    "https://github.com/msksrv/msksrv-ha-miner/blob/beta/README.md"
)


class RepairType:
    HASHBOARD = "hashboard"
    HASHRATE = "hashrate"
    TEMPERATURE = "temperature"
    FAN = "fan"
    OFFLINE = "offline"
    POOL = "pool"
    RECOVERY = "recovery"
    RECOVERY_FAILED = "recovery_failed"
    POWER_RESTORE_FAILED = "power_restore_failed"
    REJECT = "reject"
    POWER = "power"


class FarmRepairType:
    OFFLINE = "offline"


@dataclass(frozen=True)
class RepairDefinition:
    repair_type: str
    translation_key: str
    confirm_seconds: float


REPAIR_DEFINITIONS: dict[str, RepairDefinition] = {
    RepairType.HASHBOARD: RepairDefinition(
        RepairType.HASHBOARD, "miner_hashboard_chips", CONFIRM_SECONDS["hashboard"]
    ),
    RepairType.HASHRATE: RepairDefinition(
        RepairType.HASHRATE, "miner_hashrate", CONFIRM_SECONDS["hashrate"]
    ),
    RepairType.TEMPERATURE: RepairDefinition(
        RepairType.TEMPERATURE, "miner_temperature", CONFIRM_SECONDS["temperature"]
    ),
    RepairType.FAN: RepairDefinition(
        RepairType.FAN, "miner_fan", CONFIRM_SECONDS["fan"]
    ),
    RepairType.OFFLINE: RepairDefinition(
        RepairType.OFFLINE, "miner_offline", CONFIRM_SECONDS["offline"]
    ),
    RepairType.POOL: RepairDefinition(
        RepairType.POOL, "miner_pool", CONFIRM_SECONDS["pool"]
    ),
    RepairType.RECOVERY: RepairDefinition(
        RepairType.RECOVERY, "miner_recovery", CONFIRM_SECONDS["recovery"]
    ),
    RepairType.RECOVERY_FAILED: RepairDefinition(
        RepairType.RECOVERY_FAILED,
        "miner_recovery_failed",
        CONFIRM_SECONDS["recovery"],
    ),
    RepairType.POWER_RESTORE_FAILED: RepairDefinition(
        RepairType.POWER_RESTORE_FAILED,
        "miner_power_restore_failed",
        CONFIRM_SECONDS["recovery"],
    ),
    RepairType.REJECT: RepairDefinition(
        RepairType.REJECT, "miner_reject", CONFIRM_SECONDS["reject"]
    ),
    RepairType.POWER: RepairDefinition(
        RepairType.POWER, "miner_power", CONFIRM_SECONDS["power"]
    ),
}

FARM_REPAIR_DEFINITIONS: dict[str, RepairDefinition] = {
    FarmRepairType.OFFLINE: RepairDefinition(
        FarmRepairType.OFFLINE, "farm_offline", CONFIRM_SECONDS["offline"]
    ),
}

MINER_REPAIR_TYPES: tuple[str, ...] = (
    RepairType.HASHBOARD,
    RepairType.HASHRATE,
    RepairType.TEMPERATURE,
    RepairType.FAN,
    RepairType.OFFLINE,
    RepairType.POOL,
    RepairType.RECOVERY,
    RepairType.REJECT,
    RepairType.POWER,
)

MINER_MANUAL_REPAIR_TYPES: tuple[str, ...] = (
    RepairType.RECOVERY_FAILED,
    RepairType.POWER_RESTORE_FAILED,
)

ALL_MINER_REPAIR_TYPES: tuple[str, ...] = MINER_REPAIR_TYPES + MINER_MANUAL_REPAIR_TYPES

FARM_REPAIR_TYPES: tuple[str, ...] = (FarmRepairType.OFFLINE,)


def miner_issue_id(entry_id: str, repair_type: str) -> str:
    return f"{MINER_ISSUE_PREFIX}_{entry_id}_{repair_type}"


def farm_issue_id(entry_id: str, repair_type: str) -> str:
    return f"{FARM_ISSUE_PREFIX}_{entry_id}_{repair_type}"


def parse_issue_id(issue_id_str: str) -> tuple[str, str, str] | None:
    """Return (scope, entry_id, repair_type) where scope is miner|farm."""
    if issue_id_str.startswith(f"{MINER_ISSUE_PREFIX}_"):
        scope = "miner"
        types = ALL_MINER_REPAIR_TYPES
        prefix_len = len(MINER_ISSUE_PREFIX) + 1
    elif issue_id_str.startswith(f"{FARM_ISSUE_PREFIX}_"):
        scope = "farm"
        types = FARM_REPAIR_TYPES
        prefix_len = len(FARM_ISSUE_PREFIX) + 1
    else:
        return None
    for rtype in types:
        suffix = f"_{rtype}"
        if issue_id_str.endswith(suffix):
            entry_id = issue_id_str[prefix_len : -len(suffix)]
            if entry_id:
                return scope, entry_id, rtype
    return None


# Backward-compatible alias used by phase-1 code paths.
def issue_id(entry_id: str, repair_type: str) -> str:
    return miner_issue_id(entry_id, repair_type)
