"""Optional sidebar shortcut to Miner integration settings."""
from __future__ import annotations

import logging

from homeassistant.components import frontend
from homeassistant.const import EVENT_COMPONENT_LOADED
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback

from .const import CONF_SIDEBAR_PANEL, DOMAIN

_LOGGER = logging.getLogger(__name__)

PANEL_URL_PATH = "msksrv-miner"
_DATA_KEY_PANEL_REGISTERED = "_sidebar_config_panel_registered"


def _want_sidebar(hass: HomeAssistant) -> bool:
    return any(
        bool(entry.options.get(CONF_SIDEBAR_PANEL))
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.disabled_by is None
    )


@callback
def sync_miner_sidebar_panel(hass: HomeAssistant) -> None:
    """Register or remove the integration config shortcut in the left sidebar."""
    if "frontend" not in hass.config.components:
        return

    domain_data = hass.data.setdefault(DOMAIN, {})
    want = _want_sidebar(hass)
    is_reg = domain_data.get(_DATA_KEY_PANEL_REGISTERED, False)

    if want and not is_reg:
        try:
            frontend.async_register_built_in_panel(
                hass,
                "config",
                sidebar_title="MSKSRV ASIC Miner",
                sidebar_icon="mdi:pickaxe",
                frontend_url_path=PANEL_URL_PATH,
                config_panel_domain=DOMAIN,
                require_admin=True,
            )
        except ValueError:
            _LOGGER.debug("Miner sidebar panel already registered")
        domain_data[_DATA_KEY_PANEL_REGISTERED] = True
        return

    if not want and is_reg:
        frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
        domain_data[_DATA_KEY_PANEL_REGISTERED] = False


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
