"""Buttons for a farm device."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .farm_coordinator import MinerFarmCoordinator
from .farm_pool_presets import farm_pool_preset_slots
from .farm_pool_ui import resolve_farm_pool_slot_from_dashboard

_LOGGER = logging.getLogger(__name__)


async def async_setup_farm_buttons(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create farm action buttons."""
    coordinator: MinerFarmCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        [
            FarmEmergencyStopButton(coordinator),
            FarmApplyPoolButton(coordinator, replace_primary=True),
            FarmApplyPoolButton(coordinator, replace_primary=False),
        ]
    )


class FarmEmergencyStopButton(CoordinatorEntity[MinerFarmCoordinator], ButtonEntity):
    """Turn off all smart switches linked on member miners (power cut)."""

    _attr_has_entity_name = True
    _attr_translation_key = "farm_emergency_stop"
    _attr_icon = "mdi:electric-switch-closed"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: MinerFarmCoordinator) -> None:
        super().__init__(coordinator=coordinator)
        self._attr_unique_id = f"farm-{coordinator.config_entry.entry_id}-emergency-stop"

    @property
    def device_info(self) -> entity.DeviceInfo:
        return entity.DeviceInfo(
            identifiers={(DOMAIN, f"farm_{self.coordinator.config_entry.entry_id}")},
            name=self.coordinator.config_entry.title,
            manufacturer="MSKSRV",
            model="Farm",
        )

    @property
    def available(self) -> bool:
        return bool(self.coordinator.data.get("emergency_stop_available"))

    async def async_press(self) -> None:
        await self.coordinator.async_emergency_power_off()


class FarmApplyPoolButton(CoordinatorEntity[MinerFarmCoordinator], ButtonEntity):
    """Apply the selected saved stratum preset to all farm members."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:earth-arrow-right"

    def __init__(
        self, coordinator: MinerFarmCoordinator, *, replace_primary: bool
    ) -> None:
        super().__init__(coordinator=coordinator)
        self._replace_primary = replace_primary
        if replace_primary:
            self._attr_translation_key = "farm_apply_pool_primary"
            suffix = "apply-pool-primary"
        else:
            self._attr_translation_key = "farm_apply_pool_append"
            suffix = "apply-pool-append"
        self._attr_unique_id = f"farm-{coordinator.config_entry.entry_id}-{suffix}"

    @property
    def device_info(self) -> entity.DeviceInfo:
        return entity.DeviceInfo(
            identifiers={(DOMAIN, f"farm_{self.coordinator.config_entry.entry_id}")},
            name=self.coordinator.config_entry.title,
            manufacturer="MSKSRV",
            model="Farm",
        )

    @property
    def available(self) -> bool:
        slots = farm_pool_preset_slots(self.coordinator.config_entry.options)
        return bool(super().available and any(s.get("host") for s in slots))

    async def async_press(self) -> None:
        slot = resolve_farm_pool_slot_from_dashboard(
            self.hass,
            self.coordinator,
        )
        if slot < 0:
            _LOGGER.warning("Farm has no saved pool preset to apply")
            return
        ok, err_key = await self.coordinator.async_apply_saved_preset_slot(
            slot,
            replace_primary=self._replace_primary,
            device_ids=None,
        )
        if not ok:
            _LOGGER.error("Farm apply pool failed: %s", err_key or "unknown")
