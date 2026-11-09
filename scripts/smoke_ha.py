"""Exercise the released miner integration using real HA Core and loopback AxeOS."""

import argparse
import asyncio
import json
import logging
import math
import shutil
from contextlib import AsyncExitStack
from datetime import timedelta
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

from aiohttp import web
from homeassistant.bootstrap import async_setup_hass
from homeassistant.components.logbook.processor import EventProcessor
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import async_list_statistic_ids
from homeassistant.components.switch import DATA_COMPONENT as SWITCH_COMPONENT
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry, entity_registry, issue_registry
from homeassistant.loader import async_get_integration
from homeassistant.runner import RuntimeConfig
from homeassistant.util import dt as dt_util

DOMAIN = "miner"
IP = "127.0.0.31"
MAC = "02:00:00:00:00:31"


class AxeOS:
    """Serve a minimal Bitaxe Gamma payload and record control requests."""

    def __init__(self, ip=IP, mac=MAC):
        self.ip = ip
        self.mac = mac
        self.runner = None
        self.polls = 0
        self.uptime = 3600
        self.commands = []

    async def start(self):
        app = web.Application()
        app.router.add_get("/", self.index)
        app.router.add_get("/api/system/info", self.info)
        app.router.add_post("/api/system/restart", self.restart)
        app.router.add_patch("/api/system", self.configure)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        await web.TCPSite(self.runner, self.ip, 80).start()

    async def stop(self):
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None

    async def index(self, _request):
        return web.Response(text="<title>AxeOS</title>", content_type="text/html")

    async def info(self, _request):
        self.polls += 1
        return web.json_response(
            {
                "ASICModel": "BM1370",
                "hostname": "bitaxe-audit",
                "macAddr": self.mac,
                "version": "v2.9.0",
                "hashRate": 1200.0,
                "power": 23.0,
                "uptimeSeconds": self.uptime,
                "temp": 50.0,
                "vrTemp": 42.0,
                "voltage": 5000.0,
                "fanrpm": 2500,
                "smallCoreCount": 1280,
                "asicCount": 1,
                "frequency": 625,
                "autofanspeed": 1,
                "fanspeed": 50,
                "stratumURL": "pool.invalid",
                "stratumPort": 3333,
                "stratumUser": "worker",
                "stratumPassword": "example",
            }
        )

    async def restart(self, _request):
        self.commands.append(("reboot", None))
        return web.json_response({})

    async def configure(self, request):
        self.commands.append(("config", await request.json()))
        return web.json_response({})


def require(test, condition, detail=""):
    if not condition:
        raise AssertionError(f"{test}: {detail}")
    print(f"PASS {test}" + (f" ({detail})" if detail else ""), flush=True)


def state_for(hass, unique_id, platform="sensor"):
    registry = entity_registry.async_get(hass)
    entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
    return hass.states.get(entity_id) if entity_id else None


async def add_miner(hass, ip):
    flow = hass.config_entries.flow
    step = await flow.async_init(DOMAIN, context={"source": "user"})
    require("user menu", step["type"] is FlowResultType.MENU, str(step["type"]))
    flow_id = step["flow_id"]
    step = await flow.async_configure(flow_id, {"next_step_id": "manual"})
    require("manual form", step.get("step_id") == "manual")
    step = await flow.async_configure(
        flow_id, {"ip": ip, "min_power": 15, "max_power": 10000}
    )
    if step.get("step_id") == "login":
        step = await flow.async_configure(
            flow_id, {"web_username": "", "web_password": ""}
        )
    require(
        "AxeOS discovery over HTTP",
        step.get("step_id") == "title",
        str(step.get("errors")),
    )
    step = await flow.async_configure(flow_id, {"title": "Audit Bitaxe"})
    require("create miner entry", step["type"] is FlowResultType.CREATE_ENTRY)
    return step["result"]


async def add_farm(hass, device_id):
    flow = hass.config_entries.flow
    step = await flow.async_init(DOMAIN, context={"source": "user"})
    flow_id = step["flow_id"]
    await flow.async_configure(flow_id, {"next_step_id": "farm"})
    step = await flow.async_configure(
        flow_id, {"title": "Audit Farm", "farm_device_ids": [device_id]}
    )
    require(
        "create farm entry",
        step["type"] is FlowResultType.CREATE_ENTRY,
        str(step.get("errors")),
    )
    return step["result"]


async def check_farm_member_picker(hass, farm, miner_device_id):
    config_flows = hass.config_entries.flow
    options_flows = hass.config_entries.options
    setup = await config_flows.async_init(DOMAIN, context={"source": "user"})
    options = await options_flows.async_init(farm.entry_id)
    try:
        for flows, menu, next_step in (
            (config_flows, setup, "farm"),
            (options_flows, options, "farm_members"),
        ):
            form = await flows.async_configure(
                menu["flow_id"], {"next_step_id": next_step}
            )
            field, selector = next(
                (field, selector)
                for field, selector in form["data_schema"].schema.items()
                if field.schema == "farm_device_ids"
            )
            config = selector.serialize()["selector"]["select"]
            require(
                f"{next_step} offers only the individual miner, excluding the farm",
                config["multiple"]
                and [option["value"] for option in config["options"]] == [miner_device_id],
            )
            if next_step == "farm_members":
                require(
                    "editing the farm keeps its saved miner selected",
                    field.description["suggested_value"] == [miner_device_id],
                )
    finally:
        config_flows.async_abort(setup["flow_id"])
        options_flows.async_abort(options["flow_id"])


