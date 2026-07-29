"""Validation helpers for farm composition."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .device_resolution import async_get_miner_config_entry_for_device


def _algorithms_for_member_entries(
    hass: HomeAssistant, device_ids: list[str]
) -> list[str | None]:
    """Return one algorithm (or None if unknown) per unique miner config entry."""
    dev_reg = dr.async_get(hass)
    seen_entries: set[str] = set()
    algorithms: list[str | None] = []
    for did in device_ids:
        device = dev_reg.async_get(did)
        if device is None:
            continue
        entry = async_get_miner_config_entry_for_device(hass, device)
        if entry is None or entry.entry_id in seen_entries:
            continue
        seen_entries.add(entry.entry_id)
        coord = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if coord is None:
            algorithms.append(None)
            continue
        algo = (coord.data or {}).get("algorithm")
        if algo and str(algo).strip():
            algorithms.append(str(algo).strip())
        else:
            algorithms.append(None)
    return algorithms


def reported_algorithms_for_device_ids(
    hass: HomeAssistant, device_ids: list[str]
) -> set[str]:
    """Distinct mining algorithms from member coordinators (incl. last poll)."""
    return {algo for algo in _algorithms_for_member_entries(hass, device_ids) if algo}


def validate_farm_device_algorithms(
    hass: HomeAssistant, device_ids: list[str]
) -> str | None:
    """Return None if composition is allowed, else a config-flow error key."""
    algorithms = _algorithms_for_member_entries(hass, device_ids)
    if not algorithms:
        return None
    if any(algo is None for algo in algorithms):
        return "farm_algorithm_unknown"
    if len(set(algorithms)) > 1:
        return "farm_mixed_algorithms"
    return None
