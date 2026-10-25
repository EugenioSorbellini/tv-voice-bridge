"""Client wire format, checked against upstream's schema, and transport lifecycles."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.tv_voice_bridge import client as client_module
from custom_components.tv_voice_bridge.client import TvVoiceClient, VoiceStream
from custom_components.tv_voice_bridge.errors import VoiceError
from custom_components.tv_voice_bridge.session import VoiceSession
from tests.upstream_schema_pb2 import RemoteMessage, Varint

# androidtvremote2 0.3.2 values, fixed here so library updates cannot change them.
KEYCODE_SEARCH = 84
DIRECTION_SHORT = 3
PING, KEY, IME, VOICE, POWER, VOLUME, APP_LINK = 1, 2, 4, 8, 32, 64, 512
UPSTREAM_FEATURES = PING | KEY | IME | VOICE | POWER | VOLUME | APP_LINK


def varint(value):
    """Independent varint encoding, through protobuf's public API."""
    return Varint(value=value & (1 << 64) - 1).SerializeToString()[1:] or b"\x00"


def read_varint(data, offset=0):
    end = offset
    while data[end] & 0x80:
        end += 1
    return Varint.FromString(b"\x08" + data[offset : end + 1]).value, end + 1


@pytest.fixture
async def wire():
    """Build connected clients: wire(on_voice_close) -> (client, transport, frames)."""
    loop = asyncio.get_running_loop()
    clients = []

    def connect(on_voice_close=lambda: None):
        client = TvVoiceClient(
            "tv.invalid", "unused.pem", "unused.key", loop, on_voice_close=on_voice_close
        )
        frames = []
        transport = Mock()
        transport.write.side_effect = frames.append
        transport.is_closing.return_value = False
        transport.close.side_effect = lambda: setattr(transport.is_closing, "return_value", True)
        client.connection_made(transport)
        clients.append(client)
        return client, transport, frames

    yield connect
    for client in clients:
        client.connection_lost(None)


def messages(frames):
    # Independent decoder: protobuf's own varint reader, not the client's.
    wire = b"".join(frames)
    result = []
    while wire:
        size, offset = read_varint(wire)
        result.append(wire[offset : offset + size])
        wire = wire[offset + size :]
    return result


def receive(client, message):
    raw = message if isinstance(message, bytes) else message.SerializeToString()
    client.data_received(client_module.encode_varint(len(raw)) + raw)


def handshake(client, features=0b1101111):
    configure = RemoteMessage()
    configure.remote_configure.code1 = features
    configure.remote_configure.device_info.model = "Model"
    configure.remote_configure.device_info.vendor = "Vendor"
    configure.remote_configure.device_info.app_version = "7.00"
    active = RemoteMessage()
    active.remote_set_active.active = 1
    start = RemoteMessage()
    start.remote_start.started = True
    receive(client, configure)
    receive(client, active)
    receive(client, start)


def server_begin(session_id=7):
    message = RemoteMessage()
    message.remote_voice_begin.session_id = session_id
    message.remote_voice_begin.package_name = "com.google.android.katniss"
    return message


def server_close(session_id=7):
    # TV-to-client field 31 is a session-close request. Upstream's schema
    # calls it a payload, which is enough to encode the close for this test.
    message = RemoteMessage()
    message.remote_voice_payload.session_id = session_id
    return message


async def open_voice(client, frames, session_id=7):
    handshake(client)
    task = asyncio.create_task(client.start_voice())
    await asyncio.sleep(0)
    receive(client, server_begin(session_id))
    stream = await task
    frames.clear()
    return stream


async def test_handshake_matches_upstream_replies(wire):
    client, _, frames = wire()
    handshake(client)
    configure, active = (RemoteMessage.FromString(raw) for raw in messages(frames))
    assert configure.remote_configure.code1 == UPSTREAM_FEATURES & 0b1101111
    info = configure.remote_configure.device_info
    assert (info.unknown1, info.unknown2, info.package_name, info.app_version) == (
        1,
        "1",
        "atvremote",
        "1.0.0",
    )
    assert active.remote_set_active.active == UPSTREAM_FEATURES & 0b1101111
    assert client.is_voice_enabled


async def test_voice_disabled_when_tv_lacks_the_feature(wire):
    client, _, _ = wire()
    handshake(client, features=PING | KEY)
    assert not client.is_voice_enabled


async def test_ping_reply_and_split_frames(wire):
    client, _, frames = wire()
    ping = RemoteMessage()
    ping.remote_ping_request.val1 = 300
    ping.remote_ping_request.val2 = 9
    raw = ping.SerializeToString()
    data = client_module.encode_varint(len(raw)) + raw
    for byte in data:
        client.data_received(bytes([byte]))  # Any split, including inside the length.
    assert RemoteMessage.FromString(messages(frames)[0]).remote_ping_response.val1 == 300


