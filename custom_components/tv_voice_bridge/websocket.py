"""Authenticated JSON control messages; audio is accepted only as binary."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
import probatio as vol

from .const import CHUNK_BYTES, DOMAIN, MAX_BYTES, MAX_SECONDS, SAMPLE_RATE
from .errors import VoiceError
from .manager import BridgeManager

_LOGGER = logging.getLogger(__name__)
TOKEN = vol.All(str, vol.Match(r"^[0-9a-f]{32}$"))


def _manager(hass: HomeAssistant) -> BridgeManager:
    return hass.data[DOMAIN]


def _error(connection: websocket_api.ActiveConnection, message: dict[str, Any], code: str) -> None:
    connection.send_error(
        message["id"], code, code, translation_domain=DOMAIN, translation_key=code
    )


@websocket_api.websocket_command(
    {
        "type": DOMAIN + "/start",
        vol.Required("request_id"): TOKEN,
        vol.Optional("remote_entity"): cv.entity_id,
    }
)
@websocket_api.async_response
async def start(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, message: dict[str, Any]
) -> None:
    try:
        record = await _manager(hass).start(
            connection, message["request_id"], message.get("remote_entity")
        )
    except VoiceError as error:
        _error(connection, message, error.code)
        return
    except Exception as error:
        _LOGGER.warning("Cannot start TV voice (%s)", type(error).__name__)
        _error(connection, message, "unavailable")
        return
    connection.send_result(
        message["id"],
        {
            "session_id": record.token,
            "binary_handler_id": record.binary_id,
            "sample_rate": SAMPLE_RATE,
            "chunk_bytes": CHUNK_BYTES,
            "max_seconds": MAX_SECONDS,
            "max_bytes": MAX_BYTES,
            "protocol_version": 2,
        },
    )


@websocket_api.websocket_command(
    {
        "type": DOMAIN + "/progress",
        vol.Required("session_id"): TOKEN,
        vol.Required("sequence"): vol.All(int, vol.Range(min=0)),
    }
)
@callback
def progress(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, message: dict[str, Any]
) -> None:
    try:
        record = _manager(hass).owned(connection, message["session_id"])
        if record.sequence != message["sequence"]:
            record.session.close()
            raise VoiceError("invalid_audio")
        connection.send_result(
            message["id"],
            {"sequence": record.sequence, "received_bytes": record.session.total_bytes},
        )
    except VoiceError as error:
        _error(connection, message, error.code)


@websocket_api.websocket_command({"type": DOMAIN + "/cancel", vol.Required("request_id"): TOKEN})
@callback
def cancel(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, message: dict[str, Any]
) -> None:
    _manager(hass).cancel(connection, message["request_id"])
    connection.send_result(message["id"])


@websocket_api.websocket_command(
    {
        "type": DOMAIN + "/stop",
        vol.Required("session_id"): TOKEN,
        vol.Optional("cancel", default=False): bool,
        vol.Optional("expected_bytes"): vol.All(int, vol.Range(min=0, max=MAX_BYTES)),
    }
)
@websocket_api.async_response
async def stop(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, message: dict[str, Any]
) -> None:
    try:
        record = _manager(hass).owned(connection, message["session_id"])
        if not message["cancel"] and message.get("expected_bytes") != record.session.total_bytes:
            record.session.close()
            raise VoiceError("delivery_failed")
        record.session.close(flush=not message["cancel"])
        connection.send_result(message["id"], await record.session.wait_closed())
    except VoiceError as error:
        _error(connection, message, error.code)


@websocket_api.websocket_command({"type": DOMAIN + "/list"})
@callback
def list_targets(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, message: dict[str, Any]
) -> None:
    manager = _manager(hass)
    targets = []
    for entity, source in manager.targets.values():
        try:
            from .target import resolve_target  # Avoid resolving unconfigured/removed TVs.

            target = resolve_target(hass, entity, source)
        except VoiceError:
            continue
        if manager.allowed(connection, target.entity_id):
            state = hass.states.get(target.entity_id)
            targets.append(
                {"entity_id": target.entity_id, "name": state.name if state else target.entity_id}
            )
    connection.send_result(message["id"], targets)


@callback
def async_register(hass: HomeAssistant) -> None:
    for handler in (start, progress, cancel, stop, list_targets):
        websocket_api.async_register_command(hass, handler)
