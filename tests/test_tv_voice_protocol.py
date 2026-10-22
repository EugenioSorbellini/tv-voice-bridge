"""Real upstream framing plus direction-specific voice and transport lifecycles."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

from androidtvremote2 import AndroidTVRemote
from androidtvremote2.remote import RemoteProtocol
from androidtvremote2.remotemessage_pb2 import RemoteMessage
from androidtvremote2.voice_stream import VoiceStream
from google.protobuf.internal.decoder import _DecodeVarint
import pytest

from custom_components.tv_voice_bridge import protocol
from custom_components.tv_voice_bridge.errors import VoiceError
from custom_components.tv_voice_bridge.session import VoiceSession
from custom_components.tv_voice_bridge.voice_pb2 import ClientVoiceMessage, ServerVoiceMessage


@pytest.fixture
async def wire():
    loop = asyncio.get_running_loop()
    remote = AndroidTVRemote("test", "unused.pem", "unused.key", "tv.invalid", loop=loop)
    proto = RemoteProtocol(
        loop.create_future(), loop.create_future(), Mock(), Mock(), Mock(), loop, True, True
    )
    frames = []
    transport = Mock()
    transport.write.side_effect = frames.append
    transport.is_closing.return_value = False
    transport.close.side_effect = lambda: setattr(transport.is_closing, "return_value", True)
    proto.transport = transport
    remote._remote_message_protocol = proto
    yield remote, proto, transport, frames
    proto.close()
    proto.connection_lost(None)


def messages(frames):
    wire = b"".join(frames)
    result = []
    while wire:
        size, offset = _DecodeVarint(wire, 0)
        result.append(wire[offset : offset + size])
        wire = wire[offset + size :]
    return result


def send_begin(proto, session_id=7):
    begin = RemoteMessage()
    begin.remote_voice_begin.session_id = session_id
    proto._send_message(begin)


def server_close(proto, session_id=7):
    close = ServerVoiceMessage()
    close.close.session_id = session_id
    proto._handle_message(close.SerializeToString())


@pytest.mark.parametrize("session_id", [0, 7, 128, 2147483647, -1, -2147483648])
async def test_generated_client_schema_preserves_audio_and_signed_session(wire, session_id):
    remote, proto, _, frames = wire
    protocol.configure_voice_protocol(remote)
    send_begin(proto, session_id)
    begin = ClientVoiceMessage.FromString(messages(frames)[0]).begin
    assert begin.session_id == session_id
    assert (begin.sample_rate, begin.channel_config, begin.audio_format) == (16000, 16, 2)
    frames.clear()
    audio = b"\x00\x80\xff\x7f" * 2048
    stream = VoiceStream(proto, session_id)
    assert stream.send_chunk(audio)
    # Independent wire assertion: field 31's contents are the PCM itself.
    assert messages(frames) == [b"\xfa\x01\x80\x40" + audio]
    frames.clear()
    stream.end()
    assert ClientVoiceMessage.FromString(messages(frames)[0]).end.session_id == session_id


async def test_server_close_is_matched_once_and_stops_audio_without_echo(wire):
    remote, proto, _, frames = wire
    closed = Mock()
    protocol.configure_voice_protocol(remote, closed)
    send_begin(proto)
    frames.clear()
    server_close(proto, 8)
    missing = ServerVoiceMessage()
    missing.close.SetInParent()
    proto._handle_message(missing.SerializeToString())
    closed.assert_not_called()
    server_close(proto)
    server_close(proto)
    closed.assert_called_once_with()
    stream = VoiceStream(proto, 7)
    with pytest.raises(VoiceError, match="session_ended"):
        stream.send_chunk(bytes(8192))
    stream.end()
    assert not frames  # No tail, duplicate end, or payload after TV close.


async def test_handshake_ping_and_voice_begin_keep_upstream_behavior(wire):
    remote, proto, _, frames = wire
    protocol.configure_voice_protocol(remote)
    task = asyncio.create_task(remote.start_voice(timeout=1))
    await asyncio.sleep(0)
    server = ServerVoiceMessage()
    server.begin.session_id = 7
    server.begin.package_name.extend(["first", "second"])
    proto._handle_message(server.SerializeToString())
    stream = await task
    assert stream.session_id == 7
    assert ClientVoiceMessage.FromString(messages(frames)[-1]).begin.sample_rate == 16000
    ping = RemoteMessage()
    ping.remote_ping_request.val1 = 19
    proto._handle_message(ping.SerializeToString())
    assert RemoteMessage.FromString(messages(frames)[-1]).remote_ping_response.val1 == 19
    stream.end()


async def test_close_between_server_offer_and_client_begin_cannot_reopen_voice(wire):
    remote, proto, _, frames = wire
    closed = Mock()
    protocol.configure_voice_protocol(remote, closed)
    begin = ServerVoiceMessage()
    begin.begin.session_id = 7
    proto._handle_message(begin.SerializeToString())
    server_close(proto)
    closed.assert_called_once_with()
    with pytest.raises(VoiceError, match="session_ended"):
        send_begin(proto)
    assert not frames


@pytest.mark.parametrize("raw", [b"\xfa\x01\x02\x08", b"\x0a\x01\xff"])
async def test_malformed_message_is_handled_without_exposing_payload(wire, raw):
    remote, proto, _, _ = wire
    closed = Mock()
    protocol.configure_voice_protocol(remote, closed)
    proto._handle_message(raw)
    closed.assert_not_called()


async def test_echoed_audio_and_close_ids_never_reach_debug_logs(wire, caplog):
    remote, proto, _, _ = wire
    caplog.set_level("DEBUG")
    protocol.configure_voice_protocol(remote)
    send_begin(proto, 999271)
    stream = VoiceStream(proto, 999271)
    stream.send_chunk(b"PRIVATE_AUDIO" * 1024)
    error = RemoteMessage()
    error.remote_error.message.remote_voice_payload.samples = b"PRIVATE_AUDIO"
    proto._handle_message(error.SerializeToString())
    server_close(proto, 999271)
    assert "TV reported a remote protocol error" in caplog.text
    assert "PRIVATE_AUDIO" not in caplog.text
    assert "999271" not in caplog.text


async def start_session(wire):
    remote, proto, _, _ = wire
    remote.async_connect = AsyncMock()

    async def start_voice(**kwargs):
        send_begin(proto)
        return VoiceStream(proto, 7)

    remote.start_voice = AsyncMock(side_effect=start_voice)
    released, disconnected = Mock(), Mock()
    session = VoiceSession(remote, released, on_disconnect=disconnected)
    with patch("custom_components.tv_voice_bridge.session.VOICE_READY_DELAY", 0):
        await session.start()
    return session, released, disconnected


async def test_submission_waits_for_real_close_and_preserves_queued_tail(wire):
    _, proto, transport, frames = wire
    session, released, disconnected = await start_session(wire)
    session.feed(b"\x01\x02" * 50)
    session.close(flush=True)
    transport.close.assert_called_once()
    released.assert_called_once()
    disconnected.assert_not_called()
    sent = [ClientVoiceMessage.FromString(raw) for raw in messages(frames)]
    assert sent[-2].audio[:100] == b"\x01\x02" * 50
    assert sent[-1].HasField("end")
    waiter = asyncio.create_task(session.wait_closed())
    await asyncio.sleep(0)
    assert not waiter.done()
    proto.connection_lost(None)
    result = await waiter
    assert result["forwarded_bytes"] == 100
    assert not result["delivery_failed"]
    disconnected.assert_called_once()
    transport.abort.assert_not_called()


@pytest.mark.parametrize("failure", ["timeout", "network"])
async def test_failed_graceful_close_is_bounded_and_reported(wire, failure):
    _, proto, transport, _ = wire
    session, _, disconnected = await start_session(wire)
    with patch.object(protocol, "CLOSE_TIMEOUT", 0.01):
        session.close(flush=True)
        if failure == "network":
            proto.connection_lost(ConnectionResetError())
        result = await session.wait_closed()
    assert result["delivery_failed"]
    assert result["error"] == "delivery_failed"
    assert not proto.on_con_lost.cancelled()
    assert transport.abort.call_count == (failure == "timeout")
    disconnected.assert_called_once()


async def test_tv_close_drops_buffer_releases_session_and_unload_waits(wire):
    _, proto, transport, frames = wire
    session, released, disconnected = await start_session(wire)
    session.feed(bytes(100))
    frames.clear()
    server_close(proto)
    assert session.closed and session.error == "session_ended"
    assert not session.buffer and not frames
    released.assert_called_once()
    disconnected.assert_not_called()
    unload = asyncio.create_task(session.shutdown())
    await asyncio.sleep(0)
    assert not unload.done()
    proto.connection_lost(None)
    await unload
    disconnected.assert_called_once()
    transport.abort.assert_not_called()


async def test_cancelled_waiter_does_not_cancel_owned_shutdown(wire):
    _, proto, _, _ = wire
    session, _, disconnected = await start_session(wire)
    session.close()
    waiter = asyncio.create_task(session.wait_closed())
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not proto.on_con_lost.cancelled()
    proto.connection_lost(None)
    await session.shutdown()
    disconnected.assert_called_once()
