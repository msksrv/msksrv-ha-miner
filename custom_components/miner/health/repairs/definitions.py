"""Repair issue types, stable IDs, and timing constants."""

from __future__ import annotations

from dataclasses import dataclass

DOMAIN_ISSUE_PREFIX = "miner"

# Seconds the condition must hold before creating a repair.
CONFIRM_SECONDS: dict[str, float] = {
    "hashboard": 300,
    "hashrate": 0,  # anomaly detector already enforces rule duration
    "temperature": 180,
    "fan": 180,
}

# Zero-RPM fan faults confirm faster than imbalance (from baseline rules).
CONFIRM_FAN_IMBALANCE_SECONDS = 300

# Stable normalization before clearing an issue.
RECOVERY_SECONDS = 240

HASHRATE_ANOMALY_REASONS = frozenset(
    {"hashrate_power_mismatch", "hashrate_efficiency_drop"}
)
BOARD_ANOMALY_REASONS = frozenset(
    {"board_hashrate_outlier", "board_temp_outlier"}
)
FAN_ANOMALY_REASONS = frozenset({"fan_imbalance"})

LEARN_MORE_URL = (
    "https://github.com/msksrv/msksrv-ha-miner/blob/beta/README.md"
)


class RepairType:
    """Stable repair type suffixes for issue ids."""

    HASHBOARD = "hashboard"
    HASHRATE = "hashrate"
    TEMPERATURE = "temperature"
    FAN = "fan"


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
}


PHASE1_REPAIR_TYPES: tuple[str, ...] = (
    RepairType.HASHBOARD,
    RepairType.HASHRATE,
    RepairType.TEMPERATURE,
    RepairType.FAN,
)


def issue_id(entry_id: str, repair_type: str) -> str:
    """Stable issue id: miner_<entry_id>_<type>."""
    return f"{DOMAIN_ISSUE_PREFIX}_{entry_id}_{repair_type}"


def parse_issue_id(issue_id_str: str) -> tuple[str, str] | None:
    """Return (entry_id, repair_type) or None."""
    if not issue_id_str.startswith(f"{DOMAIN_ISSUE_PREFIX}_"):
        return None
    for rtype in PHASE1_REPAIR_TYPES:
        suffix = f"_{rtype}"
        if issue_id_str.endswith(suffix):
            entry_id = issue_id_str[len(DOMAIN_ISSUE_PREFIX) + 1 : -len(suffix)]
            if entry_id:
                return entry_id, rtype
    return None
