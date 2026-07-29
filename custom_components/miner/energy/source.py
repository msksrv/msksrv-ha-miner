"""Resolve energy sources and read power/energy from Home Assistant entities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant, split_entity_id
from homeassistant.helpers import entity_registry as er

from ..const import (
    CONF_ENERGY_PHYSICAL_SENSOR,
    CONF_ENERGY_POWER_SENSOR,
    CONF_ENERGY_SOURCE_MODE,
    CONF_POWER_SWITCH,
    ENERGY_SOURCE_AUTO,
    ENERGY_SOURCE_MINER_POWER,
    ENERGY_SOURCE_PHYSICAL,
    ENERGY_SOURCE_SWITCH_POWER,
)
from .definitions import (
    RESOLVED_MINER_POWER,
    RESOLVED_PHYSICAL,
    RESOLVED_SWITCH_POWER,
    RESOLVED_UNAVAILABLE,
    ResolvedEnergySource,
)
from .registry import physical_entity_owner

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

_ENERGY_TO_KWH = {
    UnitOfEnergy.WATT_HOUR: 1 / 1000.0,
    "Wh": 1 / 1000.0,
    UnitOfEnergy.KILO_WATT_HOUR: 1.0,
    "kWh": 1.0,
    UnitOfEnergy.MEGA_WATT_HOUR: 1000.0,
    "MWh": 1000.0,
}

_POWER_TO_W = {
    UnitOfPower.WATT: 1.0,
    "W": 1.0,
    UnitOfPower.KILO_WATT: 1000.0,
    "kW": 1000.0,
    UnitOfPower.MEGA_WATT: 1_000_000.0,
    "MW": 1_000_000.0,
}


def _entity_registry_entry(hass: HomeAssistant, entity_id: str):
    return er.async_get(hass).async_get(entity_id)


def _state(hass: HomeAssistant, entity_id: str):
    return hass.states.get(entity_id)


def _parse_float(value: Any) -> float | None:
    if value in (None, "unknown", "unavailable", ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _device_id_for_entity(hass: HomeAssistant, entity_id: str) -> str | None:
    entry = _entity_registry_entry(hass, entity_id)
    return entry.device_id if entry else None


def discover_device_sensors(
    hass: HomeAssistant,
    device_id: str | None,
    *,
    device_class: SensorDeviceClass,
) -> list[str]:
    if not device_id:
        return []
    reg = er.async_get(hass)
    found: list[str] = []
    for ent in reg.entities.values():
        if ent.device_id != device_id:
            continue
        if ent.domain != "sensor":
            continue
        if ent.original_device_class != device_class:
            continue
        if _state(hass, ent.entity_id) is not None:
            found.append(ent.entity_id)
    return sorted(found)


def read_energy_kwh(hass: HomeAssistant, entity_id: str) -> float | None:
    state = _state(hass, entity_id)
    if state is None:
        return None
    value = _parse_float(state.state)
    if value is None:
        return None
    unit = str(state.attributes.get("unit_of_measurement") or "").strip()
    factor = _ENERGY_TO_KWH.get(unit)
    if factor is None:
        return None
    return value * factor


def read_power_w(hass: HomeAssistant, entity_id: str) -> float | None:
    state = _state(hass, entity_id)
    if state is None:
        return None
    value = _parse_float(state.state)
    if value is None:
        return None
    unit = str(state.attributes.get("unit_of_measurement") or "").strip()
    factor = _POWER_TO_W.get(unit)
    if factor is None:
        return None
    return value * factor


def miner_power_w(data: dict[str, Any] | None) -> float | None:
    if not data:
        return None
    ms = data.get("miner_sensors") or {}
    return _parse_float(ms.get("miner_consumption"))


def auto_discovered_physical_entity(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    opts = entry.options
    mode = str(opts.get(CONF_ENERGY_SOURCE_MODE) or ENERGY_SOURCE_AUTO)
    if mode != ENERGY_SOURCE_AUTO:
        return None
    if (opts.get(CONF_ENERGY_PHYSICAL_SENSOR) or "").strip():
        return None
    switch = (opts.get(CONF_POWER_SWITCH) or "").strip() or None
    switch_device = _device_id_for_entity(hass, switch) if switch else None
    candidates = discover_device_sensors(
        hass, switch_device, device_class=SensorDeviceClass.ENERGY
    )
    if len(candidates) == 1:
        return candidates[0]
    return None


def resolve_miner_energy_source(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> ResolvedEnergySource:
    resolved = _resolve_miner_energy_source_internal(hass, entry)
    if resolved.source == RESOLVED_PHYSICAL and resolved.entity_id:
        owner = physical_entity_owner(
            hass, resolved.entity_id, exclude_entry_id=entry.entry_id
        )
        if owner:
            _LOGGER.warning(
                "Physical energy sensor %s already assigned to %s; miner %s falls back",
                resolved.entity_id,
                owner,
                entry.entry_id,
            )
            return _fallback_without_physical(hass, entry)
    return resolved


def _resolve_miner_energy_source_internal(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> ResolvedEnergySource:
    opts = entry.options
    mode = str(opts.get(CONF_ENERGY_SOURCE_MODE) or ENERGY_SOURCE_AUTO)

    physical = (opts.get(CONF_ENERGY_PHYSICAL_SENSOR) or "").strip() or None
    power = (opts.get(CONF_ENERGY_POWER_SENSOR) or "").strip() or None
    switch = (opts.get(CONF_POWER_SWITCH) or "").strip() or None
    switch_device = _device_id_for_entity(hass, switch) if switch else None

    if mode == ENERGY_SOURCE_PHYSICAL:
        if physical and _valid_energy_entity(hass, physical):
            return ResolvedEnergySource(RESOLVED_PHYSICAL, physical, estimated=False)
        return ResolvedEnergySource(RESOLVED_UNAVAILABLE)

    if mode == ENERGY_SOURCE_SWITCH_POWER:
        entity = power or _single_discovered(
            hass, switch_device, device_class=SensorDeviceClass.POWER
        )
        if entity and _valid_power_entity(hass, entity):
            return ResolvedEnergySource(RESOLVED_SWITCH_POWER, entity, estimated=True)
        return ResolvedEnergySource(RESOLVED_UNAVAILABLE)

    if mode == ENERGY_SOURCE_MINER_POWER:
        return ResolvedEnergySource(RESOLVED_MINER_POWER, estimated=True)

    # Auto: physical → switch power → miner power (single unambiguous device sensor only).
    if not physical:
        candidates = discover_device_sensors(
            hass, switch_device, device_class=SensorDeviceClass.ENERGY
        )
        if len(candidates) == 1:
            physical = candidates[0]
    if physical and _valid_energy_entity(hass, physical):
        return ResolvedEnergySource(RESOLVED_PHYSICAL, physical, estimated=False)

    if not power:
        candidates = discover_device_sensors(
            hass, switch_device, device_class=SensorDeviceClass.POWER
        )
        if len(candidates) == 1:
            power = candidates[0]
    if power and _valid_power_entity(hass, power):
        return ResolvedEnergySource(RESOLVED_SWITCH_POWER, power, estimated=True)

    return ResolvedEnergySource(RESOLVED_MINER_POWER, estimated=True)


def _fallback_without_physical(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> ResolvedEnergySource:
    opts = entry.options
    power = (opts.get(CONF_ENERGY_POWER_SENSOR) or "").strip() or None
    switch = (opts.get(CONF_POWER_SWITCH) or "").strip() or None
    switch_device = _device_id_for_entity(hass, switch) if switch else None

    if not power:
        candidates = discover_device_sensors(
            hass, switch_device, device_class=SensorDeviceClass.POWER
        )
        if len(candidates) == 1:
            power = candidates[0]
    if power and _valid_power_entity(hass, power):
        return ResolvedEnergySource(RESOLVED_SWITCH_POWER, power, estimated=True)

    return ResolvedEnergySource(RESOLVED_MINER_POWER, estimated=True)


def _single_discovered(
    hass: HomeAssistant,
    device_id: str | None,
    *,
    device_class: SensorDeviceClass,
) -> str | None:
    candidates = discover_device_sensors(hass, device_id, device_class=device_class)
    if len(candidates) == 1:
        return candidates[0]
    return None


def _valid_energy_entity(hass: HomeAssistant, entity_id: str) -> bool:
    try:
        domain, _ = split_entity_id(entity_id)
    except ValueError:
        return False
    if domain != "sensor":
        return False
    entry = _entity_registry_entry(hass, entity_id)
    if entry and entry.original_device_class != SensorDeviceClass.ENERGY:
        return False
    state = _state(hass, entity_id)
    if state is None:
        return False
    unit = str(state.attributes.get("unit_of_measurement") or "").strip()
    if unit and unit not in _ENERGY_TO_KWH:
        return False
    return read_energy_kwh(hass, entity_id) is not None or state is not None


def _valid_power_entity(hass: HomeAssistant, entity_id: str) -> bool:
    try:
        domain, _ = split_entity_id(entity_id)
    except ValueError:
        return False
    if domain != "sensor":
        return False
    entry = _entity_registry_entry(hass, entity_id)
    if entry and entry.original_device_class != SensorDeviceClass.POWER:
        return False
    state = _state(hass, entity_id)
    if state is None:
        return False
    unit = str(state.attributes.get("unit_of_measurement") or "").strip()
    if unit and unit not in _POWER_TO_W:
        return False
    return True
