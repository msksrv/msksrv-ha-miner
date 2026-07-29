"""Options flow: farm menu, sections, and miner settings."""
from __future__ import annotations

import hashlib
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import split_entity_id
from homeassistant.data_entry_flow import SectionConfig, section
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    DeviceSelector,
    DeviceSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_FARM_AMBIENT_TEMP_ENTITIES,
    CONF_FARM_DEVICE_IDS,
    CONF_FARM_ELEC_TARIFF_MODE,
    CONF_FARM_ELEC_TOU_CURRENCY,
    CONF_FARM_ELEC_ZONES,
    CONF_FARM_ENERGY_RATES,
    CONF_FARM_POOL_PRESETS,
    CONF_IS_FARM,
    CONF_POWER_SWITCH,
    DOMAIN,
    FARM_ELEC_TARIFF_DUAL,
    FARM_ELEC_TARIFF_FLAT,
    FARM_ELEC_TARIFF_TRIPLE,
)
from .device_resolution import async_get_miner_config_entry_for_device
from .farm_elec_tou import (
    FARM_TARIFF_MODE_OPTIONS,
    farm_tariff_mode,
    farm_tou_zones_stored,
    tou_zones_from_user_input,
    validate_tou_submission,
)
from .farm_energy_rates import (
    farm_electricity_schema_fields,
    farm_energy_rates_from_user_input,
)
from .farm_pool_presets import (
    FARM_POOL_SLOT_COUNT,
    farm_pool_preset_slots,
    farm_pool_slots_from_user_input,
    strip_legacy_farm_pool_keys,
)

_LOGGER = logging.getLogger(__name__)

_FARM_MENU = (
    "farm_members",
    "farm_ambient",
    "farm_pools",
    "farm_tariff",
    "farm_actions",
)

_TEMP_ENTITY_SELECTOR = EntitySelector(
    EntitySelectorConfig(
        domain="sensor",
        device_class="temperature",
        multiple=True,
    )
)

_POOL_ACTION_OPTIONS = ["none", "replace_primary", "append_backup"]


def _password_from_input(value: Any, stored: str = "") -> str:
    """Keep stored secret when the user leaves the password field empty."""
    if value is not None and str(value).strip():
        return str(value)
    return stored


def _nest_section_errors(
    section_key: str, field_errors: dict[str, str]
) -> dict[str, Any]:
    """Map flat field errors into a section for HA options-flow nested schemas."""
    if not field_errors:
        return {}
    return {section_key: field_errors}


