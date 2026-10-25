"""Select an existing paired Android TV, without opening its voice assistant."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
import probatio as vol

from .const import CONF_ANDROIDTV_ENTRY_ID, CONF_REMOTE_ENTITY, DOMAIN
from .errors import VoiceError
from .target import validate_target


def _schema(default: str | None = None) -> vol.Schema:
    key = (
        vol.Required(CONF_REMOTE_ENTITY, default=default)
        if default
        else vol.Required(CONF_REMOTE_ENTITY)
    )
    return vol.Schema(
        {
            key: selector.EntitySelector(
                selector.EntitySelectorConfig(domain="remote", integration="androidtv_remote")
            )
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """One config entry per paired TV; multiple TVs are independent."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if not any(
            item.domain == "remote" and item.platform == "androidtv_remote"
            for item in er.async_get(self.hass).entities.values()
        ):
            # The selector would otherwise show an empty list with no explanation.
            return self.async_abort(reason="no_android_tv")
        errors = {}
        if user_input is not None:
            try:
                target = await validate_target(self.hass, user_input[CONF_REMOTE_ENTITY])
            except VoiceError as error:
                errors["base"] = error.code
            else:
                await self.async_set_unique_id(target.source_entry_id)
                self._abort_if_unique_id_configured()
                state = self.hass.states.get(target.entity_id)
                return self.async_create_entry(
                    title=state.name if state else target.entity_id,
                    data={
                        CONF_REMOTE_ENTITY: target.entity_id,
                        CONF_ANDROIDTV_ENTRY_ID: target.source_entry_id,
                    },
                )
        return self.async_show_form(step_id="user", data_schema=_schema(), errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            try:
                target = await validate_target(self.hass, user_input[CONF_REMOTE_ENTITY])
            except VoiceError as error:
                errors["base"] = error.code
            else:
                await self.async_set_unique_id(target.source_entry_id)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_REMOTE_ENTITY: target.entity_id,
                        CONF_ANDROIDTV_ENTRY_ID: target.source_entry_id,
                    },
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(entry.data[CONF_REMOTE_ENTITY]),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return OptionsFlow()


class OptionsFlow(config_entries.OptionsFlow):
    """Expose reconfiguration from the entry's options menu."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            try:
                target = await validate_target(self.hass, user_input[CONF_REMOTE_ENTITY])
                if target.source_entry_id != self.config_entry.data[CONF_ANDROIDTV_ENTRY_ID]:
                    raise VoiceError("different_target")
            except VoiceError as error:
                errors["base"] = error.code
            else:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={
                        CONF_REMOTE_ENTITY: target.entity_id,
                        CONF_ANDROIDTV_ENTRY_ID: target.source_entry_id,
                    },
                )
                return self.async_create_entry(title="", data={})
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(self.config_entry.data[CONF_REMOTE_ENTITY]),
            errors=errors,
        )
