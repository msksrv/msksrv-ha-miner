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

from .const import CONF_HEALTH_THRESHOLDS, CONF_POWER_SWITCH, DOMAIN
from .farm_coordinator import MinerFarmCoordinator
from .health.profiles import health_threshold_defaults_for_ui
from .health.repairs.definitions import parse_issue_id
from .health.repairs.threshold_form import (
    build_threshold_schema,
    merge_threshold_options,
    threshold_fields_for_repair,
    validate_threshold_input,
)

_LOGGER = logging.getLogger(__name__)

ACTION_REBOOT = "reboot"
ACTION_POWER_OFF = "power_off"
ACTION_POWER_ON = "power_on"
ACTION_CHECKED = "checked"
ACTION_RETRY = "retry_refresh"
ACTION_RESTART_BACKEND = "restart_backend"
ACTION_THRESHOLDS = "thresholds"
ACTION_CHECK_POWER = "check_power"
ACTION_CHECK_PROFILE = "check_profile"

_ACTION_LABELS: dict[str, dict[str, str]] = {
    "en": {
        ACTION_REBOOT: "Reboot miner",
        ACTION_POWER_OFF: "Turn off linked power switch",
        ACTION_POWER_ON: "Turn on linked power switch",
        ACTION_CHECKED: "I checked the equipment",
        ACTION_RETRY: "Retry connection",
        ACTION_RESTART_BACKEND: "Restart miner backend",
        ACTION_THRESHOLDS: "Adjust health thresholds",
        ACTION_CHECK_POWER: "Check power supply",
        ACTION_CHECK_PROFILE: "Check power profile",
    },
    "ru": {
        ACTION_REBOOT: "Перезагрузить майнер",
        ACTION_POWER_OFF: "Выключить привязанный выключатель питания",
        ACTION_POWER_ON: "Включить привязанный выключатель питания",
        ACTION_CHECKED: "Я проверил оборудование",
        ACTION_RETRY: "Повторить опрос",
        ACTION_RESTART_BACKEND: "Перезапустить службу управления",
        ACTION_THRESHOLDS: "Настроить пороги состояния",
        ACTION_CHECK_POWER: "Проверить питание",
        ACTION_CHECK_PROFILE: "Проверить профиль мощности",
    },
}

_REPAIR_ACTIONS: dict[str, tuple[str, ...]] = {
    "hashboard": (ACTION_REBOOT, ACTION_CHECKED),
    "hashrate": (ACTION_REBOOT, ACTION_THRESHOLDS, ACTION_CHECKED),
    "temperature": (ACTION_THRESHOLDS, ACTION_POWER_OFF, ACTION_REBOOT, ACTION_CHECKED),
    "fan": (ACTION_POWER_OFF, ACTION_REBOOT, ACTION_CHECKED),
    "offline": (ACTION_RETRY, ACTION_POWER_ON, ACTION_CHECKED),
    "pool": (ACTION_RETRY, ACTION_REBOOT, ACTION_RESTART_BACKEND, ACTION_CHECKED),
    "recovery": (ACTION_CHECKED,),
    "reject": (ACTION_THRESHOLDS, ACTION_CHECKED),
    "power": (
        ACTION_CHECK_POWER,
        ACTION_CHECK_PROFILE,
        ACTION_REBOOT,
        ACTION_THRESHOLDS,
        ACTION_CHECKED,
    ),
}

_FARM_REPAIR_ACTIONS: dict[str, tuple[str, ...]] = {
    "offline": (ACTION_RETRY, ACTION_CHECKED),
}


def _farm_offline_count(coord: MinerFarmCoordinator) -> int:
    """Count farm members that are unreachable (missing coordinator or failed poll)."""
    offline = 0
    for _entry, member in coord._iter_miner_member_pairs(coord.device_ids):
        if member is None or not member.last_update_success:
            offline += 1
    return offline


