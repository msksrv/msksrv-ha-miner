"""Network discovery helpers for Miner."""
from __future__ import annotations

import asyncio
import ipaddress
import logging
from dataclasses import dataclass

import pyasic

from .const import (
    SCAN_CONCURRENCY,
    SCAN_MAX_HOSTS,
    SCAN_MINER_TIMEOUT,
    SCAN_PORTS,
    SCAN_TCP_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class DiscoveredMiner:
    """Basic info about a discovered miner."""

    ip: str
    model: str
    manufacturer: str
    hostname: str | None
    unique_key: str
    open_ports: tuple[int, ...]


def normalize_model_name(miner) -> str:
    """Return friendly miner / firmware model name."""
    try:
        raw_model = str(getattr(miner, "model", "") or "").strip()
        raw_type = str(getattr(miner, "type", "") or "").strip()
        raw_make = str(getattr(miner, "make", "") or "").strip()

        text = " ".join(x for x in [raw_make, raw_model, raw_type] if x).lower()

        if "antminer" in text:
            return raw_model or "Antminer"
        if "whatsminer" in text:
            return raw_model or "WhatsMiner"
        if "avalon" in text:
            return raw_model or "AvalonMiner"
        if "innosilicon" in text:
            return raw_model or "Innosilicon"
        if "goldshell" in text:
            return raw_model or "Goldshell"
        if "auradine" in text:
            return raw_model or "Auradine"
        if "bitaxe" in text:
            return raw_model or "BitAxe"
        if "iceriver" in text:
            return raw_model or "IceRiver"
        if "hammer" in text:
            return raw_model or "Hammer"

        if "braiins" in text:
            return raw_model or "Braiins Firmware"
        if "vnish" in text:
            return raw_model or "Vnish Firmware"
        if "epic" in text:
            return raw_model or "ePIC Firmware"
        if "hiveos" in text:
            return raw_model or "HiveOS Firmware"
        if "luxos" in text:
            return raw_model or "LuxOS Firmware"
        if "mara" in text:
            return raw_model or "Mara Firmware"

        return raw_model or raw_make or raw_type or "Miner"
    except Exception:
        return "Miner"


def get_stable_identifier(miner) -> str | None:
    """Return stable device identifier if available."""
    try:
        for attr in ("mac", "mac_address", "serial", "serial_number"):
            value = getattr(miner, attr, None)
            if value:
                return str(value).lower()
    except Exception:
        pass

    return None


async def async_port_open(ip: str, port: int, timeout: float = SCAN_TCP_TIMEOUT) -> bool:
    """Check whether a TCP port is open."""
    writer = None
    try:
        connect = asyncio.open_connection(ip, port)
        reader, writer = await asyncio.wait_for(connect, timeout=timeout)
        return True
    except Exception:
        return False
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


async def async_detect_miner(ip: str) -> DiscoveredMiner | None:
    """Detect a miner on a single IP."""
    open_ports: list[int] = []

    for port in SCAN_PORTS:
        if await async_port_open(ip, port):
            open_ports.append(port)

    if not open_ports:
        return None

    try:
        miner = await asyncio.wait_for(pyasic.get_miner(ip), timeout=SCAN_MINER_TIMEOUT)
    except Exception as err:
        _LOGGER.debug("Miner probe failed for %s: %s", ip, err)
        return None

    if miner is None:
        return None

    model = normalize_model_name(miner)
    manufacturer = str(getattr(miner, "make", "") or "").strip() or "Unknown"

    hostname: str | None = None
    try:
        hostname = await asyncio.wait_for(miner.get_hostname(), timeout=1.5)
        if hostname:
            hostname = str(hostname).strip()
    except Exception:
        hostname = None

    stable_id = get_stable_identifier(miner)
    unique_key = stable_id or ip

    return DiscoveredMiner(
        ip=ip,
        model=model,
        manufacturer=manufacturer,
        hostname=hostname,
        unique_key=unique_key,
        open_ports=tuple(open_ports),
    )


async def async_scan_subnet(
    subnet: str,
    progress_callback=None,
) -> list[DiscoveredMiner]:
    """Scan a subnet for miners."""
    network = ipaddress.ip_network(subnet, strict=False)

    if network.version != 4:
        raise ValueError("Only IPv4 subnets are supported")

    hosts = [str(host) for host in network.hosts()]
    if len(hosts) > SCAN_MAX_HOSTS:
        raise ValueError("Subnet is too large")

    semaphore = asyncio.Semaphore(SCAN_CONCURRENCY)
    found: dict[str, DiscoveredMiner] = {}
    processed = 0
    total = len(hosts)

    async def _scan_host(ip: str) -> None:
        nonlocal processed

        async with semaphore:
            miner = await async_detect_miner(ip)
            if miner is not None:
                found[miner.unique_key] = miner

            processed += 1
            if progress_callback is not None and total > 0:
                try:
                    progress_callback(processed / total)
                except Exception:
                    pass

    await asyncio.gather(*(_scan_host(ip) for ip in hosts))
    return sorted(found.values(), key=lambda item: tuple(int(x) for x in item.ip.split(".")))