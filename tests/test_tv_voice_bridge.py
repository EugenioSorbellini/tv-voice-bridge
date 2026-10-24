"""Session lifetimes and actual upstream wire-format compatibility."""

import asyncio
import types
from unittest.mock import AsyncMock, Mock, patch

from androidtvremote2.remote import RemoteProtocol
from androidtvremote2.remotemessage_pb2 import RemoteMessage
from androidtvremote2.voice_stream import VoiceStream
from google.protobuf.internal.decoder import _DecodeVarint
import pytest

from custom_components.tv_voice_bridge import protocol
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

    async def async_connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False
        self.disconnects += 1


@pytest.fixture(autouse=True)
def protocol_adapter():
    with (
        patch(
            "custom_components.tv_voice_bridge.session.configure_voice_protocol",
            new=lambda *_: None,
        ),
        patch("custom_components.tv_voice_bridge.session.VOICE_READY_DELAY", 0),
    ):
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
    session = VoiceSession(remote, release)
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
    session = VoiceSession(remote, Mock())
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
    session = VoiceSession(remote, Mock())
    await session.start()
    for _ in range(29):
        session.feed(bytes(16384))
    with pytest.raises(VoiceError, match="recording_limit"):
        session.feed(bytes(16384))
    assert session.closed
    assert session.error == "recording_limit"
    await session.shutdown()
    session2 = VoiceSession(Remote(), Mock())
    await session2.start()
    session2._expire()
    assert session2.closed and session2.error == "session_timeout"
    await session2.shutdown()


@pytest.mark.asyncio
async def test_cancel_drops_tail_and_final_failure_is_reported():
    remote = Remote()
    session = VoiceSession(remote, Mock())
    await session.start()
    session.feed(bytes(100))
    session.close()
    assert not remote.chunks
    await session.shutdown()
    remote = Remote()
    session = VoiceSession(remote, Mock())
    await session.start()
    session.feed(bytes(100))
    remote.stream.send_chunk.return_value = False
    remote.stream.send_chunk.side_effect = None
    assert session.close(flush=True)["delivery_failed"]
    await session.shutdown()


@pytest.mark.asyncio
async def test_cancel_after_streaming_forwards_nothing_and_peak_is_exact():
    remote = Remote()
    session = VoiceSession(remote, Mock())
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


def test_adapter_rejects_untested_versions():
    with (
        patch.object(protocol, "LIBRARY_VERSION", "99.0.0"),
        pytest.raises(VoiceError, match="unsupported_version"),
    ):
        protocol.validate_compatibility()


@pytest.mark.asyncio
async def test_real_upstream_packets_preserve_pcm_alignment():
    loop = asyncio.get_running_loop()
    frames = []
    remote_protocol = RemoteProtocol(
        loop.create_future(),
        loop.create_future(),
        lambda *_: None,
        lambda *_: None,
        lambda *_: None,
        loop,
        True,
        True,
    )
    remote_protocol.transport = types.SimpleNamespace(
        write=frames.append, is_closing=lambda: False, close=lambda: None
    )
    protocol.configure_voice_protocol(
        types.SimpleNamespace(_remote_message_protocol=remote_protocol)
    )
    begin = RemoteMessage()
    begin.remote_voice_begin.session_id = 7
    remote_protocol._send_message(begin)
    data = b"".join(frames)
    size, offset = _DecodeVarint(data, 0)
    assert len(data) - offset == size
    assert b"\x50\x80\x7d\x58\x10\x60\x02" in data[offset:]
    frames.clear()
    pcm = b"\x00\x80\xff\x7f" * 2048
    VoiceStream(remote_protocol, 7).send_chunk(pcm)
    data = b"".join(frames)
    _, offset = _DecodeVarint(data, 0)
    tag, offset = _DecodeVarint(data, offset)
    assert tag == (31 << 3) | 2
    size, offset = _DecodeVarint(data, offset)
    assert data[offset : offset + size] == pcm
    remote_protocol.close()
