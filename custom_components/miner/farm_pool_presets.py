"""Farm stratum presets: fixed slots per config entry (each farm has its own list)."""
from __future__ import annotations

from typing import Any

from .const import (
    CONF_FARM_POOL_HOST,
    CONF_FARM_POOL_PASSWORD,
    CONF_FARM_POOL_PORT,
    CONF_FARM_POOL_PRESETS,
    CONF_FARM_POOL_USE_SSL,
    CONF_FARM_POOL_USERNAME,
)

FARM_POOL_SLOT_COUNT = 5

LEGACY_FARM_POOL_OPTION_KEYS = (
    CONF_FARM_POOL_HOST,
    CONF_FARM_POOL_PORT,
    CONF_FARM_POOL_USE_SSL,
    CONF_FARM_POOL_USERNAME,
    CONF_FARM_POOL_PASSWORD,
)


def _normalize_filled_preset(raw: dict[str, Any]) -> dict[str, Any] | None:
    host = str(raw.get("host") or "").strip()
    port_raw = raw.get("port")
    try:
        port = int(port_raw) if port_raw is not None and str(port_raw).strip() != "" else None
    except (TypeError, ValueError):
        return None
    if not host or port is None or port < 1 or port > 65535:
        return None
    return {
        "host": host,
        "port": port,
        "use_ssl": bool(raw.get("use_ssl", False)),
        "username": str(raw.get("username") or ""),
        "password": str(raw.get("password") or ""),
    }


def farm_pool_preset_slots(options: dict[str, Any]) -> list[dict[str, Any]]:
    """Return exactly FARM_POOL_SLOT_COUNT slot dicts; empty slot is {}."""
    slots: list[dict[str, Any]] = [{} for _ in range(FARM_POOL_SLOT_COUNT)]
    raw = options.get(CONF_FARM_POOL_PRESETS)
    if isinstance(raw, list):
        for i in range(FARM_POOL_SLOT_COUNT):
            item = raw[i] if i < len(raw) else {}
            if isinstance(item, dict) and item.get("host"):
                norm = _normalize_filled_preset(item)
                if norm:
                    slots[i] = norm

    if not any(s.get("host") for s in slots):
        host = str(options.get(CONF_FARM_POOL_HOST) or "").strip()
        port_raw = options.get(CONF_FARM_POOL_PORT)
        if host and port_raw is not None:
            try:
                pi = int(port_raw)
                if 1 <= pi <= 65535:
                    slots[0] = {
                        "host": host,
                        "port": pi,
                        "use_ssl": bool(options.get(CONF_FARM_POOL_USE_SSL, False)),
                        "username": str(options.get(CONF_FARM_POOL_USERNAME) or ""),
                        "password": str(options.get(CONF_FARM_POOL_PASSWORD) or ""),
                    }
            except (TypeError, ValueError):
                pass
    return slots


def farm_pool_slots_from_user_input(
    user_input: dict[str, Any],
    prev_slots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build slot list from options form; clear slot = empty host (and port)."""
    new_slots: list[dict[str, Any]] = []
    for i in range(FARM_POOL_SLOT_COUNT):
        host = (user_input.get(f"pool_slot_{i}_host") or "").strip()
        pr = user_input.get(f"pool_slot_{i}_port")
        if not host or pr is None or str(pr).strip() == "":
            new_slots.append({})
            continue
        try:
            pi = int(pr)
            if pi < 1 or pi > 65535:
                new_slots.append({})
                continue
        except (TypeError, ValueError):
            new_slots.append({})
            continue
        use_ssl = bool(user_input.get(f"pool_slot_{i}_use_ssl", False))
        username = (user_input.get(f"pool_slot_{i}_username") or "").strip()
        pw_raw = user_input.get(f"pool_slot_{i}_password")
        prev = prev_slots[i] if i < len(prev_slots) else {}
        prev_match = prev.get("host") == host and int(prev.get("port") or 0) == pi
        if pw_raw is not None and str(pw_raw).strip():
            password = str(pw_raw).strip()
        elif prev_match:
            password = str(prev.get("password") or "")
        else:
            password = ""
        new_slots.append(
            {
                "host": host,
                "port": pi,
                "use_ssl": use_ssl,
                "username": username,
                "password": password,
            }
        )
    return new_slots


def farm_pool_filled_slot_indices(slots: list[dict[str, Any]]) -> list[int]:
    return [i for i, s in enumerate(slots) if s.get("host")]


def farm_pool_select_option_labels(slots: list[dict[str, Any]]) -> tuple[list[int], list[str]]:
    """Indices and labels for dashboard select (filled slots only)."""
    indices = farm_pool_filled_slot_indices(slots)
    labels = [f"{i + 1}: {slots[i]['host']}:{slots[i]['port']}" for i in indices]
    return indices, labels


def strip_legacy_farm_pool_keys(options: dict[str, Any]) -> None:
    for k in LEGACY_FARM_POOL_OPTION_KEYS:
        options.pop(k, None)
