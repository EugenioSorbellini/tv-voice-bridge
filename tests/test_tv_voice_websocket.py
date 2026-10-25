"""Actual HA WebSocket auth/schema/binary routing and privacy regression tests."""

import asyncio
from datetime import timedelta
import logging
from unittest.mock import AsyncMock, Mock, patch
import weakref

from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.tv_voice_bridge.const import DOMAIN
from custom_components.tv_voice_bridge.manager import BridgeManager
from custom_components.tv_voice_bridge.websocket import async_register


@pytest.fixture
async def bridge(hass):
    source = MockConfigEntry(
        domain="androidtv_remote", data={"host": "tv.invalid"}, entry_id="source-tv"
    )
    source.add_to_hass(hass)
    entity = er.async_get(hass).async_get_or_create(
        "remote", "androidtv_remote", "tv-1", suggested_object_id="test_tv", config_entry=source
    )
    hass.states.async_set(entity.entity_id, "on", {"friendly_name": "Test TV"})
    manager = BridgeManager(hass)
    manager.targets["bridge-entry"] = (entity.entity_id, source.entry_id)
    hass.data[DOMAIN] = manager
    assert await async_setup_component(hass, "websocket_api", {})
    async_register(hass)
    remotes = []

    def make_remote(*args, **kwargs):
        remote = Mock()
        remote.disconnect.return_value = False  # No transport to wait for.
        remote.is_voice_enabled = True
        remote.async_connect = AsyncMock()
        remote.start_voice = AsyncMock(return_value=Mock(send_chunk=Mock(return_value=True)))
        remotes.append(remote)
        return remote

    with (
        # A plain function, unlike a Mock, does not retain the session's callback.
        patch("custom_components.tv_voice_bridge.manager.TvVoiceClient", new=make_remote),
        patch("custom_components.tv_voice_bridge.session.VOICE_READY_DELAY", 0),
    ):
        yield manager, entity.entity_id, remotes
        await manager.unload()


async def call(client, **message):
    await client.send_json_auto_id(message)
    return await client.receive_json()


def frame(result, audio, sequence=0, token=None):
    return (
        bytes([result["binary_handler_id"]])
        + bytes.fromhex(token or result["session_id"])
        + sequence.to_bytes(4, "little")
        + audio
    )


@pytest.mark.asyncio
async def test_binary_delivery_and_no_audio_in_json_debug_logs(hass_ws_client, bridge, caplog):
    """Start, binary frame, progress and stop through HA's real WebSocket API.

    With debug logging on, starts a session, sends 8192 bytes of PCM as one binary frame,
    acknowledges it with progress and submits with stop.

    Verifies: progress reports all bytes received; stop forwards exactly those bytes to
    the TV in one chunk; the audio never appears in the logs, raw or base64, although HA
    logged the JSON commands; no session record remains.
    """
    caplog.set_level(logging.DEBUG)
    manager, entity, remotes = bridge
    client = await hass_ws_client()
    response = await call(client, type=DOMAIN + "/start", request_id="1" * 32, remote_entity=entity)
    assert response["success"]
    session = response["result"]
    pcm = b"\x23\x18" * 4096
    await client.send_bytes(frame(session, pcm))
    result = await call(
        client, type=DOMAIN + "/progress", session_id=session["session_id"], sequence=1
    )
    assert result["result"]["received_bytes"] == len(pcm)
    result = await call(
        client, type=DOMAIN + "/stop", session_id=session["session_id"], expected_bytes=len(pcm)
    )
    assert result["result"]["forwarded_bytes"] == len(pcm)
    remotes[0].start_voice.return_value.send_chunk.assert_called_once_with(pcm)
    import base64

    assert base64.b64encode(pcm).decode() not in caplog.text
    assert str(pcm) not in caplog.text
    assert "Received" in caplog.text  # Prove debug logging was enabled.
    assert not manager.records
    await client.close()