async def main(source):
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    print(
        f"homeassistant={version('homeassistant')} pyasic={version('pyasic')}",
        flush=True,
    )
    async with AsyncExitStack() as stack:
        temp = TemporaryDirectory(prefix="miner-ha-test-")
        stack.push_async_callback(asyncio.to_thread, temp.cleanup)
        path = Path(temp.name)
        shutil.copytree(
            source,
            path / "custom_components" / DOMAIN,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        blueprint = Path(__file__).resolve().parents[1] / "blueprints"
        shutil.copytree(blueprint, path / "blueprints")
        (path / "configuration.yaml").write_text(
            """homeassistant:
  time_zone: Europe/Moscow
recorder:
logbook:
energy:
automation:
  - id: miner_audit_alerts
    use_blueprint:
      path: msksrv/miner_alerts.yaml
      input:
        miner_device: blueprint_test
  - id: miner_audit_monthly
    alias: Miner Audit Monthly
    use_blueprint:
      path: msksrv/farm_monthly_summary.yaml
      input:
        energy: sensor.audit_monthly_energy
        cost: sensor.audit_monthly_cost
""",
            encoding="utf-8",
        )
        axe = AxeOS()
        stack.push_async_callback(axe.stop)
        await axe.start()

        hass = await async_setup_hass(
            RuntimeConfig(config_dir=str(path), skip_pip=True)
        )
        require(
            "real Core bootstrap", hass is not None and not hass.config.recovery_mode
        )
        stack.push_async_callback(hass.async_stop)
        await hass.async_start()
        await hass.async_block_till_done()

        miner = await add_miner(hass, axe.ip)
        await hass.async_block_till_done()
        require(
            "miner loaded", miner.state is ConfigEntryState.LOADED, str(miner.state)
        )
        devices = device_registry.async_get(hass)
        (miner_device,) = device_registry.async_entries_for_config_entry(
            devices, miner.entry_id
        )
        require(
            "HA device registry and link",
            miner_device.configuration_url == f"http://{axe.ip}",
        )
        coord = hass.data[DOMAIN][miner.entry_id]
        require(
            "real telemetry",
            math.isclose(coord.data["miner_sensors"]["hashrate"], 1.2)
            and coord.data["miner_sensors"]["miner_consumption"] == 23,
            str(coord.data["miner_sensors"]),
        )

        await check_uptime(hass, axe, miner, coord)

        farm = await add_farm(hass, miner_device.id)
        await hass.async_block_till_done()
        require("farm loaded", farm.state is ConfigEntryState.LOADED, str(farm.state))
        await check_farm_member_picker(hass, farm, miner_device.id)
        farm_coord = hass.data[DOMAIN][farm.entry_id]
        require(
            "farm aggregate",
            farm_coord.data["miners_online"] == 1
            and farm_coord.data["total_hashrate_th"] == 1.2
            and farm_coord.data["total_power_w"] == 23,
        )
        require(
            "miner sensor state",
            float(state_for(hass, f"{miner.entry_id}-hashrate").state) == 1.2,
        )
        require(
            "farm sensor state",
            state_for(hass, f"farm-{farm.entry_id}-miners_online").state == "1",
        )

        opts_flow = hass.config_entries.options
        options = await opts_flow.async_init(miner.entry_id)
        require(
            "miner options flow",
            options["type"] in {FlowResultType.MENU, FlowResultType.FORM},
        )
        opts_flow.async_abort(options["flow_id"])
        options = await opts_flow.async_init(farm.entry_id)
        require(
            "farm options flow",
            options["type"] in {FlowResultType.MENU, FlowResultType.FORM},
        )
        opts_flow.async_abort(options["flow_id"])

        events = []

        async def collect_event(event):
            events.append(event.data)

        hass.bus.async_listen("miner_event", collect_event)
        try:
            await hass.services.async_call(
                DOMAIN, "reboot", {"device_id": [miner_device.id]}, blocking=True
            )
        except Exception:
            print(
                f"HTTP commands received before HA service error: {axe.commands}",
                flush=True,
            )
            raise
        await hass.async_block_till_done()
        require("reboot service sent loopback POST", axe.commands == [("reboot", None)])
        require(
            "reboot event reached HA bus",
            any(
                event.get("type") == "reboot_command_sent"
                and event.get("device_id") == miner_device.id
                for event in events
            ),
        )

        await check_activity(hass, miner, coord, events)
        await check_energy(hass, miner, farm)
        await check_legacy_cost(hass, farm)
        await check_repair_forms(hass, miner, farm)
        await check_notification_blueprint(hass)
        await check_power_recovery(hass, axe, miner, farm, events)
        await check_offline(hass, axe, miner, farm, events, miner_device.id)
        await check_diagnostics(hass, axe, miner, farm)
        await check_dated_tariff(hass, farm)
        await check_hourly_tariff_history(hass, farm)
        await check_monthly_summary(hass)
        print(f"Completed {manifest['version']}", flush=True)


async def check_dated_tariff(hass, farm):
    from custom_components.miner.energy.tariff import (
        COST_ADJUSTMENTS,
        EFFECTIVE_DATE,
        cost_for_interval,
        current_price,
        local_midnight,
    )

    async def open_tariff(choice):
        flows = hass.config_entries.options
        menu = await flows.async_init(farm.entry_id)
        flow_id = menu["flow_id"]
        selector = await flows.async_configure(flow_id, {"next_step_id": "farm_tariff"})
        tariff_choices = next(iter(selector["data_schema"].schema.values())).config["options"]
        require(
            "tariff menu offers three tariff types plus a separate price change",
            tariff_choices == ["flat", "dual", "triple", "new_price"],
        )
        form = await flows.async_configure(flow_id, {"farm_elec_tariff_mode": choice})
        return flows, flow_id, form

    async def submit(fields, effective_date):
        flows, flow_id, form = await open_tariff("new_price")
        require(
            "price change opens directly with date and prices",
            form["step_id"] == "farm_tariff_price"
            and {str(key) for key in form["data_schema"].schema}
            == {EFFECTIVE_DATE, *fields},
        )
        result = await flows.async_configure(
            flow_id, {**fields, EFFECTIVE_DATE: effective_date}
        )
        if result["type"] == FlowResultType.FORM:
            flows.async_abort(flow_id)
        await hass.async_block_till_done()
        return result

    today = dt_util.now().date()
    tomorrow = (today + timedelta(days=1)).isoformat()
    flows, flow_id, flat_form = await open_tariff("flat")
    require(
        "the ordinary flat tariff form no longer asks for a date",
        flat_form["step_id"] == "farm_tariff_flat"
        and EFFECTIVE_DATE not in flat_form["data_schema"].schema,
    )
    flows.async_abort(flow_id)
    result = await submit({"price_flat": 8}, tomorrow)
    require("future price saves through the new form", result["type"] == FlowResultType.CREATE_ENTRY, str(result.get("errors")))
    midnight = local_midnight(tomorrow)
    hour = timedelta(hours=1)
    require(
        "future price keeps the active rate and splits a reading across midnight",
        current_price(farm.options, midnight - hour) == 6
        and current_price(farm.options, midnight + hour) == 8
        and cost_for_interval(hass, farm.options, 2, midnight - hour, midnight + hour) == 14,
    )

    retro_date = (today - timedelta(days=1)).isoformat()
    cutoff = local_midnight(retro_date)
    total = state_for(hass, f"farm-{farm.entry_id}-energy-total")
    # Seed the real Recorder before the cutoff with a monotonic meter reading.
    hass.states.async_set(
        total.entity_id, "0", dict(total.attributes), force_update=True,
        timestamp=(cutoff - hour).timestamp(),
    )
    hass.states.async_set(
        total.entity_id, "0", dict(total.attributes), force_update=True,
        timestamp=(cutoff + hour).timestamp(),
    )
    await get_instance(hass).async_block_till_done()
    energy = hass.data[DOMAIN][farm.entry_id].energy
    energy.record.total_kwh = 12
    energy.record.total_cost = 72
    energy.record.last_ts = dt_util.utcnow().isoformat()
    flat = {"price_flat": 5}
    result = await submit(flat, retro_date)
    require("past tariff is recalculated from Recorder on save", result["type"] == FlowResultType.CREATE_ENTRY, str(result.get("errors")))
    energy = hass.data[DOMAIN][farm.entry_id].energy
    require(
        "recalculation preserves kWh, lowers cost, and retains the future revision",
        math.isclose(energy.record.total_kwh, 12, abs_tol=0.005)
        and math.isclose(energy.total_cost, 60, abs_tol=0.02)
        and current_price(farm.options, midnight + hour) == 8,
        str(farm.options.get(COST_ADJUSTMENTS)),
    )

    adjustment = farm.options[COST_ADJUSTMENTS]
    result = await submit(flat, retro_date)
    require(
        "saving the same date and rate again does not repeat the correction",
        result["type"] == FlowResultType.CREATE_ENTRY
        and farm.options[COST_ADJUSTMENTS] == adjustment,
    )
    require("reload keeps the tariff and adjustment", await hass.config_entries.async_reload(farm.entry_id))
    energy = hass.data[DOMAIN][farm.entry_id].energy
    require("reload retains corrected cost", math.isclose(energy.total_cost, 60, abs_tol=0.02))
    previous_options = dict(farm.options)
    result = await submit(flat, (today - timedelta(days=90)).isoformat())
    require(
        "missing Recorder history leaves the saved tariff and costs intact",
        result.get("errors") == {"base": "farm_tariff_history_unavailable"}
        and farm.options == previous_options,
        str(result.get("errors")),
    )

    flows, flow_id, zone_form = await open_tariff("dual")
    require(
        "the ordinary zoned tariff form edits configuration without a date",
        zone_form["step_id"] == "farm_tariff_tou"
        and EFFECTIVE_DATE not in zone_form["data_schema"].schema,
    )
    result = await flows.async_configure(
        flow_id,
        {"farm_tariff_tou": {
            "farm_elec_tou_currency": "RUB",
            "farm_elec_z1_start": "00:00:00",
            "farm_elec_z1_end": "06:00:00",
            "farm_elec_z1_price": 5,
            "farm_elec_z2_start": "06:00:00",
            "farm_elec_z2_end": "00:00:00",
            "farm_elec_z2_price": 7,
        }},
    )
    require(
        "zoned configuration applies immediately",
        result["type"] == FlowResultType.CREATE_ENTRY,
        str(result.get("errors")),
    )
    await hass.async_block_till_done()
    result = await submit({"price_zone_1": 8, "price_zone_2": 10}, tomorrow)
    require(
        "a price-only change cannot replace a different scheduled tariff type",
        result.get("errors") == {"base": "farm_tariff_different_layout"},
        str(result.get("errors")),
    )
    # Remove the scheduled flat revision from the isolated test fixture.
    from custom_components.miner.energy.tariff import TARIFF_SCHEDULE, tariff_at
    active = tariff_at(farm.options, dt_util.utcnow())
    options = {**farm.options, **active}
    options.pop(TARIFF_SCHEDULE)
    hass.config_entries.async_update_entry(farm, options=options)
    await hass.async_block_till_done()
    result = await submit({"price_zone_1": 8, "price_zone_2": 10}, tomorrow)
    require(
        "zoned price change preserves the existing hours and currency",
        result["type"] == FlowResultType.CREATE_ENTRY
        and cost_for_interval(hass, farm.options, 2, midnight + 5 * hour, midnight + 7 * hour) == 18,
        str(result.get("errors")),
    )


async def check_hourly_tariff_history(hass, farm):
    from homeassistant.components.recorder.models.statistics import StatisticMeanType
    from homeassistant.components.recorder.statistics import async_import_statistics

    from custom_components.miner.energy.tariff import (
        COST_ADJUSTMENTS,
        TariffHistoryError,
        corrected_cost,
        local_midnight,
        with_history_adjustment,
        with_revision,
    )
    from custom_components.miner.energy.tariff_history import async_farm_meter_history

    entry = entity_registry.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, "farm-hourly-audit-energy-total", config_entry=farm,
        suggested_object_id="audit_hourly_farm_energy",
    )
    now = dt_util.utcnow()
    hour = timedelta(hours=1)
    handoff = now.replace(minute=0, second=0, microsecond=0) - hour
    effective = handoff - 2 * hour
    async_import_statistics(
        hass,
        {
            "statistic_id": entry.entity_id,
            "source": "recorder",
            "name": None,
            "mean_type": StatisticMeanType.NONE,
            "has_sum": True,
            "unit_of_measurement": "kWh",
            "unit_class": "energy",
        },
        [
            {"start": effective - hour, "state": 100, "sum": 0},
            {"start": effective, "state": 102, "sum": 2},
            {"start": effective + hour, "state": 105, "sum": 5},
        ],
    )
    hass.states.async_set(
        entry.entity_id, "106", timestamp=(handoff + timedelta(minutes=10)).timestamp()
    )
    await get_instance(hass).async_block_till_done()
    readings = await async_farm_meter_history(hass, "hourly-audit", effective, now, 108)
    require(
        "older tariff corrections join real hourly statistics with recent readings",
        [value for _, value in readings] == [100, 102, 105, 106, 108],
        str(readings),
    )
    previous = {"farm_energy_rates": [{"currency": "RUB", "price_kwh": 6}]}
    next_rate = {"farm_energy_rates": [{"currency": "RUB", "price_kwh": 5}]}
    updated = with_revision(previous, next_rate, effective)
    correction = with_history_adjustment(hass, previous, updated, effective, readings)
    require(
        "hourly correction charges the 8 kWh difference exactly once",
        math.isclose(correction[COST_ADJUSTMENTS]["total"], -8, abs_tol=1e-6),
    )
    october = local_midnight("2026-10-31")
    november = local_midnight("2026-11-01")
    monthly = with_history_adjustment(
        hass,
        previous,
        with_revision(previous, next_rate, october),
        october,
        [(october, 100), (october + hour, 103), (november + hour, 105)],
    )
    require(
        "retroactive tariff adjusts both calendar months and the lifetime total",
        math.isclose(corrected_cost(monthly, 18, "months", "2026-10"), 15)
        and math.isclose(corrected_cost(monthly, 12, "months", "2026-11"), 10)
        and math.isclose(corrected_cost(monthly, 30, "total"), 25),
    )
    try:
        await async_farm_meter_history(hass, "hourly-audit", effective - hour, now, 108)
    except TariffHistoryError:
        print("PASS hourly gaps reject a partial recalculation", flush=True)
    else:
        raise AssertionError("An hourly gap must reject the correction")


