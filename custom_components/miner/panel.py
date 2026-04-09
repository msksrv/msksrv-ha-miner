"""Optional sidebar shortcut to Miner integration settings."""
from __future__ import annotations

import logging

from homeassistant.components import frontend
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_COMPONENT_LOADED
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback

from .const import CONF_SIDEBAR_PANEL, DOMAIN

_LOGGER = logging.getLogger(__name__)

PANEL_URL_PATH = "msksrv-miner"
_DATA_KEY_PANEL_REGISTERED = "_sidebar_config_panel_registered"
_DATA_KEY_SIDEBAR_URL = "_sidebar_panel_iframe_url"


def _sidebar_target_entry(hass: HomeAssistant) -> ConfigEntry | None:
    """Pick one config entry that requested the sidebar (stable order by title)."""
    candidates = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.disabled_by is None and e.options.get(CONF_SIDEBAR_PANEL)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda e: (e.title or "").lower())[0]


def _integrations_entry_url(entry_id: str) -> str:
    """Same view as Settings → Integrations → Miner → this device card."""
    return f"/config/integrations/integration/{DOMAIN}?config_entry={entry_id}"


@callback
def sync_miner_sidebar_panel(hass: HomeAssistant) -> None:
    """Register or remove the sidebar shortcut (iframe → real config URL)."""
    if "frontend" not in hass.config.components:
        return

    domain_data = hass.data.setdefault(DOMAIN, {})
    target = _sidebar_target_entry(hass)
    is_reg = domain_data.get(_DATA_KEY_PANEL_REGISTERED, False)

    if target is not None:
        url = _integrations_entry_url(target.entry_id)
        if is_reg and domain_data.get(_DATA_KEY_SIDEBAR_URL) == url:
            return

        try:
            frontend.async_register_built_in_panel(
                hass,
                "iframe",
                sidebar_title="MSKSRV ASIC Miner",
                sidebar_icon="mdi:pickaxe",
                frontend_url_path=PANEL_URL_PATH,
                config={"url": url},
                require_admin=True,
                update=is_reg,
            )
        except ValueError:
            frontend.async_register_built_in_panel(
                hass,
                "iframe",
                sidebar_title="MSKSRV ASIC Miner",
                sidebar_icon="mdi:pickaxe",
                frontend_url_path=PANEL_URL_PATH,
                config={"url": url},
                require_admin=True,
                update=True,
            )
        domain_data[_DATA_KEY_PANEL_REGISTERED] = True
        domain_data[_DATA_KEY_SIDEBAR_URL] = url
        return

    if is_reg:
        frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
        domain_data[_DATA_KEY_PANEL_REGISTERED] = False
        domain_data.pop(_DATA_KEY_SIDEBAR_URL, None)


def async_setup_sidebar_panel(hass: HomeAssistant) -> CALLBACK_TYPE | None:
    """Sync sidebar now; subscribe to frontend load if needed. Returns unsubscribe."""
    sync_miner_sidebar_panel(hass)

    @callback
    def _component_loaded(event: Event) -> None:
        if event.data.get("component") != "frontend":
            return
        sync_miner_sidebar_panel(hass)

    if "frontend" in hass.config.components:
        return None

    return hass.bus.async_listen(EVENT_COMPONENT_LOADED, _component_loaded)
