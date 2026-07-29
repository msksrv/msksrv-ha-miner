"""Persist energy totals across HA restarts."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ..const import DOMAIN
from .definitions import SAVE_INTERVAL_SECONDS, STORAGE_VERSION, EnergyRecord


class EnergyStore(Store[dict[str, Any]]):
    """Energy storage with backward-compatible migration."""

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        if old_major_version in (2, 3):
            return old_data if isinstance(old_data, dict) else {}
        raise NotImplementedError(
            f"Unsupported energy store version {old_major_version}.{old_minor_version}"
        )


class EnergyStorage:
    """HA Store wrapper for energy accumulator state."""

    def __init__(self, hass: HomeAssistant, key: str) -> None:
        self._store = EnergyStore(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.energy.{key}",
        )
        self._record = EnergyRecord()
        self._dirty = False
        self._last_save_monotonic = 0.0

    @property
    def record(self) -> EnergyRecord:
        return self._record

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        if isinstance(raw, dict):
            self._record = EnergyRecord.from_dict(raw)

    def replace(self, record: EnergyRecord) -> None:
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
        if not force and (now - self._last_save_monotonic) < SAVE_INTERVAL_SECONDS:
            return
        await self._store.async_save(self._record.as_dict())
        self._dirty = False
        self._last_save_monotonic = now

    async def async_remove(self) -> None:
        await self._store.async_remove()

    def mark_dirty(self) -> None:
        self._dirty = True