async def check_monthly_summary(hass):
    now = dt_util.now()
    period = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    hass.states.async_set(
        "sensor.audit_monthly_energy", "420", {"period": period, "unit_of_measurement": "kWh"}
    )
    hass.states.async_set(
        "sensor.audit_monthly_cost", "2520", {"period": period, "unit_of_measurement": "RUB"}
    )
    notifications = []

    async def collect(event):
        if event.data["domain"] == "persistent_notification":
            notifications.append(event.data["service_data"])

    remove = hass.bus.async_listen("call_service", collect)
    try:
        await hass.services.async_call(
            "automation", "trigger", {"entity_id": "automation.miner_audit_monthly"},
            blocking=True,
        )
        await hass.async_block_till_done()
        require(
            "monthly summary renders last month's energy and cost in a notification",
            any(
                period in notification.get("title", "")
                and "420.0 kWh" in notification.get("message", "")
                and "2520.0 RUB" in notification.get("message", "")
                for notification in notifications
            ),
            str(notifications),
        )
    finally:
        remove()


async def check_activity(hass, miner, coord, events):
    from homeassistant.helpers.translation import async_get_translations

    coord.events.async_emit_problem_detected(
        "temperature",
        {
            "make": "WhatsMiner",
            "model": "M21S",
            "health": {"flags": {"temperature_high": True}},
            "board_sensors": {
                0: {"chip_temperature": 93, "board_temperature": 72},
                1: {"chip_temperature": 98, "board_temperature": 75},
            },
        },
        coord.baseline.anomaly,
    )
    await hass.async_block_till_done()
    activity = state_for(hass, f"{miner.entry_id}-activity", platform="event")
    require(
        "overheating card uses its own event type and records readings and limits",
        all(
            activity.attributes.get(key) == value
            for key, value in {
                "event_type": "problem_detected_temperature",
                "reason": "temperature_high",
                "max_chip_temperature_c": 98,
                "chip_temperature_limit_c": 95,
                "max_board_temperature_c": 75,
                "board_temperature_limit_c": 85,
            }.items()
        ),
        str(activity.attributes),
    )
    require(
        "temperature automations still receive the generic bus event",
        any(
            event.get("type") == "problem_detected"
            and event.get("event_type") == "problem_detected"
            and event.get("problem_type") == "temperature"
            and event.get("max_chip_temperature_c") == 98
            for event in events
        ),
    )
    key = "component.miner.entity.event.activity.state_attributes.event_type.state"
    for language, expected in (("en", "Overheating"), ("ru", "Перегрев")):
        translations = await async_get_translations(hass, language, "entity", [DOMAIN])
        require(
            f"HA translates the overheating card in {language}",
            translations.get(f"{key}.{activity.attributes['event_type']}") == expected,
        )

    coord.events.async_emit_problem_cleared("temperature")
    cases = {
        "hashboard": (
            {"board_sensors": {2: {"board_chips": 0, "board_expected_chips": 96}}},
            {"board": "2", "working_chips": 0, "expected_chips": 96},
        ),
        "hashrate": (
            {
                "miner_sensors": {"hashrate": 60, "ideal_hashrate": 100},
                "health": {"flags": {"hashrate_low": True}},
            },
            {"current_hashrate": 60, "expected_hashrate": 100, "hashrate_limit": 85},
        ),
        "fan": (
            {"fan_sensors": {0: {"fan_speed": 2000}, 1: {"fan_speed": 0}}},
            {"fan": "1", "fan_speed": 0, "fan_speed_limit_rpm": 1000},
        ),
        "pool": (
            {"pool_health": {"alive": False, "get_failures": 14}},
            {"pool_alive": False, "pool_get_failures": 14},
        ),
        "reject": (
            {
                "reject_rate": 7,
                "accepted_shares": 93,
                "rejected_shares": 7,
                "health": {"flags": {"reject_rate_high": True}},
            },
            {"current_reject_rate": 7, "rejected_shares": 7, "reject_rate_limit_percent": 2},
        ),
        "power": (
            {"miner_sensors": {"miner_consumption": 1200, "power_limit": 1000}},
            {"current_power": 1200, "power_lower_bound_w": 800, "power_upper_bound_w": 1100},
        ),
        "recovery": (
            {"miner_sensors": {"hashrate": 8, "ideal_hashrate": 20}},
            {"current_hashrate": 8, "expected_hashrate": 20},
        ),
    }
    for problem, (data, expected) in cases.items():
        coord.events.async_emit_problem_detected(problem, data, None)
        activity = state_for(hass, f"{miner.entry_id}-activity", platform="event")
        require(
            f"{problem} uses a specific card label with the corresponding readings",
            activity.attributes.get("event_type") == f"problem_detected_{problem}"
            and "max_chip_temperature_c" not in activity.attributes
            and all(activity.attributes.get(k) == v for k, v in expected.items()),
        )
        coord.events.async_emit_problem_cleared(problem)

    from custom_components.miner.health.recovery.definitions import RecoveryRecord

    record = RecoveryRecord(
        reboot_attempts=2, power_cycle_attempts=1, power_on_retries=3,
        expected_hashrate=52,
    )
    coord.repairs.open_recovery_failed({"miner_sensors": {"hashrate": 8}}, record)
    activity = state_for(hass, f"{miner.entry_id}-activity", platform="event")
    require(
        "recovery failure shows actual attempts and the expected hashrate",
        activity.attributes.get("event_type") == "problem_detected_recovery_failed"
        and activity.attributes.get("reboot_attempts") == 2
        and activity.attributes.get("power_cycle_attempts") == 1
        and activity.attributes.get("expected_hashrate") == 52,
    )
    coord.repairs.clear_recovery_failed()
    coord.repairs.open_power_restore_failed({}, record)
    activity = state_for(hass, f"{miner.entry_id}-activity", platform="event")
    require(
        "power restore failure shows the number of failed power-on attempts",
        activity.attributes.get("event_type") == "problem_detected_power_restore_failed"
        and activity.attributes.get("reason") == "power_restore_failed"
        and activity.attributes.get("power_on_retries") == 3,
    )
    coord.repairs.clear_power_restore_failed()



