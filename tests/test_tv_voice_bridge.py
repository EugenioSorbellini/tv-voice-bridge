"""Session lifetimes, buffering and deadlines with a stub TV client."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.tv_voice_bridge.const import MAX_BYTES
from custom_components.tv_voice_bridge.errors import VoiceError
from custom_components.tv_voice_bridge.session import VoiceSession


class Remote:
    def __init__(self):
        self.is_voice_enabled = True
        self.connected = False
        self.disconnects = 0
        self.chunks = []
        self.stream = Mock(
            send_chunk=Mock(side_effect=lambda data: self.chunks.append(data) or True)
        )
        self.start_voice = AsyncMock(return_value=self.stream)

    def open(self, on_voice_close):
        """ClientFactory: the session creates its client through this."""
        self.on_voice_close = on_voice_close
        return self

    async def async_connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False
        self.disconnects += 1


@pytest.fixture(autouse=True)
def no_ready_delay():
    with patch("custom_components.tv_voice_bridge.session.VOICE_READY_DELAY", 0):
        yield


@pytest.mark.asyncio
async def test_late_connect_after_cancellation_is_disconnected():
    remote = Remote()
    started = asyncio.Event()
    finish = asyncio.Event()

    async def stubborn_connect():
        started.set()
        try:
            await finish.wait()
        except asyncio.CancelledError:
            await finish.wait()  # Simulate an uncancellable late transport result.
        remote.connected = True

    remote.async_connect = stubborn_connect
    release = Mock()
    session = VoiceSession(remote.open, release)
    task = asyncio.create_task(session.start())
    await started.wait()
    session.close()
    assert not remote.connected
    finish.set()
    with pytest.raises(VoiceError, match="cancelled"):
        await task
    await session.shutdown()
    assert not remote.connected
    assert remote.disconnects >= 2
    release.assert_called_once()
    remote.start_voice.assert_not_awaited()


@pytest.mark.asyncio
async def test_recording_and_upload_have_separate_deadlines():
    remote = Remote()
    session = VoiceSession(remote.open, Mock())
    await session.start()
    first = session.timer
    assert first.when() - session.loop.time() > 29
    session.feed(bytes(8192))
    assert first.cancelled()
    assert 14 < session.timer.when() - session.loop.time() <= 15
    for _ in range(57):
        session.feed(bytes(8192))
    session.feed(bytes(MAX_BYTES - session.total_bytes))
    assert not remote.chunks, "audio is held until submission"
    result = session.close(flush=True)
    assert result["forwarded_bytes"] == MAX_BYTES
    assert [len(chunk) for chunk in remote.chunks] == [8192] * 58 + [4864]
    assert not result["delivery_failed"]
    assert remote.disconnects  # Graceful shutdown starts immediately.
    await session.shutdown()
    assert remote.disconnects
    assert not session._close_tasks


@pytest.mark.asyncio
async def test_byte_limit_and_idle_expiry():
    remote = Remote()
    session = VoiceSession(remote.open, Mock())
    await session.start()
    for _ in range(29):
        session.feed(bytes(16384))
    with pytest.raises(VoiceError, match="recording_limit"):
        session.feed(bytes(16384))
    assert session.closed
    assert session.error == "recording_limit"
    await session.shutdown()
    session2 = VoiceSession(Remote().open, Mock())
    await session2.start()
    session2._expire()
    assert session2.closed and session2.error == "session_timeout"
    await session2.shutdown()


@pytest.mark.asyncio
async def test_cancel_drops_tail_and_final_failure_is_reported():
    remote = Remote()
    session = VoiceSession(remote.open, Mock())
    await session.start()
    session.feed(bytes(100))
    session.close()
    assert not remote.chunks
    await session.shutdown()
    remote = Remote()
    session = VoiceSession(remote.open, Mock())
    await session.start()
    session.feed(bytes(100))
    remote.stream.send_chunk.return_value = False
    remote.stream.send_chunk.side_effect = None
    assert session.close(flush=True)["delivery_failed"]
    await session.shutdown()


@pytest.mark.asyncio
async def test_cancel_after_streaming_forwards_nothing_and_peak_is_exact():
    remote = Remote()
    session = VoiceSession(remote.open, Mock())
    await session.start()
    for _ in range(10):
        session.feed(bytes(8192))
    session.feed(b"\x00\x80" + b"\xff\x7f")  # -32768, 32767 little-endian
    assert session.peak == 32768
    result = session.close()
    assert not remote.chunks
    assert result["forwarded_bytes"] == 0
    assert result["received_bytes"] == 10 * 8192 + 4
    await session.shutdown()