class UnsupportedRepairFlow(RepairsFlow):
    """Abort immediately for unrecognized issue ids."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        return self.async_abort(reason="issue_unsupported")


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
        if parsed:
            self._scope, self._entry_id, self._repair_type = parsed
        else:
            self._scope = "miner"
            self._entry_id = str(self._data.get("entry_id", ""))
            self._repair_type = str(self._data.get("repair_type", ""))

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        if user_input is not None:
            action = user_input["action"]
            if action == ACTION_CHECKED:
                return await self._async_dismiss()
            if action == ACTION_REBOOT:
                return await self.async_step_confirm_reboot()
            if action == ACTION_POWER_OFF:
                return await self.async_step_confirm_power()
            if action == ACTION_POWER_ON:
                return await self.async_step_confirm_power_on()
            if action == ACTION_RETRY:
                return await self._async_retry_refresh()
            if action == ACTION_RESTART_BACKEND:
                return await self.async_step_confirm_restart_backend()
            if action == ACTION_THRESHOLDS:
                return await self.async_step_open_thresholds()
            if action == ACTION_CHECK_POWER:
                return await self.async_step_check_power()
            if action == ACTION_CHECK_PROFILE:
                return await self.async_step_check_profile()
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
                from .miner_actions import async_send_reboot_command

                await async_send_reboot_command(coordinator)
            except Exception:
                _LOGGER.exception("Repair reboot failed for %s", self._entry_id)
                return self.async_abort(reason="reboot_failed")
            return await self._async_dismiss()
        return self.async_show_form(
            step_id="confirm_reboot",
            data_schema=vol.Schema({}),
            description_placeholders=self._description_placeholders(),
        )

    async def async_step_confirm_restart_backend(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        if user_input is not None:
            coordinator = self._coordinator()
            if coordinator is None:
                return self.async_abort(reason="miner_not_loaded")
            try:
                miner = await coordinator.get_miner()
                if miner is None:
                    return self.async_abort(reason="miner_unavailable")
                await miner.restart_backend()
            except Exception:
                _LOGGER.exception(
                    "Repair restart_backend failed for %s", self._entry_id
                )
                return self.async_abort(reason="restart_backend_failed")
            return await self._async_dismiss()
        return self.async_show_form(
            step_id="confirm_restart_backend",
            data_schema=vol.Schema({}),
            description_placeholders=self._description_placeholders(),
        )

    async def async_step_confirm_power(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        if user_input is not None:
            switch_id = self._power_switch_entity_id()
            if not switch_id or not switch_id.startswith("switch."):
                return self.async_abort(reason="no_power_switch")
            try:
                await self._hass.services.async_call(
                    "switch",
                    "turn_off",
                    {"entity_id": switch_id},
                    blocking=True,
                )
            except Exception:
                _LOGGER.exception("Repair power off failed for %s", self._entry_id)
                return self.async_abort(reason="power_off_failed")
            return await self._async_dismiss()
        return self.async_show_form(
            step_id="confirm_power",
            data_schema=vol.Schema({}),
            description_placeholders=self._description_placeholders(),
        )

    async def async_step_confirm_power_on(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        if user_input is not None:
            switch_id = self._power_switch_entity_id()
            if not switch_id or not switch_id.startswith("switch."):
                return self.async_abort(reason="no_power_switch")
            try:
                await self._hass.services.async_call(
                    "switch",
                    "turn_on",
                    {"entity_id": switch_id},
                    blocking=True,
                )
            except Exception:
                _LOGGER.exception("Repair power on failed for %s", self._entry_id)
                return self.async_abort(reason="power_on_failed")
            return await self._async_dismiss()
        return self.async_show_form(
            step_id="confirm_power_on",
            data_schema=vol.Schema({}),
            description_placeholders=self._description_placeholders(),
        )

    async def async_step_open_thresholds(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="miner_not_loaded")
        if not threshold_fields_for_repair(self._repair_type):
            return self.async_abort(reason="issue_unsupported")

        data = coordinator.data or {}
        make = data.get("make")
        model = data.get("model")
        opts = coordinator.config_entry.options
        defaults = health_threshold_defaults_for_ui(make, model, opts)
        stored = opts.get(CONF_HEALTH_THRESHOLDS) or {}

        if user_input is not None:
            errors = validate_threshold_input(self._repair_type, user_input)
            if errors:
                return self.async_show_form(
                    step_id="open_thresholds",
                    data_schema=build_threshold_schema(
                        self._repair_type, defaults, stored
                    ),
                    errors=errors,
                    description_placeholders=self._description_placeholders(),
                )
            new_options = merge_threshold_options(
                opts,
                self._repair_type,
                user_input,
                make=make,
                model=model,
            )
            self._hass.config_entries.async_update_entry(
                coordinator.config_entry, options=new_options
            )
            await coordinator.async_request_refresh()
            return await self.async_step_init()

        return self.async_show_form(
            step_id="open_thresholds",
            data_schema=build_threshold_schema(
                self._repair_type, defaults, stored
            ),
            description_placeholders=self._description_placeholders(),
        )

    async def async_step_check_power(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        if user_input is not None:
            return await self.async_step_init()
        return self.async_show_form(
            step_id="check_power",
            data_schema=vol.Schema({}),
            description_placeholders=self._description_placeholders(),
        )

    async def async_step_check_profile(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        if user_input is not None:
            return await self.async_step_init()
        return self.async_show_form(
            step_id="check_profile",
            data_schema=vol.Schema({}),
            description_placeholders=self._description_placeholders(),
        )

    async def _async_retry_refresh(self) -> data_entry_flow.FlowResult:
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="miner_not_loaded")
        try:
            await coordinator.async_request_refresh()
        except Exception:
            _LOGGER.exception("Repair refresh failed for %s", self._entry_id)
            return self.async_abort(reason="refresh_failed")
        if not coordinator.last_update_success:
            return self.async_abort(reason="refresh_failed")
        return await self._async_dismiss()

    def _available_actions(self) -> tuple[str, ...]:
        keys = _REPAIR_ACTIONS.get(self._repair_type, (ACTION_CHECKED,))
        out: list[str] = []
        for key in keys:
            if key in (ACTION_POWER_OFF, ACTION_POWER_ON) and not self._power_switch_entity_id():
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
        if not eid.startswith("switch."):
            return None
        return eid if self._hass.states.get(eid) is not None else None

    def _description_placeholders(self) -> dict[str, str]:
        issue = ir.async_get(self._hass).async_get_issue(DOMAIN, self._issue_id)
        if issue and issue.translation_placeholders:
            return {k: str(v) for k, v in issue.translation_placeholders.items()}
        coordinator = self._coordinator()
        name = (
            getattr(coordinator.config_entry, "title", "Miner")
            if coordinator
            else "Miner"
        )
        return {"name": name}

    async def _async_dismiss(self) -> data_entry_flow.FlowResult:
        coordinator = self._coordinator()
        if coordinator is not None and hasattr(coordinator, "repairs"):
            coordinator.repairs.dismiss_repair(self._repair_type)
        else:
            ir.async_delete_issue(self._hass, DOMAIN, self._issue_id)
        return self.async_create_entry(title="", data={})


class FarmRepairFlow(RepairsFlow):
    """Repair flow for farm-level issues."""

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
        if parsed:
            self._scope, self._entry_id, self._repair_type = parsed
        else:
            self._scope = "farm"
            self._entry_id = str(self._data.get("entry_id", ""))
            self._repair_type = str(self._data.get("repair_type", ""))

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        if user_input is not None:
            action = user_input["action"]
            if action == ACTION_CHECKED:
                return await self._async_dismiss()
            if action == ACTION_RETRY:
                return await self._async_retry_offline_members()
        return self.async_show_form(
            step_id="farm_init",
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

    async def _async_retry_offline_members(self) -> data_entry_flow.FlowResult:
        coordinator = self._farm_coordinator()
        if coordinator is None:
            return self.async_abort(reason="farm_not_loaded")
        try:
            for _entry, member in coordinator._iter_miner_member_pairs(
                coordinator.device_ids
            ):
                if member is not None:
                    await member.async_request_refresh()
        except Exception:
            _LOGGER.exception("Farm repair refresh failed for %s", self._entry_id)
            return self.async_abort(reason="refresh_failed")
        if _farm_offline_count(coordinator) > 0:
            return self.async_abort(reason="refresh_failed")
        return await self._async_dismiss()

    def _available_actions(self) -> tuple[str, ...]:
        keys = _FARM_REPAIR_ACTIONS.get(self._repair_type, (ACTION_CHECKED,))
        out = list(keys)
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

    def _farm_coordinator(self) -> MinerFarmCoordinator | None:
        coord = self._hass.data.get(DOMAIN, {}).get(self._entry_id)
        if isinstance(coord, MinerFarmCoordinator):
            return coord
        return None

    def _description_placeholders(self) -> dict[str, str]:
        issue = ir.async_get(self._hass).async_get_issue(DOMAIN, self._issue_id)
        if issue and issue.translation_placeholders:
            return {k: str(v) for k, v in issue.translation_placeholders.items()}
        coordinator = self._farm_coordinator()
        name = (
            getattr(coordinator.config_entry, "title", "Farm")
            if coordinator
            else "Farm"
        )
        return {"name": name}

    async def _async_dismiss(self) -> data_entry_flow.FlowResult:
        coordinator = self._farm_coordinator()
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
    parsed = parse_issue_id(issue_id)
    if not parsed:
        return UnsupportedRepairFlow()
    scope, _entry_id, _repair_type = parsed
    if scope == "farm":
        return FarmRepairFlow(hass, issue_id, data)
    return MinerRepairFlow(hass, issue_id, data)