async def check_uptime(hass, axe, miner, coord):
    unique_id = f"{miner.entry_id}-uptime_formatted"
    uptime = state_for(hass, unique_id)
    require(
        "existing uptime entity exposes a duration in seconds",
        uptime.state == "3600"
        and uptime.attributes.get("device_class") == "duration"
        and uptime.attributes.get("unit_of_measurement") == "s"
        and uptime.attributes.get("uptime_seconds") == 3600,
    )

    started = dt_util.utcnow()
    control_id = "sensor.uptime_logbook_control"
    hass.states.async_set(control_id, "1h")
    for value, control in ((3660, "1h 1m"), (3720, "1h 2m")):
        axe.uptime = value
        await coord.async_refresh()
        hass.states.async_set(control_id, control)
    require(
        "uptime continues updating on the original entity",
        (updated := state_for(hass, unique_id)).entity_id == uptime.entity_id
        and updated.state == "3720"
        and updated.attributes.get("uptime_seconds") == 3720,
    )

    await get_instance(hass).async_block_till_done()
    processor = EventProcessor(hass, [], entity_ids=[uptime.entity_id, control_id])
    activity = await hass.async_add_executor_job(
        processor.get_events, started, dt_util.utcnow()
    )
    require(
        "Activity excludes uptime changes and still shows ordinary text sensors",
        any(row.get("entity_id") == control_id for row in activity)
        and not any(row.get("entity_id") == uptime.entity_id for row in activity),
        str(activity),
    )


