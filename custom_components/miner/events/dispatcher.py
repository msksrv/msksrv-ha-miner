"""Dispatch events to HA event entities and the miner_event bus."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from ..const import CONF_IS_FARM, DOMAIN

if TYPE_CHECKING:
    from homeassistant.components.event import EventEntity


def _device_id_for_entry(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    dev_reg = dr.async_get(hass)
    if entry.data.get(CONF_IS_FARM):
        device = dev_reg.async_get_device(identifiers={(DOMAIN, f"farm_{entry.entry_id}")})
    else:
        device = dev_reg.async_get_devices_for_config_entry(entry.entry_id)
        device = device[0] if device else None
    return device.id if device else None


class EventDispatcher:
    """Fire scoped activity events on entity + integration bus."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        scope: str,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.scope = scope
        self._entity: EventEntity | None = None

    def bind_entity(self, entity: EventEntity) -> None:
        """Attach the platform event entity."""
        self._entity = entity

    @callback
    def async_emit(self, event_type: str, event_data: dict[str, Any] | None = None) -> None:
        """Trigger event entity and miner_event bus."""
        data = dict(event_data or {})
        data.setdefault("event_type", event_type)
        if self._entity is not None:
            trigger = getattr(self._entity, "async_trigger", None)
            if callable(trigger):
                trigger(event_type, data)

        bus_payload = {
            "device_id": _device_id_for_entry(self.hass, self.entry),
            "entry_id": self.entry.entry_id,
            "scope": self.scope,
            "type": event_type,
            "name": self.entry.title,
            **data,
        }
        self.hass.bus.async_fire("miner_event", bus_payload)
