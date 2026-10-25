"""Offline lab checks; no device, HA server, or microphone is contacted."""

import asyncio
import contextlib
import importlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, Mock, call, patch
import wave

from tools import protocol_lab as lab


def bridge(remote):
    """Patch the production client the current case loads."""
    return patch.object(lab, "make_lab_client", return_value=remote)


def frame(message):
    raw = message.SerializeToString()
    return lab.bridge_client().encode_varint(len(raw)) + raw


class ProtocolLabTests(unittest.IsolatedAsyncioTestCase):
    def test_default_is_offline(self):
        with (
            patch.object(lab, "run_trial", side_effect=AssertionError("Live execution attempted")),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(lab.main([]), 0)
        self.assertEqual(json.loads(output.getvalue())["mode"], "offline_plan")

    def test_live_requires_a_fixture(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            lab.main(["--execute"])

    def test_fixture_rate_matches_the_client(self):
        self.assertEqual(lab.RATE, lab.bridge_client().SAMPLE_RATE)

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

    async def test_bridge_trial_observes_the_real_client_without_payloads(self):
        pb2 = importlib.import_module(lab.bridge_client().__package__ + ".voice_pb2")
        recorder = lab.Lab()
        args = types.SimpleNamespace(host="tv.invalid", cert="cert", key="key")
        trial = lab.BridgeTrial(args, recorder)
        trial.remote.connection_made(Mock(is_closing=Mock(return_value=False)))
        configure = pb2.ServerMessage()
        configure.configure.features = 0b1101111
        configure.configure.device_info.vendor = "Vendor"
        app = pb2.ServerMessage()
        app.ime_key_inject.SetInParent()
        offer = pb2.ServerMessage()
        offer.voice_begin.session_id = 999271
        close = pb2.ServerMessage()
        close.voice_close.session_id = 999271
        task = asyncio.create_task(trial.remote.start_voice())
        await asyncio.sleep(0)
        for message in (configure, app, offer, close):
            trial.remote.data_received(frame(message))
        with self.assertRaises(lab.bridge_client().VoiceError):
            await task  # The close arrived before start_voice resumed.
        trial.remote.connection_lost(None)
        names = [event["event"] for event in recorder.events]
        self.assertEqual(names, ["initial_app_report", "remote_voice_begin", "server_field_31"])
        self.assertTrue(recorder.events[-1]["session_matches"])
        self.assertEqual(trial.device_info["manufacturer"], "Vendor")
        self.assertTrue(trial.voice_enabled)
        self.assertNotIn("999271", json.dumps(recorder.events))

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
                )
                with bridge(remote):
                    report = await lab.run_trial(args, bytes(8192))
                remote.disconnect.assert_called_once()
                if phase == "audio":
                    stream.end.assert_called_once()
                self.assertEqual(report["recognition"], "not_observed")
                self.assertEqual(report["outcome"], "transport_failed")
                self.assertNotIn("PRIVATE", json.dumps(report))

    async def test_poll_startup_requests_voice_once_flag_is_enabled(self):
        args = types.SimpleNamespace(
            host="PRIVATE_HOST",
            cert=Path("PRIVATE_CERT"),
            key=Path("PRIVATE_KEY"),
            ready_delay=1,
            audio_delay=0,
            processing_grace=0,
            startup="poll",
            pace="burst",
        )
        stream = Mock(send_chunk=Mock(return_value=True))
        remote = Mock(
            start_voice=AsyncMock(return_value=stream),
            is_voice_enabled=False,
        )
        remote.transport.get_write_buffer_size.return_value = 0
        remote.async_connect = AsyncMock()

        async def poll(seconds):
            if seconds:
                remote.is_voice_enabled = True

        with (
            bridge(remote),
            patch.object(lab.asyncio, "sleep", side_effect=poll) as sleep,
        ):
            report = await lab.run_trial(args, bytes(8192))
        self.assertEqual(report["outcome"], "transport_completed")
        self.assertFalse(report["voice_enabled_at_connect"])
        self.assertEqual(sleep.await_args_list[0].args, (0.05,))
        self.assertNotIn(call(1), sleep.await_args_list)
        remote.start_voice.assert_awaited_once()
        remote.disconnect.assert_called_once()

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
        )
        remote.transport.get_write_buffer_size.return_value = 0

        observed = {}

        def make(host, cert, key, observe):
            observed["observe"] = observe
            return remote

        async def connect():
            app = Mock()
            app.HasField.side_effect = lambda field: field == "ime_key_inject"
            observed["observe"](remote, app)

        remote.async_connect = AsyncMock(side_effect=connect)
        with (
            patch.object(lab, "make_lab_client", side_effect=make),
            patch.object(lab.asyncio, "sleep", new_callable=AsyncMock) as sleep,
        ):
            report = await lab.run_trial(args, bytes(8192))
        self.assertEqual(report["outcome"], "transport_completed")
        self.assertEqual(report["events"][0]["event"], "initial_app_report")
        self.assertTrue(all(call.args == (0,) for call in sleep.await_args_list))
        remote.disconnect.assert_called_once()
        self.assertNotIn("PRIVATE", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