async def check_notification_blueprint(hass):
    notifications = []

    async def on_service(event):
        data = event.data
        if data["domain"] == "persistent_notification" and data["service"] == "create":
            notifications.append(data["service_data"])

    remove = hass.bus.async_listen("call_service", on_service)
    payload = {"scope": "miner", "device_id": "blueprint_test", "name": "Audit Miner"}
    try:
        for event_type, extra in (
            ("offline", {}),
            ("problem_detected", {"problem_type": "temperature"}),
            ("recovery_locked", {}),
            ("problem_detected", {"problem_type": "fan"}),
            ("offline", {"device_id": "other_miner"}),
        ):
            hass.bus.async_fire("miner_event", {**payload, "type": event_type, **extra})
        await hass.async_block_till_done()
    finally:
        remove()
    require(
        "blueprint notifies for the three matching events only",
        {note["notification_id"] for note in notifications}
        == {
            "msksrv_miner_blueprint_test_offline",
            "msksrv_miner_blueprint_test_temperature",
            "msksrv_miner_blueprint_test_recovery_locked",
        }
        and len(notifications) == 3,
        repr(notifications),
    )


async def check_diagnostics(hass, axe, miner, farm):
    secret = "diagnostics-test-secret"
    hass.config_entries.async_update_entry(
        miner,
        data={**miner.data, "rpc_password": secret, "web_password": secret},
    )
    hass.config_entries.async_update_entry(
        farm,
        options={**farm.options, "farm_pool_presets": [{"password": secret}]},
    )
    await hass.async_block_till_done()
    integration = await async_get_integration(hass, DOMAIN)
    platform = await integration.async_get_platform("diagnostics")
    miner_dump = await platform.async_get_config_entry_diagnostics(hass, miner)
    farm_dump = await platform.async_get_config_entry_diagnostics(hass, farm)
    require(
        "diagnostics reports firmware, health, energy and recovery",
        miner_dump["miner"]["firmware"] == "v2.9.0"
        and {"health", "energy", "recovery"}.issubset(miner_dump),
    )
    require(
        "farm diagnostics reports aggregate state",
        farm_dump["farm"]["miners"] == 1 and farm_dump["farm"]["online"] == 1,
    )
    dumps = json.dumps([miner_dump, farm_dump])
    require(
        "diagnostics excludes credentials, addresses and workers",
        all(
            value not in dumps
            for value in (secret, axe.ip, axe.mac, "pool.invalid", "worker")
        ),
    )