@pytest.mark.asyncio
async def test_connection_isolation_busy_and_out_of_order_frame(hass_ws_client, bridge):
    """Sessions are per connection, the TV is reserved, and an out-of-order frame ends the session.

    Starts a session on one connection; from a second connection, tries to cancel it with
    stop and to start another session; then sends a frame with sequence 3 where 0 was
    expected.

    Verifies: the other connection's stop fails and its start returns busy; the
    out-of-order frame ends the session, so the next progress fails, no record remains
    and the TV client is disconnected.
    """
    manager, entity, remotes = bridge
    client = await hass_ws_client()
    other = await hass_ws_client()
    response = await call(client, type=DOMAIN + "/start", request_id="2" * 32)
    session = response["result"]
    assert not (
        await call(other, type=DOMAIN + "/stop", session_id=session["session_id"], cancel=True)
    )["success"]
    assert (await call(other, type=DOMAIN + "/start", request_id="3" * 32))["error"][
        "code"
    ] == "busy"
    await client.send_bytes(frame(session, bytes(100), sequence=3))
    response = await call(
        client, type=DOMAIN + "/progress", session_id=session["session_id"], sequence=1
    )
    assert not response["success"]
    assert not manager.records
    remotes[0].disconnect.assert_called()
    await client.close()
    await other.close()


@pytest.mark.parametrize(
    "malformed",
    ["header_only", "oversized", "odd_length", "wrong_token"],
)
async def test_malformed_frames_end_the_session(hass_ws_client, bridge, malformed):
    """Binary frames that break the frame format end the session without feeding audio.

    Starts a session and sends one malformed frame (parametrized): a header with no
    audio, 16386 bytes of audio (over the 16384-byte limit), three bytes of audio (odd
    length), or a frame signed with another session's token.

    Verifies: progress then returns invalid_audio; no audio was accepted; no record
    remains and the TV client is disconnected.
    """
    manager, _, remotes = bridge
    client = await hass_ws_client()
    session = (await call(client, type=DOMAIN + "/start", request_id="e" * 32))["result"]
    record = manager.records[session["session_id"]]
    payload = {
        "header_only": frame(session, b""),
        "oversized": frame(session, bytes(16386)),
        "odd_length": frame(session, bytes(3)),
        "wrong_token": frame(session, bytes(8192), token="f" * 32),
    }[malformed]
    await client.send_bytes(payload)
    result = await call(
        client, type=DOMAIN + "/progress", session_id=session["session_id"], sequence=1
    )
    assert result["error"]["code"] == "invalid_audio"
    assert record.session.total_bytes == 0
    assert not manager.records
    remotes[0].disconnect.assert_called()
    await client.close()


@pytest.mark.asyncio
async def test_permission_checked_on_binary_stop_and_start(hass_ws_client, bridge):
    """TV-control permission is checked again on audio frames, stop and start.

    Starts a session and sends an audio frame with permission revoked. Starts a second
    session and calls stop with permission revoked, then tries to start a third.

    Verifies: the frame is not accepted and ends the session with unauthorized, which
    progress then reports; stop returns unauthorized and removes its session; start
    returns unauthorized.
    """
    manager, entity, _ = bridge
    client = await hass_ws_client()
    session = (await call(client, type=DOMAIN + "/start", request_id="3" * 32))["result"]
    record = manager.records[session["session_id"]]
    with patch.object(BridgeManager, "allowed", return_value=False):
        await client.send_bytes(frame(session, bytes(8192)))
        # Frames and commands keep WebSocket order, so this reply follows the frame.
        await call(client, type=DOMAIN + "/progress", session_id=session["session_id"], sequence=1)
    assert record.session.total_bytes == 0
    assert not manager.records
    # With permission back, the retained error shows the frame itself was refused.
    response = await call(
        client, type=DOMAIN + "/progress", session_id=session["session_id"], sequence=1
    )
    assert response["error"]["code"] == "unauthorized"
    response = await call(client, type=DOMAIN + "/start", request_id="4" * 32)
    session = response["result"]
    with patch.object(BridgeManager, "allowed", return_value=False):
        response = await call(
            client, type=DOMAIN + "/stop", session_id=session["session_id"], expected_bytes=0
        )
    assert response["error"]["code"] == "unauthorized"
    assert not manager.records
    with patch.object(BridgeManager, "allowed", return_value=False):
        response = await call(client, type=DOMAIN + "/start", request_id="5" * 32)
        assert response["error"]["code"] == "unauthorized"
    await client.close()


