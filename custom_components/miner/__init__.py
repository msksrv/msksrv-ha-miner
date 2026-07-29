"""MSKSRV ASIC Miner integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .const import CONF_IS_FARM, DOMAIN

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
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

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Miner integration (global)."""
    hass.data.setdefault(DOMAIN, {})

    if not hass.data[DOMAIN].get(_SERVICES_SETUP):
        from .services import async_setup_services

        await async_setup_services(hass)
        hass.data[DOMAIN][_SERVICES_SETUP] = True

    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up Miner from a config entry."""
    if config_entry.data.get(CONF_IS_FARM):
        from .farm_coordinator import MinerFarmCoordinator

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
        return True

    from homeassistant.helpers.update_coordinator import UpdateFailed

    from .coordinator import MinerCoordinator

    coordinator = MinerCoordinator(hass, config_entry)
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = coordinator
    await coordinator.baseline.async_load()

    try:
        await coordinator.async_config_entry_first_refresh()
    except UpdateFailed as err:
        raise ConfigEntryNotReady(str(err)) from err

    from .entity_migration import async_migrate_mac_unique_id_duplicates

    await async_migrate_mac_unique_id_duplicates(
        hass, config_entry, coordinator.data.get("mac")
    )

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    platforms = FARM_PLATFORMS if config_entry.data.get(CONF_IS_FARM) else PLATFORMS
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, platforms
    )
    if unload_ok:
        coord = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
        if coord is not None and hasattr(coord, "baseline"):
            await coord.baseline.async_save(force=True)
        hass.data[DOMAIN].pop(config_entry.entry_id, None)

    return unload_ok
