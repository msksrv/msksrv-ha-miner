"""Farm health aggregation with offline / empty coordinator data."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from conftest import load_miner_module

load_miner_module("const.py", "custom_components.miner.const")
farm_health = load_miner_module("farm_health.py", "custom_components.miner.farm_health")


def _entry(title: str = "miner-1", ip: str = "192.168.1.10") -> MagicMock:
    entry = MagicMock()
    entry.title = title
    entry.data = {"ip": ip}
    return entry


def _coord(*, data=None, last_update_success: bool = False) -> SimpleNamespace:
    return SimpleNamespace(data=data, last_update_success=last_update_success)


def test_member_ip_when_coord_data_is_none():
    entry = _entry()
    coord = _coord(data=None, last_update_success=False)
    assert farm_health._member_ip(entry, coord) == "192.168.1.10"


def test_compute_farm_health_offline_miner_with_none_data():
    entry = _entry()
    coord = _coord(data=None, last_update_success=False)
    metrics = farm_health.compute_farm_health_metrics([(entry, coord)])

    assert metrics["expected_miners"] == 1
    assert metrics["health_status_counts"]["offline"] == 1
    assert metrics["health_status_counts"]["healthy"] == 0
    assert metrics["health_problem_devices"][0]["status"] == "offline"
    assert metrics["health_problem_devices"][0]["issues"] == ["offline"]
