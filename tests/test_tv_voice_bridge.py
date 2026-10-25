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
async def test_byte_limit_ends_the_session():
    """Recording limit.

    Feeds 16384-byte frames until the next one would pass 480000 bytes.

    Verifies: the overflowing frame raises recording_limit and closes the session with
    that error.
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


@pytest.mark.asyncio
@pytest.mark.parametrize("deadline", ["first_audio", "upload_idle", "lifetime"])
async def test_session_timers_end_the_session(deadline):
    """Each session deadline fires on its own timer.

    Shortens one deadline at a time to a few milliseconds, leaving the others long:
    first_audio sends nothing after voice starts; upload_idle sends one frame and then
    stops; lifetime keeps sending a frame every 5 ms, which re-arms the idle deadline.

    Verifies: in each case the timer closes the session with session_timeout and the
    TV client is disconnected. Continued uploads don't extend the session lifetime.
    """
    timeouts = {"FIRST_AUDIO_TIMEOUT": 60, "UPLOAD_IDLE_SECONDS": 60, "SESSION_TIMEOUT": 60}
    timeouts[
        {
            "first_audio": "FIRST_AUDIO_TIMEOUT",
            "upload_idle": "UPLOAD_IDLE_SECONDS",
            "lifetime": "SESSION_TIMEOUT",
        }[deadline]
    ] = 0.02
    remote = Remote()
    with patch.multiple("custom_components.tv_voice_bridge.session", **timeouts):
        session = VoiceSession(remote.open, Mock())
        await session.start()
        if deadline == "upload_idle":
            session.feed(bytes(2))
        for _ in range(40):
            if session.closed:
                break
            if deadline == "lifetime":
                session.feed(bytes(2))
            await asyncio.sleep(0.005)
    assert session.closed
    assert session.error == "session_timeout"
    assert remote.disconnects
    await session.shutdown()


@pytest.mark.asyncio
async def test_tv_without_voice_is_refused_before_requesting_voice():
    """A TV that doesn't offer voice is refused after connecting.

    Starts a session against a TV client whose handshake left voice disabled.

    Verifies: start fails with voice_unsupported; voice is never requested; the client
    is disconnected and the TV reservation released.
    """
    remote = Remote()
    remote.is_voice_enabled = False
    release = Mock()
    session = VoiceSession(remote.open, release)
    with pytest.raises(VoiceError, match="voice_unsupported"):
        await session.start()
    remote.start_voice.assert_not_awaited()
    assert remote.disconnects
    release.assert_called_once()
    await session.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["connect", "voice_start"])
async def test_connect_and_voice_start_limits(phase):
    """The TV connection and the voice request each have their own time limit.

    Shortens CONNECT_TIMEOUT or VOICE_START_TIMEOUT to 10 ms and makes that step of
    the stub TV hang.

    Verifies: start raises TimeoutError (reported to the card as unavailable); for a
    connect timeout voice is never requested; the client is disconnected and the TV
    reservation released.
    """
    remote = Remote()
    hang = asyncio.Event()
    if phase == "connect":
        remote.async_connect = hang.wait
    else:
        remote.start_voice = AsyncMock(side_effect=hang.wait)
    release = Mock()
    name = "CONNECT_TIMEOUT" if phase == "connect" else "VOICE_START_TIMEOUT"
    with patch(f"custom_components.tv_voice_bridge.session.{name}", 0.01):
        session = VoiceSession(remote.open, release)
        with pytest.raises(TimeoutError):
            await session.start()
    if phase == "connect":
        remote.start_voice.assert_not_awaited()
    assert remote.disconnects
    release.assert_called_once()
    await session.shutdown()


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
