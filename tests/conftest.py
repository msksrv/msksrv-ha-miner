"""Pytest hooks and Home Assistant stubs for miner component tests."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from enum import Enum
from types import ModuleType
from unittest.mock import MagicMock


def _install_homeassistant_stubs() -> None:
    if "homeassistant" in sys.modules:
        return

    ha = ModuleType("homeassistant")
    ha_core = ModuleType("homeassistant.core")
    ha_core.HomeAssistant = MagicMock
    ha_core.split_entity_id = lambda entity_id: tuple(entity_id.split(".", 1))

    class Platform(str, Enum):
        SENSOR = "sensor"
        BINARY_SENSOR = "binary_sensor"
        SWITCH = "switch"
        NUMBER = "number"
        SELECT = "select"
        BUTTON = "button"
        EVENT = "event"

    ha_const = ModuleType("homeassistant.const")
    ha_const.Platform = Platform
    ha_const.UnitOfEnergy = MagicMock(
        WATT_HOUR="Wh",
        KILO_WATT_HOUR="kWh",
        MEGA_WATT_HOUR="MWh",
    )
    ha_const.UnitOfPower = MagicMock(WATT="W", KILO_WATT="kW", MEGA_WATT="MW")

    ha_ce = ModuleType("homeassistant.config_entries")
    ha_ce.ConfigEntry = MagicMock

    ha_exceptions = ModuleType("homeassistant.exceptions")

    class ConfigEntryNotReady(Exception):
        pass

    ha_exceptions.ConfigEntryNotReady = ConfigEntryNotReady

    ha_sensor = ModuleType("homeassistant.components.sensor")
    ha_sensor.SensorDeviceClass = MagicMock(ENERGY="energy", POWER="power")

    ha_er = ModuleType("homeassistant.helpers.entity_registry")
    ha_er.async_get = MagicMock(return_value=MagicMock(entities={}))

    ha_util = ModuleType("homeassistant.util")
    ha_dt = ModuleType("homeassistant.util.dt")

    def as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def as_local(value: datetime) -> datetime:
        return value

    def parse_datetime(value: str | datetime | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text)

    def utcnow() -> datetime:
        return datetime.now(timezone.utc)

    ha_dt.as_utc = as_utc
    ha_dt.as_local = as_local
    ha_dt.parse_datetime = parse_datetime
    ha_dt.utcnow = utcnow
    ha_util.dt = ha_dt

    ha_helpers = ModuleType("homeassistant.helpers")
    ha_cv = ModuleType("homeassistant.helpers.config_validation")
    ha_cv.config_entry_only_config_schema = lambda domain: {}
    ha_helpers.config_validation = ha_cv

    ha_update = ModuleType("homeassistant.helpers.update_coordinator")

    class UpdateFailed(Exception):
        pass

    ha_update.UpdateFailed = UpdateFailed

    ha_storage = ModuleType("homeassistant.helpers.storage")

    class Store:
        def __init__(self, hass, version, key, **kwargs):
            self.hass = hass
            self.version = version
            self.key = key

        def __class_getitem__(cls, item):
            return cls

        async def _async_migrate_func(
            self, old_major_version, old_minor_version, old_data
        ):
            raise NotImplementedError

        async def async_load(self):
            return None

        async def async_save(self, data):
            return None

        async def async_remove(self):
            return None

    ha_storage.Store = Store

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.const"] = ha_const
    sys.modules["homeassistant.config_entries"] = ha_ce
    sys.modules["homeassistant.exceptions"] = ha_exceptions
    sys.modules["homeassistant.components"] = ModuleType("homeassistant.components")
    sys.modules["homeassistant.components.sensor"] = ha_sensor
    sys.modules["homeassistant.util"] = ha_util
    sys.modules["homeassistant.util.dt"] = ha_dt
    sys.modules["homeassistant.helpers"] = ha_helpers
    sys.modules["homeassistant.helpers.config_validation"] = ha_cv
    sys.modules["homeassistant.helpers.update_coordinator"] = ha_update
    sys.modules["homeassistant.helpers.storage"] = ha_storage
    sys.modules["homeassistant.helpers.entity_registry"] = ha_er

    ha_selector = ModuleType("homeassistant.helpers.selector")
    ha_selector.Selector = MagicMock
    ha_selector.EntitySelector = MagicMock
    ha_selector.EntitySelectorConfig = MagicMock
    sys.modules["homeassistant.helpers.selector"] = ha_selector


def load_miner_module(relative_path: str, module_name: str):
    """Import a miner module without executing custom_components.miner.__init__."""
    import importlib.util
    from pathlib import Path

    base = Path(__file__).resolve().parents[1] / "custom_components" / "miner"
    path = base / relative_path
    for pkg_name, pkg_path in (
        ("custom_components", base.parent),
        ("custom_components.miner", base),
        ("custom_components.miner.energy", base / "energy"),
    ):
        if pkg_name not in sys.modules:
            pkg = ModuleType(pkg_name)
            pkg.__path__ = [str(pkg_path)]
            sys.modules[pkg_name] = pkg

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(module_name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_install_homeassistant_stubs()
