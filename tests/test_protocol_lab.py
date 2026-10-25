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
        """Running the lab without --execute only prints a plan.

        Runs main with no arguments, with the live trial patched to fail the test if called.

        Verifies: it exits 0 without starting a trial and prints a JSON report in
        offline_plan mode.
        """
        with (
            patch.object(lab, "run_trial", side_effect=AssertionError("Live execution attempted")),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(lab.main([]), 0)
        self.assertEqual(json.loads(output.getvalue())["mode"], "offline_plan")

    def test_live_requires_a_fixture(self):
        """--execute alone is refused.

        Runs main with only --execute.

        Verifies: argparse exits with an error. It doesn't check which argument is reported
        missing (host, certificate, key or WAV).
        """
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            lab.main(["--execute"])

    def test_fixture_rate_matches_the_client(self):
        """The lab records at the client's sample rate.

        Verifies: the lab's RATE equals the client's SAMPLE_RATE (16000).
        """
        self.assertEqual(lab.RATE, lab.bridge_client().SAMPLE_RATE)

    def test_fixture_rate_duration_and_truncation(self):
        """WAV fixtures are checked for rate and completeness.

        Writes a one-second 16 kHz mono 16-bit WAV, reads it at 16 kHz and at 8 kHz, then
        truncates the file by two bytes and reads it again.

        Verifies: the 16 kHz read returns 32000 bytes; the rate mismatch and the truncated
        file both raise ValueError.
        """
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
        """The lab records the real client's TV messages without session ids.

        While start_voice is pending, feeds the client of a BridgeTrial a configure, an IME
        app report, a voice-begin and a close for session 999271.

        Verifies: start fails because the close arrived first; the lab records
        initial_app_report, remote_voice_begin and server_field_31, with the close matching
        the session; it captures the vendor as manufacturer and voice as enabled; the session
        id appears nowhere in the events.
        """
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
        """Failed trials clean up and keep private details out of the report.

        Runs one trial that fails on connect and one that fails while sending audio, with the
        host, certificate, key and error text all marked PRIVATE.

        Verifies: the client is disconnected once, voice is ended after the audio failure,
        the report says transport_failed with recognition not_observed, and no PRIVATE value
        appears in it.
        """
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
        """Poll startup requests voice as soon as the TV reports voice enabled.

        Runs a trial with --startup poll and a 1 s ready delay, where voice becomes enabled
        during the first poll.

        Verifies: the trial completes; the report records voice as not enabled at connect;
        it polls in 0.05 s steps and never sleeps the 1 s delay; voice is requested once and
        the client disconnected once.
        """
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
        """IME startup waits for the TV's app report instead of a fixed delay.

        Runs a trial with --startup ime and a 1 s ready delay, where connect delivers an IME
        app report.

        Verifies: the trial completes; the first event is initial_app_report; every sleep is
        zero seconds; the client is disconnected once; no PRIVATE value appears in the
        report.
        """
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
