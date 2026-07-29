"""Support for Miner shutdown."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MinerCoordinator
from .device_resolution import miner_entity_unique_suffix
from .miner_device_info import get_miner_device_info

_LOGGER = logging.getLogger(__name__)


def _mining_mode_from_data(config) -> object | None:
    """Read mining_mode from pyasic config or offline placeholder dict."""
    if config is None:
        return None
    if isinstance(config, dict):
        return config.get("mining_mode")
    return getattr(config, "mining_mode", None)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    coordinator: MinerCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    miner = await coordinator.get_miner()
    if miner is not None and miner.supports_shutdown:
        async_add_entities(
            [
                MinerActiveSwitch(
                    coordinator=coordinator,
                )
            ]
        )


class MinerActiveSwitch(CoordinatorEntity[MinerCoordinator], SwitchEntity):
    """Defines a Miner Switch to pause and unpause the miner."""

    _attr_has_entity_name = True
    _attr_translation_key = "mining_active"
    _attr_icon = "mdi:pickaxe"

    def __init__(
        self,
        coordinator: MinerCoordinator,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator=coordinator)
        suffix = miner_entity_unique_suffix(
            coordinator.config_entry, coordinator.data.get("mac")
        )
        self._attr_unique_id = f"{suffix}-active"
        self._attr_is_on = self.coordinator.data["is_mining"]
        self.updating_switch = False
        self._last_mining_mode = _mining_mode_from_data(
            coordinator.data.get("config")
        )

    @property
    def device_info(self) -> entity.DeviceInfo:
        """Return device info."""
        return get_miner_device_info(self.coordinator)

    async def async_turn_on(self) -> None:
        """Turn on miner."""
        miner = self.coordinator.miner
        _LOGGER.debug(f"{self.coordinator.config_entry.title}: Resume mining.")
        if not miner.supports_shutdown:
            raise TypeError(f"{miner}: Shutdown not supported.")
        self._attr_is_on = True
        await miner.resume_mining()
        if miner.supports_power_modes and self._last_mining_mode is not None:
            config = await miner.get_config()
            config.mining_mode = self._last_mining_mode
            await miner.send_config(config)
        self.updating_switch = True
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        """Turn off miner."""
        miner = self.coordinator.miner
        _LOGGER.debug(f"{self.coordinator.config_entry.title}: Stop mining.")
        if not miner.supports_shutdown:
            raise TypeError(f"{miner}: Shutdown not supported.")
        if miner.supports_power_modes:
            self._last_mining_mode = _mining_mode_from_data(
                self.coordinator.data.get("config")
            )
        self._attr_is_on = False
        await miner.stop_mining()
        self.updating_switch = True
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        is_mining = self.coordinator.data["is_mining"]
        if is_mining is not None:
            if self.updating_switch and is_mining == self._attr_is_on:
                self.updating_switch = False
            if not self.updating_switch:
                self._attr_is_on = is_mining

        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        """Return if entity is available or not."""
        return self.coordinator.available
