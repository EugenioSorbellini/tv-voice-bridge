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
    """A TV connection that completes after cancellation is closed, not used.

    Starts a session whose connect step ignores cancellation and finishes late, closes
    the session while connect is pending, then lets connect complete.

    Verifies: the client is disconnected on close and again when the late connect lands;
    start fails with cancelled; voice is never requested; the TV reservation is released
    exactly once.
    """
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
    """Deadlines and submission of a full 15-second recording.

    Starts a session against a stub TV client and feeds audio in 8192-byte frames up to
    exactly 480000 bytes, the 15-second limit, then submits it.

    Verifies: before any audio, the first-audio deadline is about 30 s; the first frame
    replaces it with a 15 s inactivity deadline; nothing reaches the TV before stop; stop
    forwards all 480000 bytes as 58 chunks of 8192 bytes plus a 4864-byte tail, without a
    delivery failure; the graceful disconnect starts immediately and no close task remains
    after shutdown.
    """
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
    """Recording limit and session timeout.

    Feeds 16384-byte frames until the next one would pass 480000 bytes, then fires a
    second session's timeout handler directly.

    Verifies: the overflowing frame raises recording_limit and closes the session with
    that error; the timeout closes the session with session_timeout. The handler is called
    directly, so the idle and lifetime timers that schedule it are not exercised.
    """
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
    """Cancel discards held audio; a send rejected at submission is reported.

    The first session feeds 100 bytes and closes without submitting. The second feeds 100
    bytes, makes the TV stream reject chunks, and submits.

    Verifies: cancel forwards nothing; the rejected chunk sets delivery_failed in the
    submission result.
    """
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
    """Cancel after a long upload forwards nothing; the peak is exact at the int16 extremes.

    Feeds ten 8192-byte frames plus one frame holding -32768 and 32767, then cancels.

    Verifies: the peak is 32768, the magnitude of -32768; nothing reaches the TV; the
    result reports 0 forwarded and all 81924 received bytes.
    """
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