@pytest.mark.asyncio
async def test_start_reports_voice_unsupported_and_connect_timeout(hass_ws_client, bridge):
    """Start failures reach the client as stable codes and free the TV.

    Starts once against a TV whose handshake left voice disabled, then once with the
    connect limit shortened to 10 ms and a connect that hangs, then once normally.

    Verifies: the first start returns voice_unsupported and the second unavailable;
    neither leaves a record or session behind; the third start succeeds, so the TV
    isn't left reserved.
    """
    manager, _, remotes = bridge
    client = await hass_ws_client()
    with patch("custom_components.tv_voice_bridge.manager.TvVoiceClient") as factory:
        factory.return_value = Mock(
            is_voice_enabled=False, async_connect=AsyncMock(), disconnect=Mock(return_value=False)
        )
        response = await call(client, type=DOMAIN + "/start", request_id="1" * 32)
        assert response["error"]["code"] == "voice_unsupported"
        factory.return_value = Mock(
            async_connect=asyncio.Event().wait, disconnect=Mock(return_value=False)
        )
        with patch("custom_components.tv_voice_bridge.session.CONNECT_TIMEOUT", 0.01):
            response = await call(client, type=DOMAIN + "/start", request_id="2" * 32)
        assert response["error"]["code"] == "unavailable"
    assert not manager.records and not manager.sessions
    assert (await call(client, type=DOMAIN + "/start", request_id="3" * 32))["success"]
    await client.close()


@pytest.mark.asyncio
async def test_start_without_entity_needs_a_single_tv(hass_ws_client, bridge):
    """Start may omit remote_entity only when exactly one TV is configured.

    Adds a second paired TV to the bridge, then starts without remote_entity and again
    with the second TV's entity.

    Verifies: the first start returns select_target; naming the entity starts a session
    on that TV.
    """
    manager, _, _ = bridge
    source = MockConfigEntry(
        domain="androidtv_remote", data={"host": "tv2.invalid"}, entry_id="source-tv-2"
    )
    source.add_to_hass(manager.hass)
    entity = er.async_get(manager.hass).async_get_or_create(
        "remote", "androidtv_remote", "tv-2", suggested_object_id="second_tv", config_entry=source
    )
    manager.targets["bridge-entry-2"] = (entity.entity_id, source.entry_id)
    client = await hass_ws_client()
    response = await call(client, type=DOMAIN + "/start", request_id="1" * 32)
    assert response["error"]["code"] == "select_target"
    response = await call(
        client, type=DOMAIN + "/start", request_id="2" * 32, remote_entity=entity.entity_id
    )
    assert response["success"]
    record = manager.records[response["result"]["session_id"]]
    assert record.target.entity_id == entity.entity_id
    await client.close()


@pytest.mark.asyncio
async def test_cancel_pending_start_and_disconnect(hass_ws_client, bridge):
    """Cancel works while start is still connecting, and disconnect cleans up.

    Makes the TV connect hang, sends start, waits until connect is in progress and sends
    cancel; then starts a new session and closes the WebSocket.

    Verifies: the pending start fails with cancelled, no record remains and the client
    is disconnected; a new start then succeeds; closing the WebSocket removes that
    session.
    """
    manager, entity, remotes = bridge
    client = await hass_ws_client()
    waiting = asyncio.Event()

    async def connect():
        waiting.set()
        await asyncio.Future()

    with patch("custom_components.tv_voice_bridge.manager.TvVoiceClient") as factory:
        remote = Mock(async_connect=connect, disconnect=Mock(return_value=False))
        factory.return_value = remote
        await client.send_json_auto_id({"type": DOMAIN + "/start", "request_id": "6" * 32})
        await waiting.wait()
        await client.send_json_auto_id({"type": DOMAIN + "/cancel", "request_id": "6" * 32})
        replies = [await client.receive_json(), await client.receive_json()]
        assert any(reply.get("error", {}).get("code") == "cancelled" for reply in replies)
        assert not manager.records
        remote.disconnect.assert_called()
    response = await call(client, type=DOMAIN + "/start", request_id="7" * 32)
    assert response["success"]
    await client.close()
    await manager.hass.async_block_till_done()
    assert not manager.records


