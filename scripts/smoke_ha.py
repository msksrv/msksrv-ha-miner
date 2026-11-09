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

        await check_energy(hass, miner, farm)
        await check_legacy_cost(hass, farm)
        await check_repair_forms(hass, miner, farm)
        await check_notification_blueprint(hass)
        await check_power_recovery(hass, axe, miner, farm, events)
        await check_offline(hass, axe, miner, farm, events, miner_device.id)
        await check_diagnostics(hass, axe, miner, farm)
        print(f"Completed {manifest['version']}", flush=True)


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
