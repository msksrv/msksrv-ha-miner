"""Reconcile in-memory repair state with Home Assistant Issue Registry."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from ...const import DOMAIN
from .lifecycle import RepairLifecycle, monotonic_now


def sync_open_from_registry(
    hass: HomeAssistant,
    entry_id: str,
    repair_types: tuple[str, ...],
    issue_id_fn: Callable[[str, str], str],
    lifecycle: RepairLifecycle,
    open_set: set[str],
) -> None:
    """Seed ``open_set`` and lifecycle from issues that survived reload."""
    reg = ir.async_get(hass)
    now = monotonic_now()
    for rtype in repair_types:
        key = issue_id_fn(entry_id, rtype)
        issue = reg.async_get_issue(DOMAIN, key)
        if issue is None:
            continue
        open_set.add(rtype)
        lifecycle.seed_open_issue(key, now)
