"""MSKSRV ASIC Miner integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_IP
from .const import CONF_IS_FARM
from .const import DOMAIN
from .farm_coordinator import MinerFarmCoordinator
from .panel import async_setup_sidebar_panel
from .panel import sync_miner_sidebar_panel

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.BUTTON,
]

FARM_PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
]

_SERVICES_SETUP = "services_setup"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Miner integration (global)."""
    hass.data.setdefault(DOMAIN, {})

    if not hass.data[DOMAIN].get("_sidebar_panel_listener"):
        unsub = async_setup_sidebar_panel(hass)
        if unsub is not None:
            hass.data[DOMAIN]["_sidebar_panel_listener"] = unsub

    if not hass.data[DOMAIN].get(_SERVICES_SETUP):
        from .services import async_setup_services

        await async_setup_services(hass)
        hass.data[DOMAIN][_SERVICES_SETUP] = True

    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up Miner from a config entry."""
    if config_entry.data.get(CONF_IS_FARM):
        coordinator = MinerFarmCoordinator(hass, config_entry)
        hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = coordinator
        await coordinator.async_config_entry_first_refresh()

        async def _farm_options_changed(
            hass_inner: HomeAssistant, entry: ConfigEntry
        ) -> None:
            await hass_inner.config_entries.async_reload(entry.entry_id)

        config_entry.async_on_unload(
            config_entry.add_update_listener(_farm_options_changed)
        )

        await hass.config_entries.async_forward_entry_setups(
            config_entry, FARM_PLATFORMS
        )
        sync_miner_sidebar_panel(hass)
        return True

    import pyasic

    from .coordinator import MinerCoordinator

    miner_ip = config_entry.data[CONF_IP]
    miner = await pyasic.get_miner(miner_ip)

    if miner is None:
        raise ConfigEntryNotReady("Miner could not be found.")

    coordinator = MinerCoordinator(hass, config_entry)
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = coordinator

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    async def _sync_sidebar_on_update(
        hass_inner: HomeAssistant, _entry: ConfigEntry
    ) -> None:
        sync_miner_sidebar_panel(hass_inner)

    config_entry.async_on_unload(
        config_entry.add_update_listener(_sync_sidebar_on_update)
    )
    sync_miner_sidebar_panel(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    platforms = FARM_PLATFORMS if config_entry.data.get(CONF_IS_FARM) else PLATFORMS
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, platforms
    )
    if unload_ok:
        hass.data[DOMAIN].pop(config_entry.entry_id, None)
        sync_miner_sidebar_panel(hass)

    return unload_ok
