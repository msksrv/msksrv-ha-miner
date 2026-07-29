"""Unit tests for the miner energy accounting module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from conftest import load_miner_module

definitions = load_miner_module("energy/definitions.py", "custom_components.miner.energy.definitions")
accumulator = load_miner_module("energy/accumulator.py", "custom_components.miner.energy.accumulator")
periods = load_miner_module("energy/periods.py", "custom_components.miner.energy.periods")
storage = load_miner_module("energy/storage.py", "custom_components.miner.energy.storage")
registry = load_miner_module("energy/registry.py", "custom_components.miner.energy.registry")

EnergyRecord = definitions.EnergyRecord
ResolvedEnergySource = definitions.ResolvedEnergySource
RESOLVED_PHYSICAL = definitions.RESOLVED_PHYSICAL
stitch_physical_reading = accumulator.stitch_physical_reading
period_interval_seconds = accumulator.period_interval_seconds
preserve_total_on_source_change = accumulator.preserve_total_on_source_change
integrate_period_sample = periods.integrate_period_sample
reset_periods_if_needed = periods.reset_periods_if_needed
update_nominal_power_from_telemetry = periods.update_nominal_power_from_telemetry
EnergyStore = storage.EnergyStore
physical_entity_owner = registry.physical_entity_owner

CONF_IS_FARM = "is_farm"
CONF_FARM_ENERGY_PHYSICAL_SENSOR = "farm_energy_physical_sensor"
DOMAIN = "miner"

UTC = timezone.utc
NOW = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)


def test_physical_meter_reset_stitches_large_drop() -> None:
    record = EnergyRecord(
        total_kwh=100.0,
        physical_offset_kwh=100.0,
        last_physical_raw_kwh=100.0,
    )
    stitch_physical_reading(record, 5.0)
    assert record.physical_offset_kwh == 200.0
    assert record.total_kwh == 205.0


def test_physical_meter_ignores_small_noise_drop() -> None:
    record = EnergyRecord(
        total_kwh=100.0,
        physical_offset_kwh=0.0,
        last_physical_raw_kwh=100.0,
    )
    stitch_physical_reading(record, 99.99)
    assert record.physical_offset_kwh == 0.0
    assert record.total_kwh == 100.0


def test_physical_meter_first_read_anchors_canonical_total() -> None:
    record = EnergyRecord(total_kwh=100.0)
    stitch_physical_reading(record, 5000.0)
    assert record.physical_offset_kwh == -4900.0
    assert record.total_kwh == 100.0


def test_period_interval_caps_long_gap() -> None:
    assert period_interval_seconds(7200.0, 10.0) == 0.0
    assert period_interval_seconds(15.0, 10.0) == 15.0


def test_offline_does_not_repeat_hash_delivery() -> None:
    record = EnergyRecord(last_hashrate_th_s=200.0, last_reference_hashrate_th_s=200.0)
    integrate_period_sample(
        record,
        now=NOW,
        delta_kwh=0.0,
        delta_cost=0.0,
        hashrate_th_s=None,
        reference_hashrate_th_s=None,
        available=False,
        dt_s=10.0,
    )
    assert record.day_hash_th == pytest.approx(1000.0)
    assert record.last_hashrate_th_s == 0.0

    integrate_period_sample(
        record,
        now=NOW + timedelta(seconds=10),
        delta_kwh=0.0,
        delta_cost=0.0,
        hashrate_th_s=None,
        reference_hashrate_th_s=None,
        available=False,
        dt_s=10.0,
    )
    assert record.day_hash_th == pytest.approx(1000.0)


def test_offline_counts_lost_hash_with_stored_reference() -> None:
    record = EnergyRecord(last_reference_hashrate_th_s=150.0, last_hashrate_th_s=150.0)
    integrate_period_sample(
        record,
        now=NOW,
        delta_kwh=0.0,
        delta_cost=0.0,
        hashrate_th_s=None,
        reference_hashrate_th_s=None,
        available=False,
        dt_s=60.0,
    )
    assert record.day_lost_hash_th == pytest.approx(9000.0)


def test_long_gap_still_records_energy_without_hash_period() -> None:
    record = EnergyRecord(last_hashrate_th_s=200.0, last_reference_hashrate_th_s=200.0)
    integrate_period_sample(
        record,
        now=NOW,
        delta_kwh=3.5,
        delta_cost=1.2,
        hashrate_th_s=200.0,
        reference_hashrate_th_s=200.0,
        available=True,
        dt_s=0.0,
    )
    assert record.day_kwh == pytest.approx(3.5)
    assert record.day_cost == pytest.approx(1.2)
    assert record.day_hash_th == 0.0
    assert record.day_lost_hash_th == 0.0


def test_source_switch_preserves_total_and_reanchors_physical() -> None:
    record = EnergyRecord(
        total_kwh=42.0,
        active_source="switch_power",
        active_entity_id="sensor.rig_power",
        last_ts=NOW.isoformat(),
        last_power_w=900.0,
    )
    new_source = ResolvedEnergySource(RESOLVED_PHYSICAL, "sensor.rig_energy", False)
    preserve_total_on_source_change(record, new_source, NOW + timedelta(minutes=1))
    assert record.total_kwh == 42.0
    assert record.last_physical_raw_kwh is None
    stitch_physical_reading(record, 10.0)
    assert record.total_kwh == 42.0


def test_v2_store_dict_loads_new_optional_fields() -> None:
    record = EnergyRecord.from_dict({"total_kwh": 12.5, "day_kwh": 1.0})
    assert record.total_kwh == 12.5
    assert record.member_last_totals == {}
    assert record.last_reference_hashrate_th_s is None
    assert record.day_integrated_seconds == 0.0


@pytest.mark.asyncio
async def test_energy_store_migrates_v2_data() -> None:
    store = EnergyStore.__new__(EnergyStore)
    payload = {"total_kwh": 77.0, "day_kwh": 2.0}
    migrated = await store._async_migrate_func(2, 1, payload)
    assert migrated == payload


@pytest.mark.asyncio
async def test_energy_store_accepts_v3_data() -> None:
    store = EnergyStore.__new__(EnergyStore)
    payload = {"total_kwh": 88.0, "member_last_totals": {"abc": 1.0}}
    migrated = await store._async_migrate_func(3, 1, payload)
    assert migrated == payload


def test_farm_excludes_own_pdu_from_conflict() -> None:
    farm_entry_id = "farm-entry-1"
    pdu = "sensor.farm_pdu_energy"
    entry = SimpleNamespace(
        entry_id=farm_entry_id,
        data={CONF_IS_FARM: True},
        options={CONF_FARM_ENERGY_PHYSICAL_SENSOR: pdu},
    )
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = [entry]
    hass.data = {DOMAIN: {"energy_physical_registry": {}}}

    owner = physical_entity_owner(
        hass, pdu, exclude_entry_id=f"farm_{farm_entry_id}"
    )
    assert owner is None


def test_prune_removed_farm_members_before_delta_sum() -> None:
    member_last_totals = {"active": 10.0, "removed": 5000.0}
    active_ids = {"active"}
    for entry_id in set(member_last_totals) - active_ids:
        del member_last_totals[entry_id]

    current = 12.0
    prev = member_last_totals.get("active")
    delta = max(current - prev, 0.0)
    member_last_totals["active"] = current
    assert delta == pytest.approx(2.0)
    assert "removed" not in member_last_totals


def test_nominal_power_updates_only_near_reference() -> None:
    record = EnergyRecord(last_reference_hashrate_th_s=100.0)
    update_nominal_power_from_telemetry(
        record,
        {"miner_sensors": {"miner_consumption": 900.0, "hashrate": 80.0}},
        reference_hashrate_th_s=100.0,
    )
    assert record.last_nominal_power_w == 900.0

    record.last_nominal_power_w = 3200.0
    update_nominal_power_from_telemetry(
        record,
        {"miner_sensors": {"miner_consumption": 900.0, "hashrate": 50.0}},
        reference_hashrate_th_s=100.0,
    )
    assert record.last_nominal_power_w == 3200.0


def test_calendar_reset_clears_day_quality_without_sample() -> None:
    record = EnergyRecord(
        day_key="2026-03-14",
        day_kwh=5.0,
        day_integrated_seconds=100.0,
        day_expected_seconds=200.0,
    )
    reset_periods_if_needed(record, NOW)
    assert record.day_kwh == 0.0
    assert record.day_integrated_seconds == 0.0
    assert record.day_expected_seconds == 0.0
