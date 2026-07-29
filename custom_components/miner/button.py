"""Support for Miner action buttons."""
from __future__ import annotations

from typing import TYPE_CHECKING, cast

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_IS_FARM, CONF_POWER_SWITCH, DOMAIN
from .device_resolution import miner_entity_unique_suffix
from .farm_button import async_setup_farm_buttons
from .miner_device_info import get_miner_device_info

if TYPE_CHECKING:
    from .coordinator import MinerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Miner button entities."""
    if config_entry.data.get(CONF_IS_FARM):
        await async_setup_farm_buttons(hass, config_entry, async_add_entities)
        return

    from .coordinator import MinerCoordinator

    coordinator = cast(
        MinerCoordinator, hass.data[DOMAIN][config_entry.entry_id]
    )
    async_add_entities(
        [
            MinerRebootButton(coordinator=coordinator),
            MinerPowerOffButton(coordinator=coordinator),
            MinerPowerOnButton(coordinator=coordinator),
            MinerBaselineResetButton(coordinator=coordinator),
            MinerBaselineAcceptButton(coordinator=coordinator),
        ]
    )


class MinerRebootButton(CoordinatorEntity["MinerCoordinator"], ButtonEntity):
    """Button to reboot a miner."""

    _attr_has_entity_name = True
    _attr_translation_key = "reboot"
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(coordinator=coordinator)
        suffix = miner_entity_unique_suffix(
            coordinator.config_entry, coordinator.data.get("mac")
        )
        self._attr_unique_id = f"{suffix}-reboot"

    @property
    def device_info(self) -> entity.DeviceInfo:
        return get_miner_device_info(self.coordinator)

    async def async_press(self) -> None:
        """Handle button press."""
        self.coordinator.baseline.notify_reboot()
        await self.coordinator.miner.reboot()

    @property
    def available(self) -> bool:
        return self.coordinator.available


class _MinerLinkedSwitchButton(CoordinatorEntity["MinerCoordinator"], ButtonEntity):
    """Shared: linked HA switch from integration options (on/off power strip)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(coordinator=coordinator)

    @property
    def device_info(self) -> entity.DeviceInfo:
        return get_miner_device_info(self.coordinator)

    @property
    def _power_switch_entity_id(self) -> str | None:
        eid = self.coordinator.config_entry.options.get(CONF_POWER_SWITCH)
        return str(eid).strip() if eid else None

    @property
    def available(self) -> bool:
        eid = self._power_switch_entity_id
        if not eid:
            return False
        return self.hass.states.get(eid) is not None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        async def _entry_updated(_hass: HomeAssistant, entry: ConfigEntry) -> None:
            if entry.entry_id == self.coordinator.config_entry.entry_id:
                self.async_write_ha_state()

        self.async_on_remove(
            self.coordinator.config_entry.add_update_listener(_entry_updated)
        )


class MinerPowerOffButton(_MinerLinkedSwitchButton):
    """Turn off the linked smart switch (cuts power to the miner)."""

    _attr_translation_key = "power_off"
    _attr_icon = "mdi:power-plug-off"

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(coordinator)
        suffix = miner_entity_unique_suffix(
            coordinator.config_entry, coordinator.data.get("mac")
        )
        self._attr_unique_id = f"{suffix}-power-off"

    async def async_press(self) -> None:
        eid = self._power_switch_entity_id
        if not eid:
            return
        await self.hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": eid},
            blocking=False,
        )


class MinerPowerOnButton(_MinerLinkedSwitchButton):
    """Turn on the linked smart switch (restore power to the miner)."""

    _attr_translation_key = "power_on"
    _attr_icon = "mdi:power-plug"

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(coordinator)
        suffix = miner_entity_unique_suffix(
            coordinator.config_entry, coordinator.data.get("mac")
        )
        self._attr_unique_id = f"{suffix}-power-on"

    async def async_press(self) -> None:
        eid = self._power_switch_entity_id
        if not eid:
            return
        await self.hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": eid},
            blocking=False,
        )


class MinerBaselineResetButton(CoordinatorEntity["MinerCoordinator"], ButtonEntity):
    """Clear learned baseline statistics."""

    _attr_has_entity_name = True
    _attr_translation_key = "baseline_reset"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:chart-timeline-variant-shimmer"

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(coordinator=coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}-baseline-reset"

    @property
    def device_info(self) -> entity.DeviceInfo:
        return get_miner_device_info(self.coordinator)

    async def async_press(self) -> None:
        self.coordinator.baseline.reset_all()
        await self.coordinator.baseline.async_save(force=True)
        await self.coordinator.async_request_refresh()

    @property
    def available(self) -> bool:
        return self.coordinator.available


class MinerBaselineAcceptButton(CoordinatorEntity["MinerCoordinator"], ButtonEntity):
    """Accept current readings as normal baseline."""

    _attr_has_entity_name = True
    _attr_translation_key = "baseline_accept"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:check-decagram"

    def __init__(self, coordinator: MinerCoordinator) -> None:
        super().__init__(coordinator=coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}-baseline-accept"

    @property
    def device_info(self) -> entity.DeviceInfo:
        return get_miner_device_info(self.coordinator)

    async def async_press(self) -> None:
        self.coordinator.baseline.accept_current(dict(self.coordinator.data))
        await self.coordinator.baseline.async_save(force=True)
        await self.coordinator.async_request_refresh()

    @property
    def available(self) -> bool:
        return self.coordinator.available and bool(self.coordinator.data.get("is_mining"))
