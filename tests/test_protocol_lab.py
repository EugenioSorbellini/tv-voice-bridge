"""Offline lab checks; no device, HA server, or microphone is contacted."""

import asyncio
import contextlib
import io
import json
import logging
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch
import wave

from androidtvremote2.remote import RemoteProtocol
from androidtvremote2.remotemessage_pb2 import RemoteMessage
from androidtvremote2.voice_stream import VoiceStream
from google.protobuf.internal.decoder import _DecodeVarint

from tools import protocol_lab as lab


class ProtocolLabTests(unittest.IsolatedAsyncioTestCase):
    def test_server_close_observation_omits_session_and_audio(self):
        protocol = types.SimpleNamespace(_handle_message=Mock())
        events = []
        lab.observe_messages(
            types.SimpleNamespace(_remote_message_protocol=protocol), events, time.monotonic()
        )
        begin = RemoteMessage()
        begin.remote_voice_begin.session_id = 999271
        protocol._handle_message(begin.SerializeToString())
        closed = RemoteMessage()
        closed.remote_voice_payload.session_id = 999271
        protocol._handle_message(closed.SerializeToString())
        self.assertEqual(events[-1]["event"], "server_field_31")
        self.assertTrue(events[-1]["session_matches"])
        self.assertFalse(events[-1]["has_samples"])
        closed.remote_voice_payload.samples = b"PRIVATE_AUDIO"
        protocol._handle_message(closed.SerializeToString())
        self.assertTrue(events[-1]["has_samples"])
        self.assertNotIn("PRIVATE", json.dumps(events))
        self.assertNotIn("999271", json.dumps(events))

    def test_default_is_offline(self):
        with (
            patch.object(lab, "run_case", side_effect=AssertionError("Live execution attempted")),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(lab.main([]), 0)
        self.assertEqual(json.loads(output.getvalue())["mode"], "offline_plan")

    def test_live_requires_a_fixture(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            lab.main(["--execute"])

    def test_fixture_rate_duration_and_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.wav"
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(bytes(32000))
            self.assertEqual(len(lab.read_audio(path, 16000)), 32000)
            with self.assertRaises(ValueError):
                lab.read_audio(path, 8000)
            path.write_bytes(path.read_bytes()[:-2])
            with self.assertRaises(ValueError):
                lab.read_audio(path, 16000)

    async def test_case_packets_preserve_selected_format(self):
        for case in lab.CASES.values():
            with self.subTest(case=case.name):
                loop = asyncio.get_running_loop()
                frames = []
                protocol = RemoteProtocol(
                    loop.create_future(),
                    loop.create_future(),
                    lambda *_: None,
                    lambda *_: None,
                    lambda *_: None,
                    loop,
                    True,
                    True,
                )
                protocol.transport = types.SimpleNamespace(
                    write=frames.append, is_closing=lambda: False, close=lambda: None
                )
                try:
                    remote = types.SimpleNamespace(_remote_message_protocol=protocol)
                    lab.install_case(remote, case)
                    report = {}
                    lab.observe_payload_shape(remote, report)
                    begin = RemoteMessage()
                    begin.remote_voice_begin.session_id = 7
                    protocol._send_message(begin)
                    wire = b"".join(frames)
                    _, start = _DecodeVarint(wire, 0)
                    if case.configured_begin:
                        config = b"\x50" + lab.varint(case.rate) + b"\x58\x10\x60\x02"
                        self.assertIn(config, wire[start:])
                    else:
                        self.assertEqual(wire[start:], begin.SerializeToString())
                    frames.clear()
                    audio = b"\x00\x80\xff\x7f" * 2048
                    VoiceStream(protocol, 7).send_chunk(audio)
                    self.assertEqual(report, {"upstream_payload_wrapper_bytes": [5]})
                    wire = b"".join(frames)
                    _, start = _DecodeVarint(wire, 0)
                    if case.payload == "raw":
                        tag, start = _DecodeVarint(wire, start)
                        self.assertEqual(tag, (31 << 3) | 2)
                        size, start = _DecodeVarint(wire, start)
                        self.assertEqual(wire[start : start + size], audio)
                    else:
                        message = RemoteMessage.FromString(wire[start:])
                        self.assertEqual(message.remote_voice_payload.session_id, 7)
                        self.assertEqual(message.remote_voice_payload.samples, audio)
                finally:
                    protocol.close()

    async def test_failure_cleanup_and_metadata_privacy(self):
        for phase in ("connect", "audio"):
            with self.subTest(phase=phase):
                args = types.SimpleNamespace(
                    host="PRIVATE_HOST",
                    cert=Path("PRIVATE_CERT"),
                    key=Path("PRIVATE_KEY"),
                    ready_delay=0,
                    processing_grace=0,
                    pace="burst",
                )
                stream = Mock(send_chunk=Mock(side_effect=RuntimeError("PRIVATE_AUDIO")))
                remote = Mock(
                    async_connect=AsyncMock(
                        side_effect=RuntimeError("PRIVATE_HOST") if phase == "connect" else None
                    ),
                    start_voice=AsyncMock(return_value=stream),
                    device_info={"manufacturer": "Synthetic"},
                )
                disabled = logging.getLogger("androidtvremote2").disabled
                with (
                    patch("androidtvremote2.AndroidTVRemote", return_value=remote),
                    patch.object(lab, "install_case"),
                    patch.object(lab, "observe_messages"),
                ):
                    report = await lab.run_case(args, lab.CASES["current"], bytes(8192))
                remote.disconnect.assert_called_once()
                if phase == "audio":
                    stream.end.assert_called_once()
                self.assertEqual(report["recognition"], "not_observed")
                self.assertEqual(report["outcome"], "transport_failed")
                self.assertNotIn("PRIVATE", json.dumps(report))
                self.assertEqual(logging.getLogger("androidtvremote2").disabled, disabled)

    async def test_app_callback_removed_on_connection_failure(self):
        args = types.SimpleNamespace(
            host="PRIVATE_HOST",
            cert=Path("PRIVATE_CERT"),
            key=Path("PRIVATE_KEY"),
            ready_delay=0,
            processing_grace=0,
            startup="ime",
            pace="burst",
        )
        remote = Mock(async_connect=AsyncMock(side_effect=RuntimeError("PRIVATE_ERROR")))
        disabled = logging.getLogger("androidtvremote2").disabled
        with patch("androidtvremote2.AndroidTVRemote", return_value=remote):
            report = await lab.run_case(args, lab.CASES["current"], bytes(8192))
        callback = remote.add_current_app_updated_callback.call_args.args[0]
        remote.remove_current_app_updated_callback.assert_called_once_with(callback)
        remote.disconnect.assert_called_once()
        self.assertNotIn("PRIVATE", json.dumps(report))
        self.assertEqual(logging.getLogger("androidtvremote2").disabled, disabled)

    async def test_experimental_startup_waits_for_callback_without_fixed_sleep(self):
        args = types.SimpleNamespace(
            host="PRIVATE_HOST",
            cert=Path("PRIVATE_CERT"),
            key=Path("PRIVATE_KEY"),
            ready_delay=1,
            audio_delay=0,
            processing_grace=0,
            startup="ime",
            pace="burst",
        )
        stream = Mock(send_chunk=Mock(return_value=True))
        remote = Mock(
            start_voice=AsyncMock(return_value=stream),
            device_info={"manufacturer": "Synthetic"},
        )
        remote._remote_message_protocol.transport.get_write_buffer_size.return_value = 0

        async def connect():
            callback = remote.add_current_app_updated_callback.call_args.args[0]
            callback("PRIVATE_APP")

        remote.async_connect = AsyncMock(side_effect=connect)
        with (
            patch("androidtvremote2.AndroidTVRemote", return_value=remote),
            patch.object(lab, "install_case"),
            patch.object(lab, "observe_messages"),
            patch.object(lab, "observe_payload_shape"),
            patch.object(lab.asyncio, "sleep", new_callable=AsyncMock) as sleep,
        ):
            report = await lab.run_case(args, lab.CASES["current"], bytes(8192))
        self.assertEqual(report["outcome"], "transport_completed")
        self.assertEqual(report["events"][0]["event"], "initial_app_report")
        self.assertTrue(all(call.args == (0,) for call in sleep.await_args_list))
        remote.remove_current_app_updated_callback.assert_called_once()
        remote.disconnect.assert_called_once()
        self.assertNotIn("PRIVATE", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
