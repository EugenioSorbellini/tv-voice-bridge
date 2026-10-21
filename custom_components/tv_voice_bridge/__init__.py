"""Browser microphone bridge to an already-paired Android TV."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CONF_ANDROIDTV_ENTRY_ID, CONF_REMOTE_ENTITY, DOMAIN
from .errors import VoiceError
from .frontend import async_register_frontend
from .manager import BridgeManager
from .target import validate_target
from .websocket import async_register

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the API, frontend and shutdown cleanup."""
    manager = hass.data[DOMAIN] = BridgeManager(hass)
    async_register(hass)
    manager.frontend_url = await async_register_frontend(hass)

    async def shutdown(_event: Event) -> None:
        await manager.unload()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, shutdown)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    try:
        target = await validate_target(
            hass, entry.data[CONF_REMOTE_ENTITY], entry.data.get(CONF_ANDROIDTV_ENTRY_ID)
        )
    except VoiceError as error:
        exception = ConfigEntryNotReady if error.code == "pairing_required" else ConfigEntryError
        raise exception(translation_domain=DOMAIN, translation_key=error.code) from error
    manager: BridgeManager = hass.data[DOMAIN]
    manager.targets[entry.entry_id] = (
        target.entity_id,
        entry.data.get(CONF_ANDROIDTV_ENTRY_ID, target.source_entry_id),
    )
    entry.runtime_data = manager
    entry.async_on_unload(entry.add_update_listener(_async_update))
    return True


async def _async_update(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    manager: BridgeManager = entry.runtime_data
    await manager.unload(entry.entry_id)
    return True
