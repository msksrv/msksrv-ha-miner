"""Export an allowlisted snapshot for Home Assistant diagnostics."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_IS_FARM, DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    """Report telemetry and state without exporting credentials or addresses."""
    is_farm = bool(entry.data.get(CONF_IS_FARM))
    result = {
        "kind": "farm" if is_farm else "miner",
        "entry_state": entry.state.value,
    }
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        return result

    data = coordinator.data or {}
    result["available"] = coordinator.last_update_success
    if is_farm:
        snapshot = coordinator.energy.snapshot
        result.update(
            farm={
                "miners": data.get("miner_count"),
                "online": data.get("miners_online"),
                "health_score": data.get("health_score"),
                "health_issues": data.get("health_issues"),
                "emergency_stop_active": coordinator.emergency_stop_active,
            },
            energy={
                "source": snapshot.source,
                "estimated": snapshot.estimated,
                "coverage_percent": snapshot.coverage,
                "total_kwh": snapshot.total_kwh,
            },
        )
        return result

    health = data.get("health") or {}
    anomaly = data.get("anomaly") or {}
    recovery = coordinator.recovery.record
    energy = coordinator.energy.record
    result.update(
        miner={
            "manufacturer": data.get("make"),
            "model": data.get("model"),
            "firmware": data.get("fw_ver"),
        },
        last_poll_error={
            "type": coordinator.last_poll_error,
            "at": coordinator.last_poll_error_at,
        },
        health={
            "score": health.get("score"),
            "coverage_percent": health.get("data_coverage"),
            "flags": health.get("flags"),
            "anomaly_reason": anomaly.get("reason"),
        },
        energy={"source": energy.active_source, "total_kwh": energy.total_kwh},
        recovery={
            "state": recovery.state,
            "lock_reason": recovery.locked_reason,
            "emergency_stop_latched": recovery.emergency_stop_latched,
        },
    )
    return result
