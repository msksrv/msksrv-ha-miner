"""Service registrations for the Miner integration."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.device_registry import (
    async_get as async_get_device_registry,
)

from .const import (
    DOMAIN,
    SERVICE_REBOOT,
    SERVICE_RESTART_BACKEND,
    SERVICE_SET_FARM_POOL,
    SERVICE_SET_POOL,
    SERVICE_SET_WORK_MODE,
)
from .device_resolution import async_get_farm_config_entry_for_device
from .device_resolution import async_get_miner_config_entry_for_device

LOGGER = logging.getLogger(__name__)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register Miner domain services."""

    async def get_targets(call: ServiceCall):
        hass_devices = hass.data.get(DOMAIN, {})
        miner_ids = call.data.get(CONF_DEVICE_ID)

        if not miner_ids:
            return []

        registry = async_get_device_registry(hass)

        tasks = []
        coordinators = []
        for device_id in miner_ids:
            device = registry.async_get(device_id)
            if not device:
                continue
            entry = async_get_miner_config_entry_for_device(hass, device)
            if entry is None:
                continue
            coordinator = hass_devices.get(entry.entry_id)
            if coordinator is None or not callable(
                getattr(coordinator, "get_miner", None)
            ):
                continue
            tasks.append(coordinator.get_miner())
            coordinators.append(coordinator)

        if not tasks:
            return []

        miners = await asyncio.gather(*tasks)
        return [
            (coordinator, miner)
            for coordinator, miner in zip(coordinators, miners)
            if miner is not None
        ]

    async def reboot(call: ServiceCall) -> None:
        targets = await get_targets(call)
        await asyncio.gather(*(miner.reboot() for _, miner in targets))

    hass.services.async_register(DOMAIN, SERVICE_REBOOT, reboot)

    async def restart_backend(call: ServiceCall) -> None:
        targets = await get_targets(call)
        await asyncio.gather(*(miner.restart_backend() for _, miner in targets))

    hass.services.async_register(DOMAIN, SERVICE_RESTART_BACKEND, restart_backend)

    async def set_work_mode(call: ServiceCall) -> None:
        from pyasic.config.mining import MiningModeConfig

        targets = await get_targets(call)
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

        await asyncio.gather(*(set_mining_mode(miner) for _, miner in targets))

    hass.services.async_register(DOMAIN, SERVICE_SET_WORK_MODE, set_work_mode)

    async def set_pool(call: ServiceCall) -> None:
        from .pool_stratum import async_append_stratum_pool
        from .pool_stratum import async_apply_primary_stratum
        from .pool_stratum import ensure_first_pool_group

        targets = await get_targets(call)
        mode = str(call.data.get("mode", "existing")).lower()
        pool_index = int(call.data.get("pool_index", 0))
        host = call.data.get("host")
        port = call.data.get("port")
        use_ssl_override = call.data.get("use_ssl") if "use_ssl" in call.data else None
        username = call.data.get("username")
        password = call.data.get("password")

        async def apply_pool(coordinator, miner):
            if mode == "existing":
                cfg = await miner.get_config()
                group = ensure_first_pool_group(cfg)

                if not group.pools:
                    LOGGER.error("Cannot set existing pool: miner has no configured pools.")
                    return
                if pool_index < 0 or pool_index >= len(group.pools):
                    LOGGER.error(
                        "Invalid pool_index %s. Available indexes: 0..%s",
                        pool_index,
                        len(group.pools) - 1,
                    )
                    return
                if pool_index != 0:
                    selected = group.pools.pop(pool_index)
                    group.pools.insert(0, selected)
                await miner.send_config(cfg)
            elif mode == "manual":
                if not host or port is None:
                    LOGGER.error("Manual pool mode requires both host and port.")
                    return
                ok = await async_apply_primary_stratum(
                    miner,
                    str(host),
                    int(port),
                    use_ssl_override,
                    username,
                    password,
                )
                if not ok:
                    LOGGER.error("Manual pool: invalid host/port.")
                    return
            elif mode == "append":
                if not host or port is None:
                    LOGGER.error("Append pool mode requires both host and port.")
                    return
                use_ssl = bool(use_ssl_override) if use_ssl_override is not None else False
                ok = await async_append_stratum_pool(
                    miner,
                    str(host),
                    int(port),
                    use_ssl,
                    username,
                    password,
                )
                if not ok:
                    LOGGER.error(
                        "Append pool failed (invalid host/port or max pools reached)."
                    )
                    return
            else:
                LOGGER.error("Unsupported pool mode: %s", mode)
                return

            await coordinator.async_request_refresh()

        await asyncio.gather(*(apply_pool(c, m) for c, m in targets))

    hass.services.async_register(DOMAIN, SERVICE_SET_POOL, set_pool)

    async def set_farm_pool(call: ServiceCall) -> None:
        """Apply the same stratum primary or backup to every miner on a farm device."""
        registry = async_get_device_registry(hass)
        raw_ids = call.data.get(CONF_DEVICE_ID)
        if not raw_ids:
            return
        device_ids = [raw_ids] if isinstance(raw_ids, str) else list(raw_ids)

        mode = str(call.data.get("mode", "manual")).lower()
        replace_primary = mode == "manual"
        if mode not in ("manual", "append"):
            LOGGER.error("set_farm_pool: mode must be manual or append, got %s", mode)
            return

        host = call.data.get("host")
        port = call.data.get("port")
        if not host or port is None:
            LOGGER.error("set_farm_pool: host and port are required")
            return
        try:
            port_int = int(port)
            if port_int < 1 or port_int > 65535:
                raise ValueError
        except (TypeError, ValueError):
            LOGGER.error("set_farm_pool: invalid port")
            return

        use_ssl = call.data.get("use_ssl") if "use_ssl" in call.data else None
        username = call.data.get("username")
        password = call.data.get("password")

        for did in device_ids:
            device = registry.async_get(did)
            if device is None:
                continue
            entry = async_get_farm_config_entry_for_device(hass, device)
            if entry is None:
                LOGGER.warning(
                    "set_farm_pool: device %s is not a miner farm device", did
                )
                continue
            coord = hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if coord is None or not hasattr(coord, "async_apply_stratum_to_members"):
                LOGGER.warning("set_farm_pool: farm entry %s is not loaded", entry.title)
                continue
            ok, err_key = await coord.async_apply_stratum_to_members(
                device_ids=None,
                replace_primary=replace_primary,
                host=str(host).strip(),
                port=port_int,
                use_ssl=use_ssl,
                username=username,
                password=password,
            )
            if not ok:
                LOGGER.error(
                    "set_farm_pool for %s failed: %s",
                    entry.title,
                    err_key or "unknown",
                )

    hass.services.async_register(DOMAIN, SERVICE_SET_FARM_POOL, set_farm_pool)
