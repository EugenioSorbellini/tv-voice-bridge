"""Version-gated voice adapter for the Google Remote Service wire format.

TLS, pairing, handshake and framing remain owned by androidtvremote2. Only this
bridge's dedicated protocol instance is adapted. Generated, direction-specific
voice schemas replace the upstream nested-audio model; see voice.proto and
docs/protocol-findings-2026-10-22.md. No upstream API exposes server voice-close
or graceful-close completion yet, so private accesses are isolated here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import version
import logging
from typing import Any

from google.protobuf.message import DecodeError

from .const import CLOSE_TIMEOUT, SAMPLE_RATE, SUPPORTED_LIBRARY_VERSION
from .errors import VoiceError
from .voice_pb2 import ClientVoiceMessage, ServerVoiceMessage

# Read package metadata once during executor-based integration import.
LIBRARY_VERSION = version("androidtvremote2")
_LOGGER = logging.getLogger(__name__)


def validate_compatibility() -> None:
    """Fail clearly before touching private APIs of an untested library."""
    if LIBRARY_VERSION != SUPPORTED_LIBRARY_VERSION:
        raise VoiceError("unsupported_version")


@dataclass(frozen=True)
class ConnectionClose:
    """Keep the completion signal after upstream disconnect clears its protocol."""

    completed: asyncio.Future[Exception | None]
    transport: asyncio.Transport

    async def wait(self) -> bool:
        """Wait for transport close, aborting only when its failure deadline expires.

        Completion confirms transport shutdown, not recognition or TV execution.
        Shield the protocol's future: a waiter must never cancel that signal.
        """
        try:
            async with asyncio.timeout(CLOSE_TIMEOUT):
                error = await asyncio.shield(self.completed)
        except TimeoutError:
            self.transport.abort()
            return False
        return error is None


def disconnect(remote: Any) -> ConnectionClose | None:
    """Begin graceful close synchronously; preserve any pending transport signal."""
    protocol = getattr(remote, "_remote_message_protocol", None)
    completion = getattr(protocol, "on_con_lost", None)
    transport = getattr(protocol, "transport", None)
    closing = (
        ConnectionClose(completion, transport)
        if isinstance(completion, asyncio.Future) and transport is not None
        else None
    )
    remote.disconnect()
    return closing


class VoiceProtocol:
    """Translate only voice fields and surface a matching TV audio-close event."""

    def __init__(self, remote: Any, on_voice_close: Callable[[], None]) -> None:
        self._protocol = remote._remote_message_protocol
        self._send = self._protocol._send_message
        self._handle = self._protocol._handle_message
        self._on_voice_close = on_voice_close
        self._session_id: int | None = None
        self._voice_closed = False
        self._protocol._send_message = self.send
        self._protocol._handle_message = self.handle

    def send(self, message: Any, should_debug_log: bool = True) -> None:
        """Use generated client schemas, never passing voice data to debug logs."""
        outgoing = ClientVoiceMessage()
        if message.HasField("remote_voice_begin"):
            if self._voice_closed and message.remote_voice_begin.session_id == self._session_id:
                raise VoiceError("session_ended")
            self._session_id = message.remote_voice_begin.session_id
            self._voice_closed = False
            outgoing.begin.session_id = self._session_id
            outgoing.begin.sample_rate = SAMPLE_RATE
            outgoing.begin.channel_config = 16
            outgoing.begin.audio_format = 2
        elif message.HasField("remote_voice_payload"):
            if self._voice_closed:
                raise VoiceError("session_ended")
            outgoing.audio = message.remote_voice_payload.samples
        elif message.HasField("remote_voice_end"):
            if self._voice_closed:
                return  # TV has already ended this session; do not restart/end it again.
            outgoing.end.session_id = message.remote_voice_end.session_id
            self._voice_closed = True
        else:
            self._send(message, should_debug_log)
            return
        self._send(outgoing, False)

    def handle(self, raw: bytes) -> None:
        """Field 31 from the TV is a session-close request, never audio samples."""
        incoming = ServerVoiceMessage()
        try:
            incoming.ParseFromString(raw)
        except DecodeError:
            # Upstream handles malformed messages; do not log their contents here.
            self._handle(raw)
            return
        if (
            incoming.HasField("begin")
            and incoming.begin.HasField("session_id")
            and self._session_id is None
        ):
            # A close can follow the offer in the same TCP read, before
            # upstream start_voice resumes to send the client begin.
            self._session_id = incoming.begin.session_id
        if incoming.HasField("close"):
            close = incoming.close
            if (
                close.HasField("session_id")
                and close.session_id == self._session_id
                and not self._voice_closed
            ):
                self._voice_closed = True
                self._on_voice_close()
            return
        # Upstream error messages may echo a client message, including audio.
        # Check its descriptor, but never send the echoed payload to its logger.
        from androidtvremote2.remotemessage_pb2 import RemoteMessage

        upstream = RemoteMessage()
        try:
            upstream.ParseFromString(raw)
        except DecodeError:
            self._handle(raw)
            return
        if upstream.HasField("remote_error"):
            _LOGGER.warning("TV reported a remote protocol error")
            return
        self._handle(raw)


def configure_voice_protocol(
    remote: Any, on_voice_close: Callable[[], None] = lambda: None
) -> VoiceProtocol:
    """Adapt a dedicated connection after its handshake, before requesting voice."""
    validate_compatibility()
    return VoiceProtocol(remote, on_voice_close)
