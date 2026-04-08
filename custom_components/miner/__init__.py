"""MSKSRV ASIC Miner integration."""
from __future__ import annotations

import pyasic
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_IP, DOMAIN
from .coordinator import MinerCoordinator
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.BUTTON,
]

_SERVICES_SETUP = "services_setup"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Miner integration (global)."""
    hass.data.setdefault(DOMAIN, {})

    if not hass.data[DOMAIN].get(_SERVICES_SETUP):
        await async_setup_services(hass)
        hass.data[DOMAIN][_SERVICES_SETUP] = True

    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up Miner from a config entry."""
    miner_ip = config_entry.data[CONF_IP]
    miner = await pyasic.get_miner(miner_ip)

    if miner is None:
        raise ConfigEntryNotReady("Miner could not be found.")

    coordinator = MinerCoordinator(hass, config_entry)
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = coordinator

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    if unload_ok:
        hass.data[DOMAIN].pop(config_entry.entry_id, None)

    return unload_ok