class MinerOptionsFlow(config_entries.OptionsFlow):
    """Options for miner and farm config entries."""

    def __init__(self) -> None:
        self._pending_pool_apply: dict[str, Any] | None = None
        self._pending_farm_apply: dict[str, Any] | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if self.config_entry.data.get(CONF_IS_FARM):
            return self.async_show_menu(
                step_id="init",
                menu_options=list(_FARM_MENU),
                sort=False,
            )
        return await self._async_miner_options(user_input)

    # --- Farm menu steps -------------------------------------------------

    async def async_step_farm_members(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        return await self._async_farm_save_devices(user_input)

    async def async_step_farm_ambient(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        return await self._async_farm_save_ambient(user_input)

    async def async_step_farm_pools(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        return await self._async_farm_save_pools(user_input, apply_now=False)

    async def async_step_farm_tariff(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        opts = self.config_entry.options
        stored_mode = farm_tariff_mode(opts)

        if user_input is None:
            return self.async_show_form(
                step_id="farm_tariff",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_FARM_ELEC_TARIFF_MODE,
                            description={"suggested_value": stored_mode},
                        ): SelectSelector(
                            SelectSelectorConfig(options=FARM_TARIFF_MODE_OPTIONS)
                        ),
                    }
                ),
            )

        mode = str(user_input.get(CONF_FARM_ELEC_TARIFF_MODE) or FARM_ELEC_TARIFF_FLAT)
        if mode not in FARM_TARIFF_MODE_OPTIONS:
            mode = FARM_ELEC_TARIFF_FLAT

        if mode == FARM_ELEC_TARIFF_FLAT:
            return await self.async_step_farm_tariff_flat(
                {CONF_FARM_ELEC_TARIFF_MODE: mode}
            )
        return await self.async_step_farm_tariff_tou(
            {CONF_FARM_ELEC_TARIFF_MODE: mode}
        )

    async def async_step_farm_tariff_flat(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        opts = self.config_entry.options
        ui = user_input or {}

        if user_input is not None and "farm_tariff_flat" in user_input:
            flat = user_input["farm_tariff_flat"]
            new_options = {**opts}
            new_options[CONF_FARM_ELEC_TARIFF_MODE] = FARM_ELEC_TARIFF_FLAT
            new_options[CONF_FARM_ENERGY_RATES] = farm_energy_rates_from_user_input(flat)
            new_options[CONF_FARM_ELEC_ZONES] = []
            tc = str(flat.get(CONF_FARM_ELEC_TOU_CURRENCY) or "").strip().upper()
            if tc:
                new_options[CONF_FARM_ELEC_TOU_CURRENCY] = tc
            self.hass.config_entries.async_update_entry(
                self.config_entry, options=new_options
            )
            return self.async_create_entry(title="", data=new_options)

        fields = farm_electricity_schema_fields(opts, ui.get("farm_tariff_flat"))
        schema = vol.Schema(
            {
                vol.Required("farm_tariff_flat"): section(
                    vol.Schema(fields),
                    SectionConfig(collapsed=False),
                ),
            }
        )
        return self.async_show_form(
            step_id="farm_tariff_flat", data_schema=schema, errors=errors
        )

    async def async_step_farm_tariff_tou(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        opts = self.config_entry.options
        ui = user_input or {}
        mode = str(
            ui.get(CONF_FARM_ELEC_TARIFF_MODE)
            or farm_tariff_mode(opts)
        )
        if mode not in (FARM_ELEC_TARIFF_DUAL, FARM_ELEC_TARIFF_TRIPLE):
            return await self.async_step_farm_tariff()

        if user_input is not None and "farm_tariff_tou" in user_input:
            tou = user_input["farm_tariff_tou"]
            tc = str(tou.get(CONF_FARM_ELEC_TOU_CURRENCY) or "").strip().upper()
            if not tc:
                errors["base"] = "farm_tou_currency_required"
            else:
                zones = tou_zones_from_user_input(tou, mode)
                ve = validate_tou_submission(mode, zones)
                if ve:
                    errors["base"] = ve
                else:
                    new_options = {**opts}
                    new_options[CONF_FARM_ELEC_TARIFF_MODE] = mode
                    new_options[CONF_FARM_ENERGY_RATES] = []
                    new_options[CONF_FARM_ELEC_TOU_CURRENCY] = tc
                    new_options[CONF_FARM_ELEC_ZONES] = zones
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, options=new_options
                    )
                    return self.async_create_entry(title="", data=new_options)

        from .farm_elec_tou import TOU_CURRENCY_OPTIONS, farm_tou_currency

        stored_z = farm_tou_zones_stored(opts)
        stored_cur = farm_tou_currency(opts) or "EUR"
        zone_count = 2 if mode == FARM_ELEC_TARIFF_DUAL else 3
        inner: dict[Any, Any] = {
            vol.Optional(
                CONF_FARM_ELEC_TOU_CURRENCY,
                description={
                    "suggested_value": ui.get(CONF_FARM_ELEC_TOU_CURRENCY, stored_cur)
                },
            ): SelectSelector(SelectSelectorConfig(options=TOU_CURRENCY_OPTIONS)),
        }
        _def_start = {1: "00:00", 2: "12:00", 3: "16:00"}
        _def_end = {1: "12:00", 2: "16:00", 3: "24:00"}
        tou_ui = ui.get("farm_tariff_tou") or ui
        for i in range(1, zone_count + 1):
            zi = stored_z[i - 1] if i - 1 < len(stored_z) else {}
            sk, ek, pk = f"farm_elec_z{i}_start", f"farm_elec_z{i}_end", f"farm_elec_z{i}_price"
            from homeassistant.helpers.selector import TimeSelector

            inner[
                vol.Optional(sk, description={"suggested_value": tou_ui.get(sk, zi.get("start", _def_start[i]))})
            ] = TimeSelector()
            inner[
                vol.Optional(ek, description={"suggested_value": tou_ui.get(ek, zi.get("end", _def_end[i]))})
            ] = TimeSelector()
            inner[
                vol.Optional(pk, description={"suggested_value": tou_ui.get(pk, zi.get("price_kwh", 0))})
            ] = NumberSelector(NumberSelectorConfig(min=0, max=9999, step="any", mode="box"))

        schema = vol.Schema(
            {
                vol.Required("farm_tariff_tou"): section(
                    vol.Schema(inner),
                    SectionConfig(collapsed=False),
                ),
            }
        )
        return self.async_show_form(
            step_id="farm_tariff_tou", data_schema=schema, errors=errors
        )

    async def async_step_farm_actions(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            flat = self._flatten_user_input(user_input)
            pool_action = str(flat.get("pool_action", "none"))
            if pool_action not in _POOL_ACTION_OPTIONS:
                pool_action = "none"
            errors: dict[str, Any] = {}
            if pool_action != "none":
                errors.update(
                    self._farm_pool_apply_errors(
                        flat, farm_pool_preset_slots(self.config_entry.options)
                    )
                )
            if pool_action != "none" and not errors:
                self._pending_farm_apply = flat
                return await self.async_step_farm_actions_confirm()
            if errors:
                return self.async_show_form(
                    step_id="farm_actions",
                    data_schema=self._farm_actions_schema(),
                    errors=errors,
                )
            return self.async_create_entry(
                title="", data=dict(self.config_entry.options)
            )

        return self.async_show_form(
            step_id="farm_actions",
            data_schema=self._farm_actions_schema(),
        )

    async def async_step_farm_actions_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="farm_actions_confirm",
                data_schema=vol.Schema(
                    {
                        vol.Required("confirm"): BooleanSelector(),
                    }
                ),
                description_placeholders={
                    "action": self._pending_farm_apply.get("pool_action", "")
                },
            )
        if not user_input.get("confirm"):
            self._pending_farm_apply = None
            return await self.async_step_farm_actions()
        pending = self._pending_farm_apply or {}
        self._pending_farm_apply = None
        return await self._async_farm_save_pools(pending, apply_now=True)

    # --- Farm helpers ----------------------------------------------------

    def _farm_pool_apply_errors(
        self,
        flat: dict[str, Any],
        slots: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Validate mass pool apply before asking the user to confirm."""
        errors: dict[str, Any] = {}
        try:
            apply_slot_i = int(str(flat.get("pool_apply_slot", "1"))) - 1
        except (TypeError, ValueError):
            apply_slot_i = -1
        if apply_slot_i < 0 or apply_slot_i >= FARM_POOL_SLOT_COUNT:
            errors["pool_apply_slot"] = "farm_pool_apply_slot_invalid"
            return errors
        cand = slots[apply_slot_i] if apply_slot_i < len(slots) else {}
        if not cand.get("host"):
            errors["pool_apply_slot"] = "farm_pool_apply_slot_invalid"
            return errors
        devices = self.config_entry.data.get(CONF_FARM_DEVICE_IDS) or []
        farm_coord = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        if (
            devices
            and farm_coord is not None
            and hasattr(farm_coord, "farm_stratum_allowed_for_device_ids")
            and not farm_coord.farm_stratum_allowed_for_device_ids(devices)
        ):
            errors["base"] = "farm_pool_mixed_algorithms"
        return errors

    def _farm_devices_schema(self, user_input: dict[str, Any] | None = None) -> vol.Schema:
        ui = user_input or {}
        stored = self.config_entry.data.get(CONF_FARM_DEVICE_IDS) or []
        if isinstance(stored, str):
            stored = [stored]
        suggested = ui.get(CONF_FARM_DEVICE_IDS, stored)
        return vol.Schema(
            {
                vol.Required(
                    CONF_FARM_DEVICE_IDS,
                    description={"suggested_value": suggested},
                ): DeviceSelector(
                    DeviceSelectorConfig(integration=DOMAIN, multiple=True)
                ),
            }
        )

    def _farm_ambient_schema(self, user_input: dict[str, Any] | None = None) -> vol.Schema:
        ui = user_input or {}
        stored = self.config_entry.options.get(CONF_FARM_AMBIENT_TEMP_ENTITIES) or []
        if isinstance(stored, str):
            stored = [stored]
        suggested = ui.get(CONF_FARM_AMBIENT_TEMP_ENTITIES, stored)
        return vol.Schema(
            {
                vol.Optional(
                    CONF_FARM_AMBIENT_TEMP_ENTITIES,
                    description={"suggested_value": suggested},
                ): _TEMP_ENTITY_SELECTOR,
            }
        )

    def _farm_pools_schema(self, user_input: dict[str, Any] | None = None) -> vol.Schema:
        ui = user_input or {}
        slots = farm_pool_preset_slots(self.config_entry.options)
        preset_fields: dict[Any, Any] = {}
        for i in range(FARM_POOL_SLOT_COUNT):
            s = slots[i] if i < len(slots) else {}
            preset_fields[
                vol.Optional(
                    f"pool_slot_{i}_host",
                    description={"suggested_value": ui.get(f"pool_slot_{i}_host", s.get("host", ""))},
                )
            ] = TextSelector(TextSelectorConfig())
            port_s = ui.get(f"pool_slot_{i}_port", s.get("port"))
            port_kw: dict[str, Any] = {}
            if port_s is not None:
                port_kw["description"] = {"suggested_value": port_s}
            preset_fields[
                vol.Optional(f"pool_slot_{i}_port", **port_kw)
            ] = NumberSelector(NumberSelectorConfig(min=1, max=65535, mode="box"))
            preset_fields[
                vol.Optional(
                    f"pool_slot_{i}_use_ssl",
                    default=bool(ui.get(f"pool_slot_{i}_use_ssl", s.get("use_ssl", False))),
                )
            ] = BooleanSelector()
            preset_fields[
                vol.Optional(
                    f"pool_slot_{i}_username",
                    description={"suggested_value": ui.get(f"pool_slot_{i}_username", s.get("username", ""))},
                )
            ] = TextSelector(TextSelectorConfig(autocomplete="username"))
            preset_fields[
                vol.Optional(f"pool_slot_{i}_password")
            ] = TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="new-password")
            )
        return vol.Schema(
            {
                vol.Required("pool_presets"): section(
                    vol.Schema(preset_fields),
                    SectionConfig(collapsed=True),
                ),
            }
        )

    def _farm_actions_schema(self) -> vol.Schema:
        apply_opts = [str(n) for n in range(1, FARM_POOL_SLOT_COUNT + 1)]
        return vol.Schema(
            {
                vol.Optional("pool_action", default="none"): SelectSelector(
                    SelectSelectorConfig(options=_POOL_ACTION_OPTIONS)
                ),
                vol.Optional("pool_apply_slot", default="1"): SelectSelector(
                    SelectSelectorConfig(options=apply_opts)
                ),
            }
        )

    async def _async_farm_save_devices(
        self, user_input: dict[str, Any] | None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            devices = user_input.get(CONF_FARM_DEVICE_IDS)
            if isinstance(devices, str):
                devices = [devices]
            if not devices:
                errors["base"] = "farm_no_devices"
            else:
                dev_reg = dr.async_get(self.hass)
                for did in devices:
                    if dev_reg.async_get(did) is None:
                        errors["base"] = "farm_invalid_device"
                        break
                    if async_get_miner_config_entry_for_device(self.hass, dev_reg.async_get(did)) is None:
                        errors["base"] = "farm_only_miner_devices"
                        break
            if not errors:
                key = ",".join(sorted(devices))
                uid_digest = hashlib.sha256(key.encode()).hexdigest()[:20]
                new_unique_id = f"farm_{uid_digest}"
                for ent in self.hass.config_entries.async_entries(DOMAIN):
                    if ent.entry_id != self.config_entry.entry_id and ent.unique_id == new_unique_id:
                        errors["base"] = "farm_device_set_conflict"
                        break
            if not errors:
                update_kw: dict[str, Any] = {
                    "data": {**self.config_entry.data, CONF_FARM_DEVICE_IDS: devices},
                }
                if new_unique_id != self.config_entry.unique_id:
                    update_kw["unique_id"] = new_unique_id
                self.hass.config_entries.async_update_entry(self.config_entry, **update_kw)
                return self.async_create_entry(title="", data=dict(self.config_entry.options))
        return self.async_show_form(
            step_id="farm_members",
            data_schema=self._farm_devices_schema(user_input),
            errors=errors,
        )

    async def _async_farm_save_ambient(
        self, user_input: dict[str, Any] | None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            ents = user_input.get(CONF_FARM_AMBIENT_TEMP_ENTITIES) or []
            if isinstance(ents, str):
                ents = [ents]
            registry = er.async_get(self.hass)
            for eid in ents:
                try:
                    ent_domain, _ = split_entity_id(eid)
                except ValueError:
                    errors["base"] = "invalid_temp_entity"
                    break
                if ent_domain != "sensor" or registry.async_get(eid) is None:
                    errors["base"] = "invalid_temp_entity"
                    break
            if not errors:
                new_options = {
                    **self.config_entry.options,
                    CONF_FARM_AMBIENT_TEMP_ENTITIES: list(ents),
                }
                self.hass.config_entries.async_update_entry(
                    self.config_entry, options=new_options
                )
                return self.async_create_entry(title="", data=new_options)
        return self.async_show_form(
            step_id="farm_ambient",
            data_schema=self._farm_ambient_schema(user_input),
            errors=errors,
        )

    async def _async_farm_save_pools(
        self, user_input: dict[str, Any] | None, *, apply_now: bool
    ) -> config_entries.FlowResult:
        errors: dict[str, Any] = {}
        opts = self.config_entry.options
        prev_slots = farm_pool_preset_slots(opts)

        if user_input is not None:
            preset_section = user_input.get("pool_presets")
            if preset_section is not None:
                flat: dict[str, Any] = dict(preset_section)
                new_slots = farm_pool_slots_from_user_input(flat, prev_slots)
            elif any(f"pool_slot_{i}_host" in user_input for i in range(FARM_POOL_SLOT_COUNT)):
                flat = user_input
                new_slots = farm_pool_slots_from_user_input(flat, prev_slots)
            else:
                flat = dict(user_input)
                new_slots = list(prev_slots)

            preset_errors: dict[str, str] = {}
            for i in range(FARM_POOL_SLOT_COUNT):
                h = (flat.get(f"pool_slot_{i}_host") or "").strip()
                pr = flat.get(f"pool_slot_{i}_port")
                has_port = pr is not None and str(pr).strip() != ""
                if h and not has_port:
                    preset_errors[f"pool_slot_{i}_port"] = "pool_fields_required"
                elif has_port and not h:
                    preset_errors[f"pool_slot_{i}_host"] = "pool_fields_required"
                elif h and has_port:
                    try:
                        if int(pr) < 1 or int(pr) > 65535:
                            raise ValueError
                    except (TypeError, ValueError):
                        preset_errors[f"pool_slot_{i}_port"] = "invalid_pool_port"
            if preset_errors:
                errors.update(_nest_section_errors("pool_presets", preset_errors))

            pool_action = str(flat.get("pool_action", "none"))
            devices = self.config_entry.data.get(CONF_FARM_DEVICE_IDS) or []
            farm_coord = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)

            if apply_now and pool_action != "none" and not errors:
                try:
                    apply_slot_i = int(str(flat.get("pool_apply_slot", "1"))) - 1
                except (TypeError, ValueError):
                    apply_slot_i = 0
                cand = new_slots[apply_slot_i] if 0 <= apply_slot_i < FARM_POOL_SLOT_COUNT else {}
                if not cand.get("host"):
                    errors["pool_apply_slot"] = "farm_pool_apply_slot_invalid"
                elif (
                    farm_coord
                    and hasattr(farm_coord, "farm_stratum_allowed_for_device_ids")
                    and not farm_coord.farm_stratum_allowed_for_device_ids(devices)
                ):
                    errors["base"] = "farm_pool_mixed_algorithms"
                if not errors and farm_coord:
                    try:
                        ok, err_key = await farm_coord.async_apply_stratum_to_members(
                            device_ids=devices,
                            replace_primary=pool_action == "replace_primary",
                            host=str(cand["host"]),
                            port=int(cand["port"]),
                            use_ssl=bool(cand.get("use_ssl", False)),
                            username=str(cand.get("username") or ""),
                            password=str(cand.get("password") or ""),
                        )
                        if not ok:
                            errors["base"] = err_key or "farm_pool_apply_failed"
                    except Exception:
                        _LOGGER.exception("Farm stratum from options")
                        errors["base"] = "farm_pool_apply_failed"

            if not errors:
                new_options = {**opts, CONF_FARM_POOL_PRESETS: new_slots}
                strip_legacy_farm_pool_keys(new_options)
                self.hass.config_entries.async_update_entry(
                    self.config_entry, options=new_options
                )
                return self.async_create_entry(title="", data=new_options)

        step = "farm_actions" if apply_now else "farm_pools"
        schema = (
            self._farm_actions_schema()
            if apply_now
            else self._farm_pools_schema(user_input)
        )
        return self.async_show_form(step_id=step, data_schema=schema, errors=errors)

    # --- Single-miner options --------------------------------------------

    async def async_step_miner_pool_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="miner_pool_confirm",
                data_schema=vol.Schema({vol.Required("confirm"): BooleanSelector()}),
            )
        if not user_input.get("confirm"):
            self._pending_pool_apply = None
            return await self._async_miner_options()
        pending = self._pending_pool_apply or {}
        self._pending_pool_apply = None
        return await self._async_miner_options(pending, confirmed=True)

    @staticmethod
    def _flatten_user_input(user_input: dict[str, Any]) -> dict[str, Any]:
        flat: dict[str, Any] = {}
        for key, val in user_input.items():
            if isinstance(val, dict):
                flat.update(val)
            else:
                flat[key] = val
        return flat

    async def _async_miner_options(
        self,
        user_input: dict[str, Any] | None = None,
        *,
        confirmed: bool = False,
    ) -> config_entries.FlowResult:
        errors: dict[str, Any] = {}

        if user_input is not None:
            user_input = self._flatten_user_input(user_input)
            entity_id = user_input.get(CONF_POWER_SWITCH)
            if entity_id:
                try:
                    ent_domain, _ = split_entity_id(entity_id)
                except ValueError:
                    ent_domain = ""
                if er.async_get(self.hass).async_get(entity_id) is None or ent_domain != "switch":
                    errors["base"] = "invalid_switch"

            pool_action = str(user_input.get("pool_action", "none"))
            host = (user_input.get("pool_host") or "").strip()
            port_raw = user_input.get("pool_port")
            port_int: int | None = None

            if pool_action not in _POOL_ACTION_OPTIONS:
                pool_action = "none"

            if pool_action != "none":
                pool_errors: dict[str, str] = {}
                if not host or port_raw is None or port_raw == "":
                    pool_errors["pool_host"] = "pool_fields_required"
                else:
                    try:
                        port_int = int(port_raw)
                        if port_int < 1 or port_int > 65535:
                            raise ValueError
                    except (TypeError, ValueError):
                        pool_errors["pool_port"] = "invalid_pool_port"
                if pool_errors:
                    errors.update(_nest_section_errors("stratum_pool", pool_errors))
                elif not confirmed:
                    self._pending_pool_apply = dict(user_input)
                    return await self.async_step_miner_pool_confirm()

            if errors:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._miner_options_schema(user_input),
                    errors=errors,
                )

            new_options = {**self.config_entry.options}
            if entity_id:
                new_options[CONF_POWER_SWITCH] = entity_id
            else:
                new_options.pop(CONF_POWER_SWITCH, None)

            if pool_action != "none" and port_int is not None:
                entry_id = self.config_entry.entry_id
                coordinator = self.hass.data.get(DOMAIN, {}).get(entry_id)
                if coordinator is None:
                    errors["base"] = "miner_not_loaded"
                else:
                    miner = await coordinator.get_miner()
                    if miner is None:
                        errors["base"] = "miner_offline"
                    else:
                        from . import pool_stratum

                        use_ssl = bool(user_input.get("pool_use_ssl"))
                        uname = str(user_input.get("pool_username") or "")
                        pwd = str(user_input.get("pool_password") or "")
                        try:
                            if pool_action == "replace_primary":
                                ok = await pool_stratum.async_apply_primary_stratum(
                                    miner, host, port_int, use_ssl, uname, pwd, force_user_password=True
                                )
                            else:
                                ok = await pool_stratum.async_append_stratum_pool(
                                    miner, host, port_int, use_ssl, uname, pwd
                                )
                            if not ok:
                                errors["base"] = "pool_apply_failed"
                            else:
                                await coordinator.async_request_refresh()
                        except Exception:
                            _LOGGER.exception("Applying pool from options")
                            errors["base"] = "pool_apply_failed"

            if errors:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._miner_options_schema(user_input),
                    errors=errors,
                )
            return self.async_create_entry(title="", data=new_options)

        return self.async_show_form(
            step_id="init",
            data_schema=self._miner_options_schema(),
        )

    def _miner_options_schema(
        self, user_input: dict[str, Any] | None = None
    ) -> vol.Schema:
        ui = self._flatten_user_input(user_input) if user_input else {}
        stored = self.config_entry.options.get(CONF_POWER_SWITCH)
        suggested = ui.get(CONF_POWER_SWITCH, stored)
        sw_kw: dict[str, Any] = {}
        if suggested:
            sw_kw["description"] = {"suggested_value": suggested}

        return vol.Schema(
            {
                vol.Required("linked_switch"): section(
                    vol.Schema(
                        {
                            vol.Optional(CONF_POWER_SWITCH, **sw_kw): EntitySelector(
                                EntitySelectorConfig(domain="switch")
                            ),
                        }
                    ),
                    SectionConfig(collapsed=False),
                ),
                vol.Required("stratum_pool"): section(
                    vol.Schema(
                        {
                            vol.Optional(
                                "pool_action",
                                description={"suggested_value": ui.get("pool_action", "none")},
                            ): SelectSelector(
                                SelectSelectorConfig(options=_POOL_ACTION_OPTIONS)
                            ),
                            vol.Optional(
                                "pool_host",
                                description={"suggested_value": ui.get("pool_host", "")},
                            ): TextSelector(TextSelectorConfig()),
                            vol.Optional(
                                "pool_port",
                                description={"suggested_value": ui.get("pool_port")},
                            ): NumberSelector(
                                NumberSelectorConfig(min=1, max=65535, mode="box")
                            ),
                            vol.Optional(
                                "pool_use_ssl",
                                default=bool(ui.get("pool_use_ssl", False)),
                            ): BooleanSelector(),
                            vol.Optional(
                                "pool_username",
                                description={"suggested_value": ui.get("pool_username", "")},
                            ): TextSelector(TextSelectorConfig(autocomplete="username")),
                            vol.Optional("pool_password"): TextSelector(
                                TextSelectorConfig(
                                    type=TextSelectorType.PASSWORD,
                                    autocomplete="new-password",
                                )
                            ),
                        }
                    ),
                    SectionConfig(collapsed=True),
                ),
            }
        )