async def check_energy(hass, miner, farm):
    coord = hass.data[DOMAIN][miner.entry_id]
    farm_coord = hass.data[DOMAIN][farm.entry_id]
    miner_total_id = f"{miner.entry_id}-energy-total"
    farm_total_id = f"farm-{farm.entry_id}-energy-total"
    energy_ids = set()
    for name, unique_id in (("miner", miner_total_id), ("farm", farm_total_id)):
        state = state_for(hass, unique_id)
        require(
            f"{name} energy sensor metadata",
            state is not None
            and all(
                state.attributes.get(key) == value
                for key, value in {
                    "device_class": "energy",
                    "state_class": "total_increasing",
                    "unit_of_measurement": "kWh",
                }.items()
            ),
            repr(state),
        )
        energy_ids.add(state.entity_id)
    statistics = await async_list_statistic_ids(hass, energy_ids)
    require(
        "recorder advertises both kWh sensors for energy statistics",
        {stat["statistic_id"] for stat in statistics if stat["has_sum"]} == energy_ids,
        repr(statistics),
    )
    previous = coord.energy.record.total_kwh
    await asyncio.sleep(1)
    await coord.async_refresh()
    await farm_coord.async_refresh()
    measured = coord.energy.record.total_kwh
    require(
        "energy integrated from actual 23 W polls",
        measured > previous,
        f"{measured:.8f} kWh",
    )
    require(
        "energy retained across entry reload",
        await hass.config_entries.async_reload(miner.entry_id),
    )
    after = hass.data[DOMAIN][miner.entry_id].energy.record.total_kwh
    require("stored total remains monotonic", after >= measured, f"{after:.8f} kWh")


async def check_legacy_cost(hass, farm):
    registry = entity_registry.async_get(hass)
    legacy_id = f"farm-{farm.entry_id}-cost-total-rub"
    legacy = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        legacy_id,
        config_entry=farm,
        suggested_object_id="audit_legacy_cost_rub",
    )
    await hass.config_entries.async_reload(farm.entry_id)
    await hass.async_block_till_done()
    disabled = entity_registry.RegistryEntryDisabler.INTEGRATION
    require(
        "migration disables old active cost entry",
        registry.async_get(legacy.entity_id).disabled_by == disabled,
    )
    hass.config_entries.async_update_entry(
        farm,
        options={
            **farm.options,
            "farm_legacy_cost_sensors_enabled": True,
            "farm_energy_rates": [{"currency": "RUB", "price_kwh": 6.0}],
        },
    )
    await hass.async_block_till_done()
    require(
        "opt-in marks legacy entity enabled",
        registry.async_get(legacy.entity_id).disabled_by is None,
    )
    immediate = state_for(hass, legacy_id)
    require(
        "legacy entity active after first reload",
        state_is_live(immediate),
        repr(immediate),
    )
    require(
        "legacy total monetary class is accepted",
        immediate.attributes["state_class"] == "total",
    )

    for suffix in ("today", "month", "total"):
        state = state_for(hass, f"farm-{farm.entry_id}-energy-cost-{suffix}")
        require(
            f"RUB tariff publishes valid cost {suffix}",
            state_is_live(state) and state.attributes["state_class"] == "total",
        )
        require(
            f"cost {suffix} reset metadata",
            bool(state.attributes.get("last_reset")) == (suffix != "total"),
        )
    fresh_legacy = state_for(hass, f"farm-{farm.entry_id}-cost-now-rub")
    require("legacy opt-in enables newly created entities", state_is_live(fresh_legacy))

    registry.async_update_entity(
        legacy.entity_id, disabled_by=entity_registry.RegistryEntryDisabler.USER
    )
    await hass.config_entries.async_reload(farm.entry_id)
    require(
        "legacy migration preserves user-disabled state",
        registry.async_get(legacy.entity_id).disabled_by
        == entity_registry.RegistryEntryDisabler.USER,
    )