@pytest.mark.asyncio
async def test_real_schemas_reject_invalid_tokens_and_json_audio(hass_ws_client, bridge):
    """HA's command schemas reject a bad request id and JSON audio; list returns the TV.

    Sends start with request_id "bad", a JSON audio command, and list.

    Verifies: start fails with invalid_format, the audio command with unknown_command,
    and list returns the configured TV by name.
    """
    client = await hass_ws_client()
    response = await call(client, type=DOMAIN + "/start", request_id="bad")
    assert response["error"]["code"] == "invalid_format"
    response = await call(
        client, type=DOMAIN + "/audio", session_id="0" * 32, audio="not-supported"
    )
    assert response["error"]["code"] == "unknown_command"
    response = await call(client, type=DOMAIN + "/list")
    assert response["result"][0]["name"] == "Test TV"
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code", ["invalid_audio", "delivery_failed", "recording_limit", "session_timeout"]
)
async def test_terminal_errors_survive_cleanup_and_remain_owned(hass_ws_client, bridge, code):
    """A failed session's error stays with its connection without holding resources.

    Parametrized over four failures: invalid_audio (out-of-order frame), delivery_failed
    (the TV rejects the chunk forwarded at stop), recording_limit (a frame past 480000
    bytes) and session_timeout. Then calls progress and stop from the owning connection
    and from another one.

    Verifies: the owner gets the original code from both, the other connection gets
    session_ended; no record, held audio or binary handler remains, and the TV client is
    disconnected; the retained error still honours revoked permission (unauthorized); the
    session object is garbage-collected; a new start succeeds, so the TV isn't reserved;
    closing the WebSocket removes the retained error.
    """
    manager, _, remotes = bridge
    client = await hass_ws_client()
    other = await hass_ws_client()
    response = await call(client, type=DOMAIN + "/start", request_id="8" * 32)
    session = response["result"]
    token = session["session_id"]
    record = manager.records[token]
    if code == "session_timeout":
        record.session._expire()
    else:
        if code == "delivery_failed":
            # Audio is held until submission, so forwarding fails at stop.
            remotes[0].start_voice.return_value.send_chunk.return_value = False
            await client.send_bytes(frame(session, bytes(8192)))
            result = await call(
                client, type=DOMAIN + "/stop", session_id=token, expected_bytes=8192
            )
            assert result["result"]["delivery_failed"]
            assert result["result"]["error"] == "delivery_failed"
        elif code == "recording_limit":
            # Receive the entire valid recording before the overflowing frame.
            for sequence in range(29):
                await client.send_bytes(frame(session, bytes(16384), sequence))
            await client.send_bytes(frame(session, bytes(4864), 29))
            await client.send_bytes(frame(session, bytes(2), 30))
        else:
            await client.send_bytes(
                frame(session, bytes(8192), 3 if code == "invalid_audio" else 0)
            )
    for message in (
        {"type": DOMAIN + "/progress", "session_id": token, "sequence": 1},
        {"type": DOMAIN + "/stop", "session_id": token, "expected_bytes": 8192},
    ):
        assert (await call(client, **message))["error"]["code"] == code
        assert (await call(other, **message))["error"]["code"] == "session_ended"
    assert not manager.records
    assert not record.session.buffer
    remotes[0].disconnect.assert_called()
    assert token in manager.terminal_errors
    assert not any(record.connection.binary_handlers)
    with patch.object(BridgeManager, "allowed", return_value=False):
        result = await call(client, type=DOMAIN + "/progress", session_id=token, sequence=1)
        assert result["error"]["code"] == "unauthorized"
    # Retained errors do not reserve the TV or keep the session alive.
    reference = weakref.ref(record.session)
    del record
    await manager.hass.async_block_till_done()
    import gc

    gc.collect()
    assert reference() is None
    assert (await call(client, type=DOMAIN + "/start", request_id="9" * 32))["success"]
    await client.close()
    await manager.hass.async_block_till_done()
    assert not manager.terminal_errors
    await other.close()


