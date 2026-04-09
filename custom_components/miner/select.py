"""Selector entities for miner (power mode, pool priority)."""
from __future__ import annotations

import logging

import pyasic
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from pyasic.config.mining import MiningModeHPM, MiningModeLPM, MiningModeNormal
from pyasic.config.pools import PoolGroup

from .const import CONF_IS_FARM
from .const import DOMAIN
from .miner_device_info import get_miner_device_info
from .coordinator import MinerCoordinator

_LOGGER = logging.getLogger(__name__)

_POWER_MODE_OPTIONS = ("Normal", "High", "Low")


def _power_mode_current_option(
    config: pyasic.MinerConfig | dict | None,
) -> str | None:
    """Map pyasic mining_mode to select option; None if not low/normal/high tri-state."""
    if config is None or not isinstance(config, pyasic.MinerConfig):
        return None
    mm = getattr(config, "mining_mode", None)
    if isinstance(mm, MiningModeNormal):
        return "Normal"
    if isinstance(mm, MiningModeLPM):
        return "Low"
    if isinstance(mm, MiningModeHPM):
        return "High"
    return None


def _power_mode_state_label(config: pyasic.MinerConfig | dict | None) -> str | None:
    """When not in low/normal/high, show current pyasic mode for the select UI."""
    if not isinstance(config, pyasic.MinerConfig):
        return None
    if _power_mode_current_option(config) is not None:
        return None
    mm = getattr(config, "mining_mode", None)
    if mm is None:
        return None
    mode = getattr(mm, "mode", None)
    if mode is None:
        return None
    return str(mode).replace("_", " ").title()


def _first_pool_group(cfg: pyasic.MinerConfig) -> PoolGroup:
    if not cfg.pools.groups:
        cfg.pools.groups = [PoolGroup(pools=[])]
    return cfg.pools.groups[0]


def _pool_option_labels(config: pyasic.MinerConfig) -> list[str]:
    """Build unique select labels for pools in the primary group (order = miner priority)."""
    try:
        groups = config.pools.groups
        if not groups:
            return []
        pools = groups[0].pools
    except (AttributeError, IndexError, TypeError):
        return []
    labels: list[str] = []
    for i, pool in enumerate(pools):
        url = str(getattr(pool, "url", "") or "")
        short = url.replace("stratum+tcp://", "").replace("stratum+ssl://", "")
        if len(short) > 52:
            short = f"{short[:49]}..."
        labels.append(f"{i + 1}: {short}" if short else f"{i + 1}: —")
    return labels


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Miner select entities."""
    if config_entry.data.get(CONF_IS_FARM):
        from .farm_select import async_setup_farm_selects

        await async_setup_farm_selects(hass, config_entry, async_add_entities)
        return

    coordinator: MinerCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    await coordinator.async_config_entry_first_refresh()
    to_add: list[SelectEntity] = [MinerPoolPrioritySelect(coordinator=coordinator)]
    if (
        coordinator.miner.supports_power_modes
        and not coordinator.miner.supports_autotuning
    ):
        to_add.append(MinerPowerModeSelect(coordinator=coordinator))
    async_add_entities(to_add)


class MinerPowerModeSelect(CoordinatorEntity[MinerCoordinator], SelectEntity):
    """Select entity for miner power mode."""

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(coordinator=coordinator)
        self._attr_unique_id = f"{self.coordinator.data['mac']}-power-mode"

    @property
    def name(self) -> str | None:
        return f"{self.coordinator.config_entry.title} power mode"

    @property
    def device_info(self) -> entity.DeviceInfo:
        return get_miner_device_info(self.coordinator)

    @property
    def options(self) -> list[str]:
        cfg = self.coordinator.data.get("config")
        extra = _power_mode_state_label(cfg)
        base = list(_POWER_MODE_OPTIONS)
        if extra and extra not in base:
            return [extra, *base]
        return base

    @property
    def current_option(self) -> str | None:
        cfg = self.coordinator.data.get("config")
        tri = _power_mode_current_option(cfg)
        if tri is not None:
            return tri
        return _power_mode_state_label(cfg)

    async def async_select_option(self, option: str) -> None:
        if option not in _POWER_MODE_OPTIONS:
            _LOGGER.debug("Power mode: ignoring non-action option %r", option)
            return
        option_map = {
            "High": MiningModeHPM,
            "Normal": MiningModeNormal,
            "Low": MiningModeLPM,
        }
        cfg = await self.coordinator.miner.get_config()
        cfg.mining_mode = option_map[option]()
        await self.coordinator.miner.send_config(cfg)
        await self.coordinator.async_request_refresh()


class MinerPoolPrioritySelect(CoordinatorEntity[MinerCoordinator], SelectEntity):
    """Select which configured pool slot is primary (first in list)."""

    _attr_has_entity_name = True
    _attr_translation_key = "pool_priority"
    _attr_icon = "mdi:swap-horizontal"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(coordinator=coordinator)
        self._attr_unique_id = f"{self.coordinator.data['mac']}-pool-priority"

    @property
    def device_info(self) -> entity.DeviceInfo:
        return get_miner_device_info(self.coordinator)

    @property
    def options(self) -> list[str]:
        cfg = self.coordinator.data.get("config")
        if not isinstance(cfg, pyasic.MinerConfig):
            return []
        return _pool_option_labels(cfg)

    @property
    def current_option(self) -> str | None:
        opts = self.options
        return opts[0] if opts else None

    @property
    def available(self) -> bool:
        return bool(
            super().available
            and self.coordinator.miner is not None
            and len(self.options) >= 2
        )

    async def async_select_option(self, option: str) -> None:
        opts = self.options
        if option not in opts:
            _LOGGER.warning("Unknown pool option: %s", option)
            return
        pool_index = opts.index(option)
        if pool_index == 0:
            return
        miner = self.coordinator.miner
        if miner is None:
            return
        cfg = await miner.get_config()
        group = _first_pool_group(cfg)
        if pool_index < 0 or pool_index >= len(group.pools):
            return
        selected = group.pools.pop(pool_index)
        group.pools.insert(0, selected)
        await miner.send_config(cfg)
        await self.coordinator.async_request_refresh()