async def check_repair_forms(hass, miner, farm):
    from homeassistant.components.repairs.websocket_api import RepairsFlowIndexView
    from homeassistant.helpers.translation import async_get_translations

    from custom_components.miner.health.repairs.definitions import (
        farm_issue_id,
        miner_issue_id,
    )

    manager = hass.data["repairs"]["flow_manager"]
    for issue_id, key in (
        (farm_issue_id(farm.entry_id, "offline"), "farm_offline"),
        (miner_issue_id(miner.entry_id, "temperature"), "miner_temperature"),
    ):
        issue_registry.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=True,
            severity=issue_registry.IssueSeverity.WARNING,
            translation_key=key,
            translation_placeholders={
                "name": "Audit",
                "offline": "1",
                "total": "1",
                "miners": "Bitaxe",
                "miners_more": "",
                "chip_temperature": "80",
                "board_temperature": "65",
            },
        )
        step = await manager.async_init(DOMAIN, data={"issue_id": issue_id})
        require(f"{key} repair opens", step["type"] is FlowResultType.FORM)
        serialized = RepairsFlowIndexView(manager)._prepare_result_json(step)
        require(
            f"{key} repair serializes its action selector",
            any(field["name"] == "action" for field in serialized["data_schema"]),
        )
        for language in ("en", "ru"):
            translations = await async_get_translations(
                hass, language, "issues", [DOMAIN]
            )
            prefix = f"component.miner.issues.{key}.fix_flow.step.{step['step_id']}"
            require(
                f"{key} repair has {language} action and description",
                bool(translations.get(prefix + ".data.action"))
                and bool(translations.get(prefix + ".description")),
            )
        if key == "miner_temperature":
            thresholds = await manager.async_configure(
                step["flow_id"], {"action": "thresholds"}
            )
            require(
                "temperature repair opens thresholds",
                thresholds["step_id"] == "open_thresholds",
            )
            invalid = await manager.async_configure(
                step["flow_id"],
                {
                    "temp_chip_warn_c": 90,
                    "temp_chip_high_c": 85,
                    "temp_board_warn_c": 60,
                    "temp_board_high_c": 70,
                },
            )
            require(
                "temperature repair rejects inverted thresholds",
                invalid.get("errors", {}).get("temp_chip_high_c")
                == "temp_warn_must_be_below_critical",
            )
            manager.async_abort(step["flow_id"])
            step = await manager.async_init(DOMAIN, data={"issue_id": issue_id})
        done = await manager.async_configure(step["flow_id"], {"action": "checked"})
        require(
            f"{key} repair accepts acknowledgement",
            done["type"] is FlowResultType.CREATE_ENTRY,
        )
        require(
            f"{key} repair disappears",
            issue_registry.async_get(hass).async_get_issue(DOMAIN, issue_id) is None,
        )


class AuditPowerSwitch(SwitchEntity):
    """Simulate immediate commands and a delayed turn-on acknowledgement."""

    entity_id = "switch.audit_power"
    _attr_is_on = True

    def __init__(self):
        self.commands = []
        self.before_off = None
        self.on_started = asyncio.Event()
        self.off_completed = asyncio.Event()
        self.allow_on = asyncio.Event()
        self.allow_on.set()

    async def async_turn_off(self, **kwargs):
        if self.before_off is not None:
            await self.before_off()
        self.commands.append("off")
        self._attr_is_on = False
        self.async_write_ha_state()
        self.off_completed.set()

    async def async_turn_on(self, **kwargs):
        self.on_started.set()
        await self.allow_on.wait()
        self.commands.append("on")
        self._attr_is_on = True
        self.async_write_ha_state()


async def check_power_recovery(hass, axe, miner, farm, events):
    from custom_components.miner.health.recovery.definitions import (
        RecoveryRecord,
        RecoveryState,
    )
    from custom_components.miner.health.recovery.emergency import (
        async_entry_emergency_latched,
    )
    from custom_components.miner.health.recovery.storage import RecoveryStorage

    power = AuditPowerSwitch()
    await hass.data[SWITCH_COMPONENT].async_add_entities([power])
    hass.config_entries.async_update_entry(
        miner,
        options={
            **miner.options,
            "power_switch": power.entity_id,
            "auto_recovery_enabled": True,
            "auto_recovery_power_cycle_enabled": True,
            "auto_recovery_power_off_pause_seconds": 0,
        },
    )
    await hass.async_block_till_done()
    coord = hass.data[DOMAIN][miner.entry_id]
    farm_coord = hass.data[DOMAIN][farm.entry_id]
    await farm_coord.async_refresh()
    recovery = coord.recovery
    recovery.record.state = RecoveryState.WAITING_REBOOT
    recovery.record.wait_until = None
    recovery.record.reboot_attempts = 1
    saved = RecoveryStorage(hass, miner.entry_id)

    async def check_power_off_journal():
        await saved.async_load()
        require(
            "power-off intent is persisted before turn_off",
            saved.record.state == RecoveryState.POWER_OFF_WAIT,
        )

    power.before_off = check_power_off_journal
    await recovery.async_process_update(None, None, available=False)
    power.before_off = None
    require(
        "recovery can cut simulated power after reboot timeout",
        power.commands == ["off"]
        and recovery.record.state == RecoveryState.POWER_OFF_WAIT,
    )
    await recovery.async_process_update(None, None, available=False)
    require(
        "recovery restores power while miner remains unreachable",
        power.commands == ["off", "on"]
        and recovery.record.state == RecoveryState.WAITING_POWER_RECOVERY,
    )

    recovery.record.state = RecoveryState.POWER_OFF_WAIT
    recovery.record.wait_until = None
    await power.async_turn_off()
    power.on_started.clear()
    power.off_completed.clear()
    power.allow_on.clear()
    stop = state_for(hass, f"farm-{farm.entry_id}-emergency-stop", "button")
    restore_task = asyncio.create_task(
        recovery.async_process_update(None, None, available=False)
    )
    stop_task = None
    try:
        await asyncio.wait_for(power.on_started.wait(), timeout=5)
        stop_task = asyncio.create_task(
            hass.services.async_call(
                "button", "press", {"entity_id": stop.entity_id}, blocking=True
            )
        )
        # Allow an incorrectly unordered emergency stop to reach the switch first.
        try:
            await asyncio.wait_for(power.off_completed.wait(), timeout=0.5)
        except TimeoutError:
            pass
    finally:
        power.allow_on.set()
        await restore_task
        if stop_task is not None:
            await stop_task
    await hass.async_block_till_done()
    require(
        "emergency stop wins over in-flight power-on",
        hass.states.get(power.entity_id).state == "off",
        repr(power.commands),
    )
    require(
        "emergency latch persisted",
        await async_entry_emergency_latched(hass, miner.entry_id),
    )
    require(
        "farm stop reached event bus",
        any(
            event.get("type") == "emergency_power_off"
            and event.get("scope") == "farm"
            and event.get("device_id")
            for event in events
        ),
    )
    require(
        "latched miner reload succeeds",
        await hass.config_entries.async_reload(miner.entry_id),
    )
    require(
        "latched farm reload succeeds",
        await hass.config_entries.async_reload(farm.entry_id),
    )
    farm_coord = hass.data[DOMAIN][farm.entry_id]
    require(
        "latch restored after reload",
        farm_coord.emergency_stop_active
        and hass.data[DOMAIN][miner.entry_id].recovery.record.emergency_stop_latched,
    )
    require(
        "reload leaves simulated power off",
        hass.states.get(power.entity_id).state == "off",
    )

    clear = state_for(hass, f"farm-{farm.entry_id}-clear-emergency-stop", "button")
    for expected in (True, False):
        await hass.services.async_call(
            "button", "press", {"entity_id": clear.entity_id}, blocking=True
        )
        require(
            f"two-step clear latch={expected}",
            farm_coord.emergency_stop_active is expected,
        )
    require(
        "clearing the latch does not energize the switch",
        hass.states.get(power.entity_id).state == "off",
    )
    require(
        "unload before simulating a restart mid-cycle",
        await hass.config_entries.async_unload(miner.entry_id),
    )
    saved.replace(RecoveryRecord(state=RecoveryState.POWER_OFF_WAIT))
    await saved.async_save(force=True)
    await axe.stop()
    await hass.config_entries.async_setup(miner.entry_id)
    require(
        "first failed poll resumes pending power restoration",
        miner.state is ConfigEntryState.SETUP_RETRY and power.is_on,
    )
    await axe.start()
    require(
        "miner loads after recovering power",
        await hass.config_entries.async_reload(miner.entry_id),
    )
    hass.config_entries.async_update_entry(
        miner, options={**miner.options, "auto_recovery_enabled": False}
    )
    await hass.async_block_till_done()


