"""Validation helpers for farm composition."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_FARM_DEVICE_IDS, DOMAIN
from .device_resolution import async_get_miner_config_entry_for_device


def farm_member_field(
    hass: HomeAssistant, suggested: str | list[str] | None
) -> dict[vol.Required, SelectSelector]:
    """Offer only devices backed by a single-miner config entry."""
    options: list[SelectOptionDict] = []
    for device in dr.async_get(hass).devices.values():
        entry = async_get_miner_config_entry_for_device(hass, device)
        if entry is not None:
            options.append(
                {
                    "value": device.id,
                    "label": device.name_by_user or device.name or entry.title,
                }
            )
    options.sort(key=lambda option: (option["label"].casefold(), option["value"]))

    allowed = {option["value"] for option in options}
    selected = [suggested] if isinstance(suggested, str) else suggested or []
    field = vol.Required(
        CONF_FARM_DEVICE_IDS,
        description={
            "suggested_value": [
                device_id for device_id in selected if device_id in allowed
            ]
        },
    )
    return {
        field: SelectSelector(
            SelectSelectorConfig(
                options=options, multiple=True, mode=SelectSelectorMode.DROPDOWN
            )
        )
    }


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
