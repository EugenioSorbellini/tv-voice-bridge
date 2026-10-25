"""Voice-only client for the Android TV Remote Service (port 6466).

Pairing stays with the core androidtv_remote integration; this client reuses
its certificate and key. Messages use the generated voice.proto schemas, one per
direction; on the wire each is preceded by its varint length.
See docs/voice-protocol-research.md.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import ssl
from typing import cast

from google.protobuf.message import DecodeError

from .const import CLOSE_TIMEOUT, SAMPLE_RATE
from .errors import VoiceError
from .voice_pb2 import ClientMessage, ServerMessage

_LOGGER = logging.getLogger(__name__)

API_PORT = 6466
# Server pings every 5 seconds; it drops clients after three missed pings.
IDLE_TIMEOUT = 16.0
MAX_MESSAGE_BYTES = 1 << 20

KEYCODE_SEARCH = 84
DIRECTION_SHORT = 3

FEATURE_VOICE = 1 << 3
# Announce exactly what androidtvremote2 did in the live-validated setup
# (PING, KEY, IME, VOICE, POWER, VOLUME, APP_LINK); unused traffic is ignored.
FEATURES = 0b1001101111

# ClientVoiceBegin values, as validated in docs/voice-protocol-research.md.
CHANNEL_IN_MONO = 16
ENCODING_PCM_16BIT = 2


def encode_varint(value: int) -> bytes:
    """Frame length only; protobuf has no public length-delimited API in Python."""
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def decode_varint(data: bytes | bytearray) -> tuple[int, int]:
    """Return (frame length, header size); raise IndexError when incomplete."""
    result = shift = pos = 0
    while True:
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift >= 64:
            raise ValueError("varint too long")


def load_ssl_context(certfile: str, keyfile: str) -> ssl.SSLContext:
    """Blocking; run in an executor. The TV's self-signed certificate is not verified."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.load_cert_chain(certfile, keyfile)
    return context


class VoiceStream:
    """One voice session; the same surface session.py uses today."""

    def __init__(self, client: TvVoiceClient, session_id: int) -> None:
        self._client = client
        self.session_id = session_id
        self._ended = False

    def send_chunk(self, chunk: bytes) -> bool:
        if self._ended or self._client.voice_closed:
            return False
        # Raw PCM in field 31; never logged.
        self._client.send(ClientMessage(voice_audio=chunk))
        return True

    def end(self) -> None:
        if self._ended:
            return
        self._ended = True
        if not self._client.voice_closed:
            self._client.voice_closed = True
            message = ClientMessage()
            message.voice_end.session_id = self.session_id
            self._client.send(message)