@pytest.mark.parametrize("session_id", [0, 7, 128, 2147483647, -1, -2147483648])
async def test_voice_messages_preserve_audio_and_signed_session(wire, session_id):
    client, _, frames = wire()
    handshake(client)
    frames.clear()
    task = asyncio.create_task(client.start_voice())
    await asyncio.sleep(0)
    key = RemoteMessage.FromString(messages(frames)[0]).remote_key_inject
    assert (key.key_code, key.direction) == (KEYCODE_SEARCH, DIRECTION_SHORT)
    frames.clear()
    receive(client, server_begin(session_id))
    stream = await task
    assert stream.session_id == session_id
    # Hand-built expected bytes: begin with 16 kHz, mono mask 16, PCM16 format 2.
    # int32 negatives are ten-byte two's complement varints.
    begin = b"\x08" + varint(session_id) + b"\x50\x80\x7d\x58\x10\x60\x02"
    assert messages(frames) == [b"\xf2\x01" + client_module.encode_varint(len(begin)) + begin]
    frames.clear()
    audio = b"\x00\x80\xff\x7f" * 2048
    assert stream.send_chunk(audio)
    # Field 31's contents are the PCM itself, not upstream's nested message.
    assert messages(frames) == [b"\xfa\x01\x80\x40" + audio]
    frames.clear()
    stream.end()
    assert RemoteMessage.FromString(messages(frames)[0]).remote_voice_end.session_id == (session_id)


async def test_server_close_is_matched_once_and_stops_audio(wire):
    closed = Mock()
    client, _, frames = wire(closed)
    stream = await open_voice(client, frames)
    receive(client, server_close(8))
    missing = RemoteMessage()
    missing.remote_voice_payload.SetInParent()
    receive(client, missing)
    closed.assert_not_called()
    receive(client, server_close())
    receive(client, server_close())
    closed.assert_called_once_with()
    assert not stream.send_chunk(bytes(8192))
    stream.end()
    assert not frames  # No tail, duplicate end, or payload after TV close.


async def test_close_in_same_read_as_offer_cannot_open_voice(wire):
    closed = Mock()
    client, _, frames = wire(closed)
    handshake(client)
    task = asyncio.create_task(client.start_voice())
    await asyncio.sleep(0)
    frames.clear()
    offer, close = server_begin().SerializeToString(), server_close().SerializeToString()
    encode = client_module.encode_varint
    client.data_received(encode(len(offer)) + offer + encode(len(close)) + close)
    with pytest.raises(VoiceError, match="session_ended"):
        await task
    closed.assert_called_once_with()
    assert not frames


async def test_unsolicited_offer_is_ignored(wire):
    client, _, frames = wire()
    handshake(client)
    frames.clear()
    receive(client, server_begin())
    assert client.session_id is None
    assert not frames


async def test_start_voice_times_out_and_fails_on_lost_connection(wire):
    client, _, _ = wire()
    handshake(client)
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await client.start_voice()
    task = asyncio.create_task(client.start_voice())
    await asyncio.sleep(0)
    client.connection_lost(ConnectionResetError())
    with pytest.raises(VoiceError, match="unavailable"):
        await task


@pytest.mark.parametrize("raw", [b"\xfa\x01\x02\x08", b"\x0a\x01\xff", b"\x0f"])
async def test_malformed_message_is_ignored_without_exposing_payload(wire, raw, caplog):
    caplog.set_level("DEBUG")
    closed = Mock()
    client, transport, _ = wire(closed)
    receive(client, raw)
    closed.assert_not_called()
    transport.abort.assert_not_called()
    assert raw.hex() not in caplog.text


async def test_corrupt_length_aborts_the_connection(wire):
    client, transport, _ = wire()
    client.data_received(b"\xff" * 11)
    transport.abort.assert_called_once()


async def test_echoed_audio_and_session_ids_never_reach_logs(wire, caplog):
    client, _, frames = wire()
    caplog.set_level("DEBUG")
    stream = await open_voice(client, frames, 999271)
    stream.send_chunk(b"PRIVATE_AUDIO" * 1024)
    error = RemoteMessage()
    error.remote_error.message.remote_voice_payload.samples = b"PRIVATE_AUDIO"
    receive(client, error)
    receive(client, server_close(999271))
    assert "TV reported a remote protocol error" in caplog.text
    assert "PRIVATE_AUDIO" not in caplog.text
    assert "999271" not in caplog.text


async def test_idle_connection_is_closed(wire):
    client, transport, _ = wire()
    with patch.object(client_module, "IDLE_TIMEOUT", 0.01):
        client.data_received(b"")  # Rearm with the patched timeout.
        await asyncio.sleep(0.05)
    transport.close.assert_called_once()


