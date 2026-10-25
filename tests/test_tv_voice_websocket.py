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
async def test_connection_isolation_busy_and_malformed_frames(hass_ws_client, bridge):
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


@pytest.mark.asyncio
async def test_permission_checked_on_binary_and_stop(hass_ws_client, bridge):
    manager, entity, _ = bridge
    client = await hass_ws_client()
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
async def test_cancel_pending_start_and_disconnect(hass_ws_client, bridge):
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
