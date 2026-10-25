"""Resolve a paired Android TV without owning or replacing its credentials."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import STORAGE_DIR

from .errors import VoiceError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@dataclass(frozen=True)
class Target:
    """An authorized entity and the core integration that owns its pairing."""

    entity_id: str
    source_entry_id: str
    host: str
    certfile: str
    keyfile: str


def resolve_target(
    hass: HomeAssistant, entity_id: str, source_entry_id: str | None = None
) -> Target:
    registry = er.async_get(hass)
    item = registry.async_get(entity_id)
    if source_entry_id and (item is None or item.config_entry_id != source_entry_id):
        # Entity ids can be renamed; the underlying config entry is stable.
        item = next(
            (
                candidate
                for candidate in er.async_entries_for_config_entry(registry, source_entry_id)
                if candidate.domain == "remote" and candidate.platform == "androidtv_remote"
            ),
            None,
        )
    if (
        item is None
        or item.platform != "androidtv_remote"
        or not item.entity_id.startswith("remote.")
        or item.config_entry_id is None
    ):
        raise VoiceError("invalid_target")
    entry = hass.config_entries.async_get_entry(item.config_entry_id)
    if entry is None or not entry.data.get(CONF_HOST):
        raise VoiceError("invalid_target")
    # Must match core's androidtv_remote helpers.create_api; a test compares them.
    return Target(
        item.entity_id,
        entry.entry_id,
        entry.data[CONF_HOST],
        hass.config.path(STORAGE_DIR, "androidtv_remote_cert.pem"),
        hass.config.path(STORAGE_DIR, "androidtv_remote_key.pem"),
    )


async def validate_target(
    hass: HomeAssistant, entity_id: str, source_entry_id: str | None = None
) -> Target:
    """Validate selection and pairing without opening the assistant on the TV."""
    target = resolve_target(hass, entity_id, source_entry_id)

    def paired() -> bool:
        return Path(target.certfile).is_file() and Path(target.keyfile).is_file()

    if not await hass.async_add_executor_job(paired):
        source = hass.config_entries.async_get_entry(target.source_entry_id)
        if source is not None and source.state is ConfigEntryState.LOADED:
            # The core integration only loads once connected, so the pairing exists elsewhere.
            raise VoiceError("pairing_not_found")
        raise VoiceError("pairing_required")
    return target
