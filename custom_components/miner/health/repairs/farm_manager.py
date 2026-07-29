"""Farm-level repair issues."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from ...const import DOMAIN
from .definitions import (
    FARM_REPAIR_TYPES,
    FARM_REPAIR_DEFINITIONS,
    LEARN_MORE_URL,
    FarmRepairType,
    farm_issue_id,
)
from .lifecycle import RepairLifecycle, monotonic_now
from .membership import format_offline_miner_list
from .registry_sync import sync_open_from_registry


class FarmRepairManager:
    """Repairs for a farm device (aggregate offline members)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.entry_id = entry.entry_id
        self._lifecycle = RepairLifecycle()
        self._open: set[str] = set()
        sync_open_from_registry(
            hass,
            entry.entry_id,
            FARM_REPAIR_TYPES,
            farm_issue_id,
            self._lifecycle,
            self._open,
        )

    @callback
    def process_update(
        self,
        *,
        offline_count: int,
        miner_count: int,
        offline_names: list[str],
    ) -> None:
        now = monotonic_now()
        rtype = FarmRepairType.OFFLINE
        key = farm_issue_id(self.entry_id, rtype)
        raw = offline_count > 0
        confirm = FARM_REPAIR_DEFINITIONS[rtype].confirm_seconds
        name = self.entry.title or "Farm"

        if rtype in self._open:
            if raw:
                self._lifecycle.cancel_recovery(key)
                miners, miners_more = format_offline_miner_list(
                    offline_names, language=getattr(self.hass.config, "language", "en")
                )
                self._create_or_update(
                    rtype,
                    {
                        "name": name,
                        "offline": str(offline_count),
                        "total": str(miner_count),
                        "miners": miners,
                        "miners_more": miners_more,
                    },
                )
            elif self._lifecycle.should_clear(key, False, now):
                ir.async_delete_issue(self.hass, DOMAIN, key)
                self._open.discard(rtype)
                self._lifecycle.reset_key(key)
        elif self._lifecycle.confirmed(key, raw, now, confirm):
            miners, miners_more = format_offline_miner_list(
                offline_names, language=getattr(self.hass.config, "language", "en")
            )
            self._create_or_update(
                rtype,
                {
                    "name": name,
                    "offline": str(offline_count),
                    "total": str(miner_count),
                    "miners": miners,
                    "miners_more": miners_more,
                },
            )
            self._open.add(rtype)

    @callback
    def async_clear_all(self) -> None:
        for rtype in FARM_REPAIR_TYPES:
            ir.async_delete_issue(self.hass, DOMAIN, farm_issue_id(self.entry_id, rtype))
        self._open.clear()
        self._lifecycle.reset_all()

    def dismiss_repair(self, repair_type: str) -> None:
        if repair_type not in FARM_REPAIR_TYPES:
            return
        key = farm_issue_id(self.entry_id, repair_type)
        self._lifecycle.reset_key(key)
        ir.async_delete_issue(self.hass, DOMAIN, key)
        self._open.discard(repair_type)

    def _create_or_update(
        self, rtype: str, placeholders: dict[str, str]
    ) -> None:
        definition = FARM_REPAIR_DEFINITIONS[rtype]
        key = farm_issue_id(self.entry_id, rtype)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            key,
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=definition.translation_key,
            translation_placeholders=placeholders,
            learn_more_url=LEARN_MORE_URL,
            data={
                "entry_id": self.entry_id,
                "scope": "farm",
                "repair_type": rtype,
            },
        )
