"""Bounded in-memory audio with owned startup, idle and shutdown lifetimes."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import struct
from typing import TYPE_CHECKING, Any

from .const import (
    CHUNK_BYTES,
    CONNECT_TIMEOUT,
    FIRST_AUDIO_TIMEOUT,
    MAX_BYTES,
    MAX_CHUNK_BYTES,
    PROCESSING_GRACE_SECONDS,
    SESSION_TIMEOUT,
    UPLOAD_IDLE_SECONDS,
    VOICE_READY_DELAY,
    VOICE_START_TIMEOUT,
)
from .errors import VoiceError
from .protocol import configure_voice_protocol

if TYPE_CHECKING:
    from androidtvremote2 import AndroidTVRemote
    from androidtvremote2.voice_stream import VoiceStream


class VoiceSession:
    """Own every task and transport, including late startup and processing grace."""

    def __init__(
        self,
        remote: AndroidTVRemote,
        on_close: Callable[[], None],
        loop: asyncio.AbstractEventLoop | None = None,
        on_disconnect: Callable[[], None] = lambda: None,
    ) -> None:
        self.remote = remote
        self.on_close = on_close
        self.on_disconnect = on_disconnect
        self.loop = loop or asyncio.get_running_loop()
        self.stream: VoiceStream | None = None
        self.closed = False
        self.buffer = bytearray()
        self.total_bytes = 0
        self.forwarded_bytes = 0
        self.peak = 0
        self.delivery_failed = False
        self.error: str | None = None
        self.timer: asyncio.TimerHandle | None = None
        self._lifetime: asyncio.TimerHandle | None = None
        self._disconnect_timer: asyncio.TimerHandle | None = None
        self._start_task: asyncio.Task[None] | None = None
        self._disconnected = False

    async def start(self) -> None:
        """Start a cancellable task; its finally also catches late transports."""
        if self.closed or self._start_task is not None:
            raise VoiceError("cancelled")
        self._lifetime = self.loop.call_later(SESSION_TIMEOUT, self._expire)
        self._start_task = self.loop.create_task(self._connect())
        self._start_task.add_done_callback(self._startup_done)
        try:
            await self._start_task
        except asyncio.CancelledError:
            was_closed = self.closed
            self.close()
            if was_closed:
                raise VoiceError("cancelled") from None
            raise
        except Exception:
            self.close()
            raise

    async def _connect(self) -> None:
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                await self.remote.async_connect()
            if self.closed:
                raise VoiceError("cancelled")
            await asyncio.sleep(VOICE_READY_DELAY)
            if self.closed:
                raise VoiceError("cancelled")
            if not self.remote.is_voice_enabled:
                raise VoiceError("voice_unsupported")
            configure_voice_protocol(self.remote)
            stream = await self.remote.start_voice(timeout=VOICE_START_TIMEOUT)
            if self.closed:
                stream.end()
                raise VoiceError("cancelled")
            self.stream = stream
            self._arm_idle(FIRST_AUDIO_TIMEOUT)
        finally:
            if self.closed:
                # disconnect() before create_connection() resolves is not enough.
                self._disconnect()

    def _arm_idle(self, seconds: float) -> None:
        if self.timer:
            self.timer.cancel()
        self.timer = self.loop.call_later(seconds, self._expire)

    def _expire(self) -> None:
        self.error = "session_timeout"
        self.close()

    def feed(self, audio: bytes) -> None:
        """Accept PCM only, with a byte cap independent of network transfer time."""
        if self.closed or self.stream is None:
            raise VoiceError("session_ended")
        if not audio or len(audio) > MAX_CHUNK_BYTES or len(audio) % 2:
            raise VoiceError("invalid_audio")
        if self.total_bytes + len(audio) > MAX_BYTES:
            self.error = "recording_limit"
            self.close()
            raise VoiceError("recording_limit")
        self._arm_idle(UPLOAD_IDLE_SECONDS)
        self.total_bytes += len(audio)
        self.peak = max(
            self.peak, max(abs(sample[0]) for sample in struct.iter_unpack("<h", audio))
        )
        self.buffer.extend(audio)
        try:
            while len(self.buffer) >= CHUNK_BYTES:
                if not self.stream.send_chunk(bytes(self.buffer[:CHUNK_BYTES])):
                    raise VoiceError("delivery_failed")
                self.forwarded_bytes += CHUNK_BYTES
                del self.buffer[:CHUNK_BYTES]
        except Exception:
            self.error = "delivery_failed"
            self.close()
            raise

    def close(self, flush: bool = False) -> dict[str, Any]:
        """End audio once. Keep successful submissions alive for processing."""
        if self.closed:
            return self.result()
        self.closed = True
        for timer in (self.timer, self._lifetime):
            if timer:
                timer.cancel()
        if (
            self._start_task
            and not self._start_task.done()
            and self._start_task is not asyncio.current_task()
        ):
            self._start_task.cancel()
        try:
            if self.stream:
                try:
                    if flush and self.buffer:
                        if not self.stream.send_chunk(bytes(self.buffer)):
                            raise VoiceError("delivery_failed")
                        self.forwarded_bytes += len(self.buffer)
                finally:
                    self.stream.end()
        except Exception:
            self.delivery_failed = True
            self.error = "delivery_failed"
        finally:
            self.buffer.clear()
            try:
                self.on_close()
            finally:
                if flush and self.stream and not self.delivery_failed:
                    self._disconnect_timer = self.loop.call_later(
                        PROCESSING_GRACE_SECONDS, self._disconnect
                    )
                else:
                    self._disconnect()
        return self.result()

    def _disconnect(self) -> None:
        # Always repeat transport cleanup: startup may complete after cancellation.
        self.remote.disconnect()
        if not self._disconnected and (self._start_task is None or self._start_task.done()):
            self._disconnected = True
            self.on_disconnect()

    def _startup_done(self, _task: asyncio.Task[None]) -> None:
        if self.closed and not self._disconnect_timer:
            self._disconnect()

    async def shutdown(self) -> None:
        """Unload/shutdown waits for startup and bypasses processing grace."""
        self.close()
        if self._disconnect_timer:
            self._disconnect_timer.cancel()
        task = self._start_task
        if task and task is not asyncio.current_task():
            await asyncio.gather(task, return_exceptions=True)
        self._disconnect()

    def result(self) -> dict[str, Any]:
        return {
            "received_bytes": self.total_bytes,
            "forwarded_bytes": self.forwarded_bytes,
            "peak": self.peak,
            "delivery_failed": self.delivery_failed,
            "error": self.error,
        }
