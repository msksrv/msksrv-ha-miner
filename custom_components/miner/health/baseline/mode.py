"""Derive baseline profile key from coordinator poll data."""

from __future__ import annotations

import pyasic
from pyasic.config.mining import MiningModeHPM, MiningModeLPM, MiningModeNormal


def baseline_mode_key(data: dict) -> str:
    """Unique key per power/preset mode (separate baselines per mode)."""
    ms = data.get("miner_sensors") or {}
    preset = (ms.get("active_preset_name") or "default").strip()
    config = data.get("config")
    tri = _power_mode_tri_state(config)
    if tri:
        return f"{preset}|{tri}"
    return preset


def _power_mode_tri_state(config: pyasic.MinerConfig | dict | None) -> str | None:
    if config is None or not isinstance(config, pyasic.MinerConfig):
        return None
    mm = getattr(config, "mining_mode", None)
    if isinstance(mm, MiningModeNormal):
        return "Normal"
    if isinstance(mm, MiningModeLPM):
        return "Low"
    if isinstance(mm, MiningModeHPM):
        return "High"
    return None
