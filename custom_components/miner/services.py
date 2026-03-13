"""Service registrations for the Miner integration."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.device_registry import (
    async_get as async_get_device_registry,
)
from pyasic.config.mining import MiningModeConfig

from .const import DOMAIN, SERVICE_REBOOT, SERVICE_RESTART_BACKEND, SERVICE_SET_WORK_MODE

LOGGER = logging.getLogger(__name__)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register Miner domain services."""

    async def get_miners(call: ServiceCall):
        hass_devices = hass.data.get(DOMAIN, {})
        miner_ids = call.data.get(CONF_DEVICE_ID)

        if not miner_ids:
            return []

        registry = async_get_device_registry(hass)

        tasks = []
        for device_id in miner_ids:
            device = registry.async_get(device_id)
            if device and device.primary_config_entry in hass_devices:
                coordinator = hass_devices[device.primary_config_entry]
                tasks.append(coordinator.get_miner())

        if not tasks:
            return []

        return await asyncio.gather(*tasks)

    async def reboot(call: ServiceCall) -> None:
        miners = await get_miners(call)
        await asyncio.gather(*(miner.reboot() for miner in miners if miner is not None))

    hass.services.async_register(DOMAIN, SERVICE_REBOOT, reboot)

    async def restart_backend(call: ServiceCall) -> None:
        miners = await get_miners(call)
        await asyncio.gather(
            *(miner.restart_backend() for miner in miners if miner is not None)
        )

    hass.services.async_register(DOMAIN, SERVICE_RESTART_BACKEND, restart_backend)

    async def set_work_mode(call: ServiceCall) -> None:
        miners = await get_miners(call)
        mode = call.data.get("mode", "high")

        async def set_mining_mode(miner):
            cfg_mode = MiningModeConfig.default()
            if mode == "high":
                cfg_mode = MiningModeConfig.high()
            elif mode == "normal":
                cfg_mode = MiningModeConfig.normal()
            elif mode == "low":
                cfg_mode = MiningModeConfig.low()

            cfg = await miner.get_config()
            cfg.mining_mode = cfg_mode
            await miner.send_config(cfg)

        await asyncio.gather(
            *(set_mining_mode(miner) for miner in miners if miner is not None)
        )

    hass.services.async_register(DOMAIN, SERVICE_SET_WORK_MODE, set_work_mode)
