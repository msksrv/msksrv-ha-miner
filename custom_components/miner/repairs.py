"""Repair flows for miner health issues."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import selector

from .const import CONF_POWER_SWITCH, DOMAIN
from .health.repairs.definitions import parse_issue_id

_LOGGER = logging.getLogger(__name__)

ACTION_REBOOT = "reboot"
ACTION_POWER_OFF = "power_off"
ACTION_CHECKED = "checked"

_ACTION_LABELS: dict[str, dict[str, str]] = {
    "en": {
        ACTION_REBOOT: "Reboot miner",
        ACTION_POWER_OFF: "Turn off linked power switch",
        ACTION_CHECKED: "I checked the equipment",
    },
    "ru": {
        ACTION_REBOOT: "Перезагрузить майнер",
        ACTION_POWER_OFF: "Выключить привязанный выключатель питания",
        ACTION_CHECKED: "Я проверил оборудование",
    },
}

_REPAIR_ACTIONS: dict[str, tuple[str, ...]] = {
    "hashboard": (ACTION_REBOOT, ACTION_CHECKED),
    "hashrate": (ACTION_REBOOT, ACTION_CHECKED),
    "temperature": (ACTION_POWER_OFF, ACTION_REBOOT, ACTION_CHECKED),
    "fan": (ACTION_POWER_OFF, ACTION_REBOOT, ACTION_CHECKED),
}


class MinerRepairFlow(RepairsFlow):
    """Multi-step repair for a single miner issue."""

    def __init__(
        self,
        hass: HomeAssistant,
        issue_id: str,
        data: dict[str, str | int | float | None] | None,
    ) -> None:
        self._hass = hass
        self._issue_id = issue_id
        self._data = data or {}
        parsed = parse_issue_id(issue_id)
        self._entry_id = parsed[0] if parsed else str(self._data.get("entry_id", ""))
        self._repair_type = parsed[1] if parsed else str(
            self._data.get("repair_type", "")
        )
        self._pending_action: str | None = None

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        if user_input is not None:
            action = user_input["action"]
            if action == ACTION_CHECKED:
                return await self._async_dismiss()
            self._pending_action = action
            if action == ACTION_REBOOT:
                return await self.async_step_confirm_reboot()
            if action == ACTION_POWER_OFF:
                return await self.async_step_confirm_power()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=self._action_select_options(),
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            description_placeholders=self._description_placeholders(),
        )

    async def async_step_confirm_reboot(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        if user_input is not None:
            coordinator = self._coordinator()
            if coordinator is None:
                return self.async_abort(reason="miner_not_loaded")
            try:
                coordinator.baseline.notify_reboot()
                miner = await coordinator.get_miner()
                if miner is not None:
                    await miner.reboot()
            except Exception:
                _LOGGER.exception("Repair reboot failed for %s", self._entry_id)
                return self.async_abort(reason="reboot_failed")
            return await self._async_dismiss()
        return self.async_show_form(
            step_id="confirm_reboot",
            data_schema=vol.Schema({}),
            description_placeholders=self._description_placeholders(),
        )

    async def async_step_confirm_power(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        if user_input is not None:
            switch_id = self._power_switch_entity_id()
            if not switch_id:
                return self.async_abort(reason="no_power_switch")
            domain = switch_id.split(".", 1)[0]
            await self._hass.services.async_call(
                domain,
                "turn_off",
                {"entity_id": switch_id},
                blocking=True,
            )
            return await self._async_dismiss()
        return self.async_show_form(
            step_id="confirm_power",
            data_schema=vol.Schema({}),
            description_placeholders=self._description_placeholders(),
        )

    def _available_actions(self) -> tuple[str, ...]:
        keys = _REPAIR_ACTIONS.get(self._repair_type, (ACTION_CHECKED,))
        out: list[str] = []
        for key in keys:
            if key == ACTION_POWER_OFF and not self._power_switch_entity_id():
                continue
            out.append(key)
        if ACTION_CHECKED not in out:
            out.append(ACTION_CHECKED)
        return tuple(out)

    def _action_select_options(self) -> list[selector.SelectOptionDict]:
        lang = (
            "ru"
            if self._hass.config.language
            and self._hass.config.language.startswith("ru")
            else "en"
        )
        labels = _ACTION_LABELS[lang]
        return [
            selector.SelectOptionDict(
                value=action,
                label=labels.get(action, action),
            )
            for action in self._available_actions()
        ]

    def _coordinator(self) -> Any | None:
        return self._hass.data.get(DOMAIN, {}).get(self._entry_id)

    def _power_switch_entity_id(self) -> str | None:
        coordinator = self._coordinator()
        if coordinator is None:
            return None
        eid = coordinator.config_entry.options.get(CONF_POWER_SWITCH)
        if not eid:
            return None
        eid = str(eid).strip()
        return eid if self._hass.states.get(eid) is not None else None

    def _description_placeholders(self) -> dict[str, str]:
        issue = ir.async_get(self._hass).async_get_issue(DOMAIN, self._issue_id)
        if issue and issue.translation_placeholders:
            return {k: str(v) for k, v in issue.translation_placeholders.items()}
        coordinator = self._coordinator()
        name = getattr(coordinator.config_entry, "title", "Miner") if coordinator else "Miner"
        return {"name": name}

    async def _async_dismiss(self) -> data_entry_flow.FlowResult:
        coordinator = self._coordinator()
        if coordinator is not None and hasattr(coordinator, "repairs"):
            coordinator.repairs.dismiss_repair(self._repair_type)
        else:
            ir.async_delete_issue(self._hass, DOMAIN, self._issue_id)
        return self.async_create_entry(title="", data={})


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Route fix flow by stable issue id."""
    if parse_issue_id(issue_id):
        return MinerRepairFlow(hass, issue_id, data)
    return RepairsFlow()