async def wait_for(predicate, *, timeout):
    try:
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(0.25)
    except TimeoutError:
        return False
    return True


def state_is_live(state):
    return (
        state is not None
        and state.state not in {STATE_UNAVAILABLE, STATE_UNKNOWN}
        and not state.attributes.get("restored", False)
    )


async def check_offline(hass, axe, miner, farm, events, device_id):
    from custom_components.miner.health.repairs.definitions import farm_issue_id

    hass.config_entries.async_update_entry(
        farm,
        options={
            **farm.options,
            "repair_confirm_overrides": {"offline": 0},
            "repair_recovery_seconds": 0,
        },
    )
    await hass.async_block_till_done()
    coord = hass.data[DOMAIN][miner.entry_id]
    farm_coord = hass.data[DOMAIN][farm.entry_id]
    coord.update_interval = timedelta(seconds=2)
    await coord.async_refresh()
    await axe.stop()
    require(
        "four scheduled polls fail without manual refresh",
        await wait_for(lambda: coord._failure_count >= 4, timeout=14),
    )
    await hass.async_block_till_done()
    require(
        "scheduled polling publishes exactly one offline event",
        sum(
            event.get("type") == "offline" and event.get("device_id") == device_id
            for event in events
        )
        == 1,
    )
    platform = await (await async_get_integration(hass, DOMAIN)).async_get_platform(
        "diagnostics"
    )
    diagnostics = await platform.async_get_config_entry_diagnostics(hass, miner)
    require(
        "failed polls are visible in diagnostics",
        bool(diagnostics["last_poll_error"]["type"])
        and bool(diagnostics["last_poll_error"]["at"]),
    )
    await farm_coord.async_refresh()
    require(
        "connection loss makes telemetry unavailable", not coord.last_update_success
    )
    require(
        "farm remains loaded during member outage",
        farm.state is ConfigEntryState.LOADED,
    )
    require(
        "farm counts 0 of 1 online",
        farm_coord.data["miners_online"] == 0 and farm_coord.data["miner_count"] == 1,
    )
    issue_id = farm_issue_id(farm.entry_id, "offline")
    issues = issue_registry.async_get(hass)
    require(
        "offline Repair registered",
        issues.async_get_issue(DOMAIN, issue_id) is not None,
    )
    await axe.start()
    require(
        "scheduled polls restore miner and farm without reload",
        await wait_for(
            lambda: coord.last_update_success and farm_coord.data["miners_online"] == 1,
            timeout=38,
        ),
    )
    require(
        "scheduled polling publishes exactly one online event",
        sum(
            event.get("type") == "online" and event.get("device_id") == device_id
            for event in events
        )
        == 1,
    )
    await axe.stop()
    await hass.config_entries.async_reload(miner.entry_id)
    require(
        "offline miner enters retry",
        miner.state is ConfigEntryState.SETUP_RETRY,
        str(miner.state),
    )
    require(
        "farm reload succeeds with member never polled",
        await hass.config_entries.async_reload(farm.entry_id),
    )
    farm_coord = hass.data[DOMAIN][farm.entry_id]
    require(
        "offline farm health is zero",
        farm_coord.data["health_score"] == 0
        and farm_coord.data["health_miners_offline"] == 1,
    )
    await axe.start()
    require(
        "miner reload restores telemetry",
        await hass.config_entries.async_reload(miner.entry_id),
    )
    await farm_coord.async_refresh()
    await farm_coord.async_refresh()
    require("farm sees miner online again", farm_coord.data["miners_online"] == 1)
    require(
        "offline Repair clears after recovery",
        issues.async_get_issue(DOMAIN, issue_id) is None,
    )
    require(
        "energy sensor restored after reconnect",
        state_is_live(state_for(hass, f"{miner.entry_id}-energy-total")),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source", type=Path, help="Path to the custom_components/miner directory"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main(args.source.resolve()))
