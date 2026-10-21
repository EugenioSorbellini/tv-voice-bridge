"""Resolve a paired Android TV without owning or replacing its credentials."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import STORAGE_DIR

from .errors import VoiceError
from .protocol import validate_compatibility

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
    if entry is None or not entry.data.get("host"):
        raise VoiceError("invalid_target")
    return Target(
        item.entity_id,
        entry.entry_id,
        entry.data["host"],
        hass.config.path(STORAGE_DIR, "androidtv_remote_cert.pem"),
        hass.config.path(STORAGE_DIR, "androidtv_remote_key.pem"),
    )


async def validate_target(
    hass: HomeAssistant, entity_id: str, source_entry_id: str | None = None
) -> Target:
    """Validate selection and pairing without opening the assistant on the TV."""
    validate_compatibility()
    target = resolve_target(hass, entity_id, source_entry_id)

    def paired() -> bool:
        return Path(target.certfile).is_file() and Path(target.keyfile).is_file()

    if not await hass.async_add_executor_job(paired):
        raise VoiceError("pairing_required")
    return target