async def test_connect_waits_for_remote_start_and_reports_early_close():
    loop = asyncio.get_running_loop()
    client = TvVoiceClient("tv.invalid", "cert", "key", loop)
    transport = Mock(is_closing=Mock(return_value=False))

    async def create_connection(factory, host, port, ssl):
        assert (host, port, ssl) == ("tv.invalid", 6466, "context")
        factory().connection_made(transport)
        return transport, client

    with (
        patch.object(client_module, "load_ssl_context", return_value="context") as load,
        patch.object(loop, "create_connection", side_effect=create_connection),
    ):
        task = asyncio.create_task(client.async_connect())
        await asyncio.sleep(0.01)
        assert not task.done()
        handshake(client)
        await task
        load.assert_called_once_with("cert", "key")
        client.connection_lost(None)
        failed = TvVoiceClient("tv.invalid", "cert", "key", loop)
        task = asyncio.create_task(failed.async_connect())
        await asyncio.sleep(0.01)
        failed.connection_lost(ConnectionResetError())
        with pytest.raises(VoiceError, match="unavailable"):
            await task


async def start_session(wire):
    """Run a real VoiceSession whose factory builds the client, as the manager does."""
    opened = []

    def open_client(on_voice_close):
        client, transport, frames = wire(on_voice_close)
        handshake(client)
        client.async_connect = AsyncMock()
        real_start = client.start_voice

        async def start_voice():
            task = asyncio.create_task(real_start())
            await asyncio.sleep(0)
            receive(client, server_begin())
            return await task

        client.start_voice = start_voice
        opened.append((client, transport, frames))
        return client

    released, disconnected = Mock(), Mock()
    session = VoiceSession(open_client, released, on_disconnect=disconnected)
    with patch("custom_components.tv_voice_bridge.session.VOICE_READY_DELAY", 0):
        await session.start()
    client, transport, frames = opened[0]
    frames.clear()
    return session, released, disconnected, client, transport, frames


async def test_submission_waits_for_real_close_and_preserves_queued_tail(wire):
    session, released, disconnected, client, transport, frames = await start_session(wire)
    session.feed(b"\x01\x02" * 50)
    session.close(flush=True)
    transport.close.assert_called_once()
    released.assert_called_once()
    disconnected.assert_not_called()
    sent = [RemoteMessage.FromString(raw) for raw in messages(frames)[1:]]
    assert messages(frames)[0] == b"\xfa\x01\x64" + b"\x01\x02" * 50
    assert sent[-1].HasField("remote_voice_end")
    waiter = asyncio.create_task(session.wait_closed())
    await asyncio.sleep(0)
    assert not waiter.done()
    client.connection_lost(None)
    result = await waiter
    assert result["forwarded_bytes"] == 100
    assert not result["delivery_failed"]
    disconnected.assert_called_once()
    transport.abort.assert_not_called()


@pytest.mark.parametrize("failure", ["timeout", "network"])
async def test_failed_graceful_close_is_bounded_and_reported(wire, failure):
    session, _, disconnected, client, transport, _ = await start_session(wire)
    with patch.object(client_module, "CLOSE_TIMEOUT", 0.01):
        session.close(flush=True)
        if failure == "network":
            client.connection_lost(ConnectionResetError())
        result = await session.wait_closed()
    assert result["delivery_failed"]
    assert result["error"] == "delivery_failed"
    assert not client.closed.cancelled()
    assert transport.abort.call_count == (failure == "timeout")
    disconnected.assert_called_once()


async def test_tv_close_drops_buffer_releases_session_and_unload_waits(wire):
    session, released, disconnected, client, transport, frames = await start_session(wire)
    session.feed(bytes(100))
    receive(client, server_close())
    assert session.closed and session.error == "session_ended"
    assert not session.buffer and not frames
    released.assert_called_once()
    disconnected.assert_not_called()
    unload = asyncio.create_task(session.shutdown())
    await asyncio.sleep(0)
    assert not unload.done()
    client.connection_lost(None)
    await unload
    disconnected.assert_called_once()
    transport.abort.assert_not_called()


async def test_cancelled_waiter_does_not_cancel_owned_shutdown(wire):
    session, _, disconnected, client, _, _ = await start_session(wire)
    session.close()
    waiter = asyncio.create_task(session.wait_closed())
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not client.closed.cancelled()
    client.connection_lost(None)
    await session.shutdown()
    disconnected.assert_called_once()


def test_stream_end_is_sent_once():
    client = Mock(voice_closed_by_tv=False)
    stream = VoiceStream(client, 7)
    stream.end()
    stream.end()
    client.send.assert_called_once()
    assert not stream.send_chunk(bytes(2))


async def test_closed_connection_releases_the_owner_callback(wire):
    closed = Mock()
    client, _, frames = wire(closed)
    await open_voice(client, frames)
    client.connection_lost(None)
    receive(client, server_close())  # A late close reaches nobody.
    closed.assert_not_called()


async def test_tv_close_after_our_end_is_still_reported(wire):
    closed = Mock()
    client, _, frames = wire(closed)
    stream = await open_voice(client, frames)
    stream.end()
    receive(client, server_close())
    closed.assert_called_once_with()
    assert client.voice_closed_by_tv
