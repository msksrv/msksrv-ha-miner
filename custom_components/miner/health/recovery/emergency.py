"""Farm emergency stop latch — persisted across loaded/unloaded miners."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .definitions import EMERGENCY_STOP_COOLDOWN_SECONDS, RecoveryRecord, RecoveryState
from .policy import apply_cooldown
from .storage import RecoveryStorage

_LOGGER = logging.getLogger(__name__)


def latched_record(existing: RecoveryRecord | None = None) -> RecoveryRecord:
    """Build a recovery record latched by farm emergency stop."""
    base = existing or RecoveryRecord()
    record = RecoveryRecord(
        emergency_stop_latched=True,
        state=RecoveryState.IDLE,
        wait_until=None,
        config_block_until=base.config_block_until,
    )
    apply_cooldown(record, EMERGENCY_STOP_COOLDOWN_SECONDS)
    return record


async def async_latch_emergency_stop(hass: HomeAssistant, entry_id: str) -> None:
    """Persist emergency stop latch for one miner (loaded or not)."""
    storage = RecoveryStorage(hass, entry_id)
    await storage.async_load()
    storage.replace(latched_record(storage.record))
    await storage.async_save(force=True)


async def async_clear_emergency_latch(hass: HomeAssistant, entry_id: str) -> None:
    """Clear emergency stop latch after explicit farm confirmation."""
    storage = RecoveryStorage(hass, entry_id)
    await storage.async_load()
    if not storage.record.emergency_stop_latched:
        return
    record = storage.record
    record.emergency_stop_latched = False
    record.cooldown_until = None
    storage._dirty = True
    await storage.async_save(force=True)


async def async_entry_emergency_latched(hass: HomeAssistant, entry_id: str) -> bool:
    storage = RecoveryStorage(hass, entry_id)
    await storage.async_load()
    return bool(storage.record.emergency_stop_latched)