class TvVoiceClient(asyncio.Protocol):
    """Connect, answer the handshake and pings, then run one voice session."""

    def __init__(
        self,
        host: str,
        certfile: str,
        keyfile: str,
        loop: asyncio.AbstractEventLoop,
        port: int = API_PORT,
    ) -> None:
        self.host = host
        self.port = port
        self._certfile = certfile
        self._keyfile = keyfile
        self._loop = loop
        # Called once when the TV closes the active voice session.
        self.on_voice_close: Callable[[], None] = lambda: None
        # Diagnostics only: top-level field numbers of each handled TV message.
        self.on_message: Callable[[frozenset[int]], None] = lambda fields: None
        self.transport: asyncio.Transport | None = None
        self.closed: asyncio.Future[Exception | None] = loop.create_future()
        self._started: asyncio.Future[None] = loop.create_future()
        self._voice_offer: asyncio.Future[int] | None = None
        self._buffer = bytearray()
        self._idle: asyncio.TimerHandle | None = None
        self.features = 0
        self.device_info: dict[str, str] = {}
        self.session_id: int | None = None
        self.voice_closed = False

    @property
    def is_voice_enabled(self) -> bool:
        return bool(self.features & FEATURE_VOICE)

    async def async_connect(self) -> None:
        """Return once the TV sends remote_start, i.e. the handshake is complete."""
        context = await self._loop.run_in_executor(
            None, load_ssl_context, self._certfile, self._keyfile
        )
        await self._loop.create_connection(lambda: self, self.host, self.port, ssl=context)
        done, _ = await asyncio.wait(
            (self._started, self.closed), return_when=asyncio.FIRST_COMPLETED
        )
        if self._started not in done:
            raise VoiceError("unavailable")

    async def start_voice(self) -> VoiceStream:
        """Press SEARCH, wait for the TV's voice offer, then send the configured begin.

        Waits until the offer or a disconnect; callers bound it with asyncio.timeout.
        """
        if self.transport is None or self.transport.is_closing():
            raise VoiceError("unavailable")
        if self._voice_offer is not None or self.session_id is not None:
            raise VoiceError("busy")
        self._voice_offer = self._loop.create_future()
        try:
            search = ClientMessage()
            search.key_inject.key_code = KEYCODE_SEARCH
            search.key_inject.direction = DIRECTION_SHORT
            self.send(search)
            done, _ = await asyncio.wait(
                (self._voice_offer, self.closed), return_when=asyncio.FIRST_COMPLETED
            )
            if self._voice_offer not in done:
                raise VoiceError("unavailable")
            session_id = self._voice_offer.result()
            self.session_id = session_id
        finally:
            self._voice_offer = None
        if self.voice_closed:
            # The TV withdrew the offer in the same read that carried it.
            raise VoiceError("session_ended")
        begin = ClientMessage()
        begin.voice_begin.session_id = session_id
        begin.voice_begin.sample_rate = SAMPLE_RATE
        begin.voice_begin.channel_config = CHANNEL_IN_MONO
        begin.voice_begin.audio_format = ENCODING_PCM_16BIT
        self.send(begin)
        return VoiceStream(self, session_id)

    def disconnect(self) -> bool:
        """Begin graceful TLS close; True when wait_closed() has a transport to watch."""
        self._cancel_idle()
        if self.transport and not self.transport.is_closing():
            self.transport.close()
        return self.transport is not None and not self.closed.done()

    async def wait_closed(self) -> bool:
        """Wait for transport close, aborting only when its failure deadline expires.

        Completion confirms transport shutdown, not recognition or TV execution.
        Shield the future: a waiter must never cancel that signal.
        """
        try:
            async with asyncio.timeout(CLOSE_TIMEOUT):
                error = await asyncio.shield(self.closed)
        except TimeoutError:
            if self.transport:
                self.transport.abort()
            return False
        return error is None

    def send(self, message: ClientMessage) -> None:
        if self.transport is None or self.transport.is_closing():
            raise VoiceError("delivery_failed")
        body = message.SerializeToString()
        self.transport.write(encode_varint(len(body)) + body)

    def _reply(self, message: ClientMessage) -> None:
        """Handshake and ping replies; a closing transport just drops them."""
        if self.transport and not self.transport.is_closing():
            body = message.SerializeToString()
            self.transport.write(encode_varint(len(body)) + body)

    # asyncio.Protocol

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = cast("asyncio.Transport", transport)
        self._reset_idle()

    def connection_lost(self, exc: Exception | None) -> None:
        self._cancel_idle()
        if not self.closed.done():
            self.closed.set_result(exc)

    def data_received(self, data: bytes) -> None:
        self._reset_idle()
        self._buffer += data
        while self._buffer:
            try:
                size, pos = decode_varint(self._buffer)
            except IndexError:
                return  # Length not complete yet.
            except ValueError:
                self._fail()
                return
            if size > MAX_MESSAGE_BYTES:
                self._fail()
                return
            if len(self._buffer) < pos + size:
                return
            raw = bytes(self._buffer[pos : pos + size])
            del self._buffer[: pos + size]
            message = ServerMessage()
            try:
                message.ParseFromString(raw)
            except DecodeError:
                # Never log message contents: errors may echo our audio.
                _LOGGER.debug("Ignoring malformed message from TV")
                continue
            self._handle(message)
            self.on_message(frozenset(field.number for field, _ in message.ListFields()))

    def _handle(self, message: ServerMessage) -> None:
        if message.HasField("ping_request"):
            reply = ClientMessage()
            reply.ping_response.val1 = message.ping_request.val1
            self._reply(reply)
        elif message.HasField("configure"):
            configure = message.configure
            self.features = FEATURES & configure.features
            self.device_info = {
                "manufacturer": configure.device_info.vendor,
                "model": configure.device_info.model,
                "sw_version": configure.device_info.app_version,
            }
            reply = ClientMessage()
            reply.configure.features = self.features
            # Same client identity androidtvremote2 announces.
            reply.configure.device_info.unknown1 = 1
            reply.configure.device_info.unknown2 = "1"
            reply.configure.device_info.package_name = "atvremote"
            reply.configure.device_info.app_version = "1.0.0"
            self._reply(reply)
        elif message.HasField("set_active"):
            reply = ClientMessage()
            reply.set_active.active = self.features
            self._reply(reply)
        elif message.HasField("start"):
            if not self._started.done():
                self._started.set_result(None)
        elif message.HasField("voice_begin"):
            # A missing id is 0: the TV's proto3 encoder omits zero values.
            session_id = message.voice_begin.session_id
            if self._voice_offer and not self._voice_offer.done():
                # Record it now: a close can follow in the same TCP read,
                # before start_voice resumes.
                self.session_id = session_id
                self._voice_offer.set_result(session_id)
        elif message.HasField("voice_close"):
            close = message.voice_close
            if (
                close.HasField("session_id")
                and close.session_id == self.session_id
                and not self.voice_closed
            ):
                self.voice_closed = True
                self.on_voice_close()
        elif message.HasField("error"):
            _LOGGER.warning("TV reported a remote protocol error")

    def _fail(self) -> None:
        """A corrupt length cannot be resynchronized."""
        self._buffer.clear()
        if self.transport and not self.transport.is_closing():
            self.transport.abort()

    def _reset_idle(self) -> None:
        self._cancel_idle()
        self._idle = self._loop.call_later(IDLE_TIMEOUT, self._idle_expired)

    def _cancel_idle(self) -> None:
        if self._idle:
            self._idle.cancel()
            self._idle = None

    def _idle_expired(self) -> None:
        _LOGGER.debug("Closing idle TV connection")
        self.disconnect()
