"""Support diagnostics that deliberately exclude audio, tokens and TV identity."""

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, VERSION
from .manager import BridgeManager


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    manager: BridgeManager = hass.data[DOMAIN]
    return {
        "integration_version": VERSION,
        "configured": entry.entry_id in manager.targets,
        "active_sessions": sum(
            record.entry_id == entry.entry_id for record in manager.records.values()
        ),
        "processing_sessions": sum(
            owner == entry.entry_id and session.closed
            for session, owner in manager.sessions.items()
        ),
    }
