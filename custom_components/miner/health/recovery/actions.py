"""Recovery reboot and power-cycle command execution."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ...coordinator import MinerCoordinator
    from ...events.manager import MinerEventManager

_LOGGER = logging.getLogger(__name__)

SWITCH_VERIFY_TIMEOUT = 45
SWITCH_POLL_INTERVAL = 1.0


async def async_send_recovery_reboot(coordinator: MinerCoordinator) -> None:
    """Reboot miner for auto-recovery without manual cooldown side-effects."""
    from ...miner_actions import async_send_reboot_command

    await async_send_reboot_command(coordinator, manual=False)


async def async_set_switch(
    hass: HomeAssistant,
    entity_id: str,
    *,
    turn_on: bool,
    timeout: float = SWITCH_VERIFY_TIMEOUT,
) -> bool:
    """Turn a switch on/off and verify the state changed."""
    service = "turn_on" if turn_on else "turn_off"
    expected = "on" if turn_on else "off"
    try:
        await hass.services.async_call(
            "switch",
            service,
            {"entity_id": entity_id},
            blocking=True,
        )
    except Exception:
        _LOGGER.exception(
            "Switch %s failed for %s", service, entity_id
        )
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = hass.states.get(entity_id)
        if state is not None and state.state == expected:
            return True
        await asyncio.sleep(SWITCH_POLL_INTERVAL)
    return False


async def async_power_off(
    hass: HomeAssistant,
    entity_id: str,
) -> bool:
    return await async_set_switch(hass, entity_id, turn_on=False)


async def async_power_on(
    hass: HomeAssistant,
    entity_id: str,
) -> bool:
    return await async_set_switch(hass, entity_id, turn_on=True)