@pytest.mark.asyncio
async def test_terminal_errors_expire_are_bounded_and_unload(hass_ws_client, bridge):
    """Retained errors expire after 30 s, are capped, and are cleared on unload.

    With the cap patched to 2, times out three sessions and advances time by 31 s; then
    times out one more and unloads the entry.

    Verifies: only the newest two errors are kept and the evicted one's timer is
    cancelled; after 31 s none remain and progress returns session_ended; unload clears
    the remaining error and cancels its timer.
    """
    manager, _, _ = bridge
    client = await hass_ws_client()
    tokens = []
    timers = []
    with patch("custom_components.tv_voice_bridge.manager.MAX_TERMINAL_ERRORS", 2):
        for number in range(3):
            response = await call(client, type=DOMAIN + "/start", request_id=f"{number:032x}")
            token = response["result"]["session_id"]
            tokens.append(token)
            manager.records[token].session._expire()
            timers.append(manager.terminal_errors[token].timer)
    assert len(manager.terminal_errors) == 2
    assert tokens[0] not in manager.terminal_errors
    assert timers[0].cancelled()
    async_fire_time_changed(manager.hass, dt_util.utcnow() + timedelta(seconds=31))
    await manager.hass.async_block_till_done()
    assert not manager.terminal_errors
    assert all(timer.cancelled() for timer in timers)
    result = await call(client, type=DOMAIN + "/progress", session_id=tokens[-1], sequence=0)
    assert result["error"]["code"] == "session_ended"
    response = await call(client, type=DOMAIN + "/start", request_id="f" * 32)
    token = response["result"]["session_id"]
    manager.records[token].session._expire()
    timer = manager.terminal_errors[token].timer
    await manager.unload("bridge-entry")
    assert not manager.terminal_errors
    assert timer.cancelled()
    await client.close()


@pytest.mark.parametrize("close_error", [None, ConnectionResetError()])
async def test_stop_waits_for_transport_and_reserves_tv_until_closed(
    hass_ws_client, bridge, close_error
):
    """Stop replies only after the TV connection closes; the TV stays reserved meanwhile.

    Parametrized with a clean close and a connection reset. Sends stop, holds the TV
    connection's close open and tries to start from another connection; then completes
    the close.

    Verifies: while closing, the session record is gone but the session is still owned
    and the other start returns busy; the stop reply reports delivery_failed only for the
    reset; afterwards no session remains and the other connection can start.
    """
    manager, _, remotes = bridge
    client = await hass_ws_client()
    other = await hass_ws_client()
    response = await call(client, type=DOMAIN + "/start", request_id="a" * 32)
    token = response["result"]["session_id"]
    completed = manager.hass.loop.create_future()
    closing = asyncio.Event()
    remote = remotes[0]

    async def wait_closed():
        return await completed is None

    remote.wait_closed = wait_closed

    def disconnect():
        closing.set()
        return True

    remote.disconnect.side_effect = disconnect
    await client.send_json_auto_id(
        {"type": DOMAIN + "/stop", "session_id": token, "expected_bytes": 0}
    )
    await closing.wait()
    assert not manager.records
    assert manager.sessions  # Graceful close is still owned, with no fixed grace timer.
    busy = await call(other, type=DOMAIN + "/start", request_id="b" * 32)
    assert busy["error"]["code"] == "busy"
    completed.set_result(close_error)
    result = await client.receive_json()
    assert result["result"]["delivery_failed"] == (close_error is not None)
    assert result["result"]["error"] == ("delivery_failed" if close_error else None)
    assert not manager.sessions
    assert (await call(other, type=DOMAIN + "/start", request_id="c" * 32))["success"]
    await client.close()
    await other.close()


async def test_tv_voice_close_removes_binary_handler_and_returns_owned_error(
    hass_ws_client, bridge
):
    """A TV close ends the session; both connections then get session_ended.

    Feeds 100 bytes into a session and triggers the TV's close, then calls stop from the
    owner and from another connection.

    Verifies: the record and held audio are removed and the binary handler is
    unregistered; stop returns session_ended on both connections.
    """
    manager, _, _ = bridge
    client = await hass_ws_client()
    other = await hass_ws_client()
    response = await call(client, type=DOMAIN + "/start", request_id="d" * 32)
    token = response["result"]["session_id"]
    record = manager.records[token]
    record.session.feed(bytes(100))
    record.session._tv_closed()
    assert not manager.records and not record.session.buffer
    assert not any(record.connection.binary_handlers)
    result = await call(client, type=DOMAIN + "/stop", session_id=token, expected_bytes=100)
    assert result["error"]["code"] == "session_ended"
    result = await call(other, type=DOMAIN + "/stop", session_id=token, expected_bytes=100)
    assert result["error"]["code"] == "session_ended"
    await client.close()
    await other.close()
