"""Persist recovery FSM state across HA restarts."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ...const import DOMAIN
from .definitions import STORAGE_VERSION, RecoveryRecord

SAVE_INTERVAL_SECONDS = 60


class RecoveryStorage:
    """HA Store wrapper for recovery state."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.recovery.{entry_id}",
        )
        self._record = RecoveryRecord()
        self._dirty = False
        self._last_save_monotonic = 0.0

    @property
    def record(self) -> RecoveryRecord:
        return self._record

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        if isinstance(raw, dict):
            self._record = RecoveryRecord.from_dict(raw)

    def replace(self, record: RecoveryRecord) -> None:
        self._record = record
        self._dirty = True

    def update(self, **fields: Any) -> None:
        for key, value in fields.items():
            if hasattr(self._record, key):
                setattr(self._record, key, value)
        self._dirty = True

    async def async_save(self, *, force: bool = False) -> None:
        import time

        now = time.monotonic()
        if not force and not self._dirty:
            return
        if (
            not force
            and (now - self._last_save_monotonic) < SAVE_INTERVAL_SECONDS
        ):
            return
        await self._store.async_save(self._record.as_dict())
        self._dirty = False
        self._last_save_monotonic = now

    async def async_remove(self) -> None:
        await self._store.async_remove()
