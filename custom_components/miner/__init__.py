"""MSKSRV ASIC Miner integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .const import CONF_IS_FARM, DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.BUTTON,
    Platform.EVENT,
]

FARM_PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.EVENT,
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
        await coordinator.async_refresh_emergency_stop_cache()
        await coordinator.energy.async_load()
        from .farm_cost_migration import async_apply_legacy_farm_cost_registry

        await async_apply_legacy_farm_cost_registry(hass, config_entry)
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
    await coordinator.recovery.async_load()
    await coordinator.energy.async_load()

    try:
        await coordinator.async_config_entry_first_refresh()
    except UpdateFailed as err:
        raise ConfigEntryNotReady(str(err)) from err

    from .entity_migration import async_migrate_mac_unique_id_duplicates

    await async_migrate_mac_unique_id_duplicates(
        hass, config_entry, coordinator.data.get("mac")
    )

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    async def _miner_options_changed(
        hass_inner: HomeAssistant, entry: ConfigEntry
    ) -> None:
        coord = hass_inner.data.get(DOMAIN, {}).get(entry.entry_id)
        if coord is None:
            return
        if hasattr(coord, "energy"):
            coord.energy.reload_options()
        if hasattr(coord, "recovery"):
            coord.recovery.reload_options()

    config_entry.async_on_unload(
        config_entry.add_update_listener(_miner_options_changed)
    )

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    platforms = FARM_PLATFORMS if config_entry.data.get(CONF_IS_FARM) else PLATFORMS
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, platforms
    )
    if unload_ok:
        coord = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
        if coord is not None:
            if hasattr(coord, "baseline"):
                await coord.baseline.async_save(force=True)
            if hasattr(coord, "recovery"):
                await coord.recovery.async_prepare_unload()
            if hasattr(coord, "energy"):
                await coord.energy.async_save(force=True)
        hass.data[DOMAIN].pop(config_entry.entry_id, None)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Remove repair issues only when the config entry is deleted."""
    from homeassistant.helpers import issue_registry as ir

    from .health.repairs.definitions import (
        ALL_MINER_REPAIR_TYPES,
        FARM_REPAIR_TYPES,
        farm_issue_id,
        miner_issue_id,
    )

    if config_entry.data.get(CONF_IS_FARM):
        from .energy.farm_manager import FarmEnergyManager

        await FarmEnergyManager(hass, config_entry.entry_id).async_remove()
        for rtype in FARM_REPAIR_TYPES:
            ir.async_delete_issue(
                hass, DOMAIN, farm_issue_id(config_entry.entry_id, rtype)
            )
        return

    for rtype in ALL_MINER_REPAIR_TYPES:
        ir.async_delete_issue(
            hass, DOMAIN, miner_issue_id(config_entry.entry_id, rtype)
        )

    from .health.baseline.manager import BaselineManager
    from .health.recovery.actions import async_power_on
    from .health.recovery.definitions import POWER_CRITICAL_STATES
    from .health.recovery.storage import RecoveryStorage
    from .const import CONF_POWER_SWITCH

    from .energy.storage import EnergyStorage

    storage = RecoveryStorage(hass, config_entry.entry_id)
    await storage.async_load()
    if storage.record.emergency_stop_latched:
        await storage.async_remove()
        await BaselineManager(hass, config_entry.entry_id).async_remove()
        await EnergyStorage(hass, config_entry.entry_id).async_remove()
        return

    if storage.record.state in POWER_CRITICAL_STATES:
        switch = config_entry.options.get(CONF_POWER_SWITCH)
        if switch:
            restored = await async_power_on(hass, str(switch).strip())
            if not restored:
                _LOGGER.error(
                    "Could not restore power for %s before entry removal; "
                    "keeping recovery store",
                    config_entry.title,
                )
                await BaselineManager(hass, config_entry.entry_id).async_remove()
                return

    await EnergyStorage(hass, config_entry.entry_id).async_remove()
    await BaselineManager(hass, config_entry.entry_id).async_remove()
    await storage.async_remove()
