"""Shared DeviceInfo for single-miner entities (incl. web UI link on device card)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers import device_registry
from homeassistant.helpers import entity

from .const import CONF_IP
from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import MinerCoordinator


def get_miner_device_info(coordinator: MinerCoordinator) -> entity.DeviceInfo:
    """Device registry row + ``configuration_url`` → link on the HA device page (like ESPHome)."""
    data = coordinator.data
    entry = coordinator.config_entry
    ip = data.get("ip") or entry.data.get(CONF_IP)
    if ip is not None:
        ip = str(ip).strip() or None
    mac = data.get("mac")

    connections: set[tuple[str, str]] = set()
    if ip:
        connections.add(("ip", ip))
    if mac:
        connections.add((device_registry.CONNECTION_NETWORK_MAC, mac))

    return entity.DeviceInfo(
        identifiers={(DOMAIN, mac)},
        connections=connections if connections else None,
        configuration_url=f"http://{ip}" if ip else None,
        manufacturer=data.get("make"),
        model=data.get("model"),
        sw_version=data.get("fw_ver"),
        name=entry.title,
    )
