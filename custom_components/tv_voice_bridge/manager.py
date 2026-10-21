"""Connection-owned sessions, binary transport and configuration lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import logging
import secrets
from typing import TYPE_CHECKING

from androidtvremote2 import AndroidTVRemote
from homeassistant.auth.permissions.const import POLICY_CONTROL

from .const import BINARY_HEADER_BYTES, MAX_CHUNK_BYTES, MAX_TERMINAL_ERRORS, TERMINAL_ERROR_SECONDS
from .errors import VoiceError
from .session import VoiceSession
from .target import Target, resolve_target

if TYPE_CHECKING:
    from homeassistant.components.websocket_api import ActiveConnection
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass
class SessionRecord:
    connection: ActiveConnection
    entry_id: str
    target: Target
    token: str
    request_id: str
    session: VoiceSession
    sequence: int = 0
    binary_id: int = 0
    remove_binary: Callable[[], None] | None = None


@dataclass
class TerminalError:
    """Bounded failure metadata, without retaining a session or its audio."""

    connection: ActiveConnection
    entry_id: str
    entity_id: str
    code: str
    timer: asyncio.TimerHandle


@dataclass
class BridgeManager:
    """One recording per TV; independent ownership for each browser connection."""

    hass: HomeAssistant
    targets: dict[str, tuple[str, str]] = field(default_factory=dict)
    records: dict[str, SessionRecord] = field(default_factory=dict)
    sessions: dict[VoiceSession, str] = field(default_factory=dict)
    terminal_errors: dict[str, TerminalError] = field(default_factory=dict)
    frontend_url: str | None = None
    shutting_down: bool = False

    def target(self, entity_id: str | None) -> tuple[str, Target]:
        candidates = []
        for entry_id, (entity, source) in self.targets.items():
            try:
                target = resolve_target(self.hass, entity, source)
            except VoiceError:
                continue
            candidates.append((entry_id, target))
        if entity_id is None:
            if len(candidates) != 1:
                raise VoiceError("select_target")
            return candidates[0]
        for entry_id, target in candidates:
            if target.entity_id == entity_id:
                return entry_id, target
        raise VoiceError("invalid_target")

    @staticmethod
    def allowed(connection: ActiveConnection, entity_id: str) -> bool:
        return connection.user.permissions.check_entity(entity_id, POLICY_CONTROL)

    def owned(self, connection: ActiveConnection, token: str) -> SessionRecord:
        record = self.records.get(token)
        if record is None or record.connection is not connection:
            failure = self.terminal_errors.get(token)
            if failure is not None and failure.connection is connection:
                if not self.allowed(connection, failure.entity_id):
                    raise VoiceError("unauthorized")
                raise VoiceError(failure.code)
            raise VoiceError("session_ended")
        if not self.allowed(connection, record.target.entity_id):
            record.session.error = "unauthorized"
            record.session.close()
            raise VoiceError("unauthorized")
        return record

    def _forget_error(self, token: str) -> None:
        if failure := self.terminal_errors.pop(token, None):
            failure.timer.cancel()
            self.hass.loop.call_soon(
                failure.connection.subscriptions.pop, "tv_voice_bridge:" + token, None
            )

    def _remember_error(self, record: SessionRecord) -> None:
        assert record.session.error is not None
        token = record.token
        while len(self.terminal_errors) >= MAX_TERMINAL_ERRORS:
            self._forget_error(next(iter(self.terminal_errors)))
        self.terminal_errors[record.token] = TerminalError(
            record.connection,
            record.entry_id,
            record.target.entity_id,
            record.session.error,
            self.hass.loop.call_later(TERMINAL_ERROR_SECONDS, self._forget_error, record.token),
        )
        record.connection.subscriptions["tv_voice_bridge:" + token] = lambda: self._forget_error(
            token
        )

    async def start(
        self, connection: ActiveConnection, request_id: str, entity_id: str | None
    ) -> SessionRecord:
        if self.shutting_down:
            raise VoiceError("unavailable")
        entry_id, target = self.target(entity_id)
        if not self.allowed(connection, target.entity_id):
            raise VoiceError("unauthorized")
        if any(
            record.target.source_entry_id == target.source_entry_id
            for record in self.records.values()
        ):
            raise VoiceError("busy")
        if any(
            record.connection is connection and record.request_id == request_id
            for record in self.records.values()
        ):
            raise VoiceError("invalid_request")
        token = secrets.token_hex(16)
        subscription = "tv_voice_bridge:" + token
        remote = AndroidTVRemote(
            client_name="Home Assistant TV Voice",
            certfile=target.certfile,
            keyfile=target.keyfile,
            host=target.host,
            loop=self.hass.loop,
            enable_ime=True,
            enable_voice=True,
        )

        def release() -> None:
            self.records.pop(token, None)
            if record.remove_binary:
                record.remove_binary()
            if session.error and record.remove_binary and not self.shutting_down:
                self._remember_error(record)
            else:
                self.hass.loop.call_soon(connection.subscriptions.pop, subscription, None)

        def disconnected() -> None:
            self.sessions.pop(session, None)

        session = VoiceSession(remote, release, self.hass.loop, on_disconnect=disconnected)
        record = SessionRecord(connection, entry_id, target, token, request_id, session)
        self.records[token] = record
        self.sessions[session] = entry_id
        connection.subscriptions[subscription] = session.close
        try:
            await session.start()
            # Permission may have changed during network setup.
            self.owned(connection, token)
            record.binary_id, record.remove_binary = connection.async_register_binary_handler(
                lambda hass, owner, payload: self.audio(record, owner, payload)
            )
            return record
        except BaseException:
            session.close()
            raise

    def audio(self, record: SessionRecord, connection: ActiveConnection, payload: bytes) -> None:
        """Never raise with payload data: HA may log exceptions from handlers."""
        try:
            self.owned(connection, record.token)
            if (
                len(payload) <= BINARY_HEADER_BYTES
                or len(payload) > BINARY_HEADER_BYTES + MAX_CHUNK_BYTES
            ):
                raise VoiceError("invalid_audio")
            if not secrets.compare_digest(payload[:16], bytes.fromhex(record.token)):
                raise VoiceError("invalid_audio")
            sequence = int.from_bytes(payload[16:20], "little")
            if sequence != record.sequence:
                raise VoiceError("invalid_audio")
            record.session.feed(payload[BINARY_HEADER_BYTES:])
            record.sequence += 1
        except Exception as error:
            record.session.error = (
                error.code if isinstance(error, VoiceError) else "delivery_failed"
            )
            # Log types/codes only, never an exception string or audio payload.
            _LOGGER.debug("Voice binary stream ended (%s)", record.session.error)
            record.session.close()

    def cancel(self, connection: ActiveConnection, request_id: str) -> None:
        for record in list(self.records.values()):
            if record.connection is connection and record.request_id == request_id:
                record.session.close()

    async def unload(self, entry_id: str | None = None) -> None:
        if entry_id is None:
            self.shutting_down = True
        if entry_id is not None:
            self.targets.pop(entry_id, None)
        sessions = [
            session
            for session, owner in list(self.sessions.items())
            if entry_id is None or owner == entry_id
        ]
        await asyncio.gather(*(session.shutdown() for session in sessions))
        for token, failure in list(self.terminal_errors.items()):
            if entry_id is None or failure.entry_id == entry_id:
                self._forget_error(token)
