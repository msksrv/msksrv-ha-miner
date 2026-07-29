"""Shared miner command helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .coordinator import MinerCoordinator


async def async_send_reboot_command(coordinator: MinerCoordinator) -> None:
    """Reboot miner and emit reboot_command_sent when the command succeeds."""
    if coordinator.miner is None:
        miner = await coordinator.get_miner()
        if miner is None:
            raise RuntimeError("Miner unavailable")
        coordinator.miner = miner
    await coordinator.miner.reboot()
    coordinator.baseline.notify_reboot()
    coordinator.events.async_emit_reboot_command_sent()
