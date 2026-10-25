"""Isolated protocol experiments. Default invocation is offline; --execute is live.

Run directly from the checkout. No Home Assistant imports, pairing changes,
microphone capture, automatic device discovery, or release operations.
It runs the production client at its 16 kHz rate. The earlier comparison
cases against androidtvremote2 0.3.2 are recorded in
docs/voice-protocol-research.md and in Git history.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import importlib
import json
import math
from pathlib import Path
import sys
import time
import types
from typing import Any
import wave

CHUNK_BYTES = 8192
RATE = 16000  # The client's SAMPLE_RATE; tests check they match.


def read_audio(path: Path, rate: int) -> bytes:
    """Validate the complete fixture before any live connection is created."""
    with wave.open(str(path), "rb") as wav:
        if (
            wav.getnchannels() != 1
            or wav.getsampwidth() != 2
            or wav.getframerate() != rate
            or wav.getcomptype() != "NONE"
            or not 0 < wav.getnframes() <= rate * 15
        ):
            raise ValueError("Use an uncompressed mono PCM16 WAV at the client rate, up to 15s")
        expected = wav.getnframes() * 2
        audio = wav.readframes(wav.getnframes())
    if len(audio) != expected:
        raise ValueError("Truncated WAV")
    return audio


def bridge_client() -> Any:
    """Load the actual production client without executing HA's __init__.py."""
    package_name = "_tv_voice_lab_bridge"
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [
            str(Path(__file__).resolve().parents[1] / "custom_components/tv_voice_bridge")
        ]
        sys.modules[package_name] = package
    return importlib.import_module(package_name + ".client")


def make_lab_client(host: str, cert: str, key: str, observe: Any) -> Any:
    """The production client, plus an observer of each message it has handled.

    Subclassing reaches the client's own _handle; the lab tests cover that coupling.
    """
    base = bridge_client().TvVoiceClient

    class LabClient(base):  # type: ignore[misc, valid-type]
        def _handle(self, message: Any) -> None:
            super()._handle(message)
            observe(self, message)

    return LabClient(host, cert, key, asyncio.get_running_loop())


class BridgeTrial:
    """The production client, observed through the lab's event log."""

    def __init__(self, args: argparse.Namespace, lab: Any):
        self._lab = lab
        self.device_info: dict[str, str] = {}
        self.remote = make_lab_client(args.host, str(args.cert), str(args.key), self._observe)

    def _observe(self, client: Any, message: Any) -> None:
        """Record event names and timing only, never audio or session ids."""
        if message.HasField("configure"):
            info = message.configure.device_info
            self.device_info = {
                "manufacturer": info.vendor,
                "model": info.model,
                "sw_version": info.app_version,
            }
        if message.HasField("ime_key_inject"):
            self._lab.app_reported()
        for field, event in (("error", "remote_error"), ("voice_begin", "remote_voice_begin")):
            if message.HasField(field):
                self._lab.event(event)
        if message.HasField("voice_close"):
            # Observed after handling: the flag is set only by a close for our session.
            self._lab.event("server_field_31", session_matches=client.voice_closed_by_tv)

    @property
    def voice_enabled(self) -> bool:
        return bool(self.remote.is_voice_enabled)

    async def connect(self) -> None:
        await self.remote.async_connect()

    async def start_voice(self) -> Any:
        async with asyncio.timeout(5):
            return await self.remote.start_voice()

    def buffered(self) -> int:
        return int(self.remote.transport.get_write_buffer_size())

    def close(self) -> None:
        self.remote.disconnect()


class Lab:
    """Shared event log and the one-shot initial app report."""

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.events: list[dict[str, Any]] = []
        self.app_ready = asyncio.Event()

    def seconds(self) -> float:
        return round(time.monotonic() - self.started, 3)

    def event(self, name: str, **details: Any) -> None:
        self.events.append({"event": name, "seconds": self.seconds(), **details})

    def app_reported(self) -> None:
        if not self.app_ready.is_set():
            self.event("initial_app_report")
            self.app_ready.set()


async def run_trial(args: argparse.Namespace, audio: bytes) -> dict[str, Any]:
    """Open one dedicated connection, send one fixture, and always disconnect."""
    lab = Lab()
    startup = getattr(args, "startup", "delay")
    report: dict[str, Any] = {
        "started_utc": datetime.now(UTC).isoformat(),
        "rate": RATE,
        "ready_delay": args.ready_delay,
        "startup": startup,
        "processing_grace": args.processing_grace,
        "audio_delay": getattr(args, "audio_delay", 0),
        "pace": args.pace,
        "fixture_sha256": hashlib.sha256(audio).hexdigest(),
        "input_bytes": len(audio),
        "transport_accepted_bytes": 0,
        "recognition": "not_observed",
        "events": lab.events,
    }
    stream = None
    trial: BridgeTrial | None = None
    try:
        trial = BridgeTrial(args, lab)
        async with asyncio.timeout(90):
            async with asyncio.timeout(10):
                await trial.connect()
            report["device_info"] = trial.device_info
            report["connect_seconds"] = lab.seconds()
            report["voice_enabled_at_connect"] = trial.voice_enabled
            if startup == "ime":
                async with asyncio.timeout(5):
                    await lab.app_ready.wait()
            elif startup == "poll":
                # Rejected review proposal: poll the handshake flag, delay as ceiling.
                deadline = time.monotonic() + args.ready_delay
                while not trial.voice_enabled and time.monotonic() < deadline:  # noqa: ASYNC110
                    await asyncio.sleep(0.05)
            else:
                await asyncio.sleep(args.ready_delay)
            if not trial.voice_enabled:
                raise RuntimeError("voice_unsupported")
            report["voice_request_seconds"] = lab.seconds()
            stream = await trial.start_voice()
            report["voice_ready_seconds"] = lab.seconds()
            await asyncio.sleep(getattr(args, "audio_delay", 0))
            report["first_audio_seconds"] = lab.seconds()
            audio_started = time.monotonic()
            for offset in range(0, len(audio), CHUNK_BYTES):
                if args.pace == "realtime":
                    await asyncio.sleep(
                        max(0, audio_started + offset / (RATE * 2) - time.monotonic())
                    )
                chunk = audio[offset : offset + CHUNK_BYTES]
                if not stream.send_chunk(chunk):
                    raise RuntimeError("stream_closed")
                report["transport_accepted_bytes"] += len(chunk)
            if args.pace == "realtime":
                await asyncio.sleep(
                    max(0, audio_started + len(audio) / (RATE * 2) - time.monotonic())
                )
            stream.end()
            stream = None
            report["buffered_bytes_at_end"] = trial.buffered()
            await asyncio.sleep(args.processing_grace)
            report["buffered_bytes_before_disconnect"] = trial.buffered()
            report["outcome"] = "transport_completed"
    except Exception as error:
        # Exception strings can contain hostnames or protocol payloads.
        report["outcome"] = "transport_failed"
        report["exception_type"] = type(error).__name__
    finally:
        try:
            if stream is not None:
                stream.end()
        except Exception:
            report["cleanup_end_failed"] = True
        finally:
            if trial is not None:
                trial.close()
        report["elapsed_seconds"] = lab.seconds()
    return report


def bounded_seconds(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or not 0 <= seconds <= 15:
        raise argparse.ArgumentTypeError("Use a finite delay between 0 and 15 seconds")
    return seconds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wav", type=Path)
    parser.add_argument("--host")
    parser.add_argument("--cert", type=Path)
    parser.add_argument("--key", type=Path)
    parser.add_argument("--ready-delay", type=bounded_seconds, default=1.0)
    parser.add_argument("--startup", choices=("delay", "ime", "poll"), default="delay")
    parser.add_argument("--processing-grace", type=bounded_seconds, default=15.0)
    parser.add_argument("--audio-delay", type=bounded_seconds, default=0.0)
    parser.add_argument("--pace", choices=("burst", "realtime"), default="burst")
    parser.add_argument("--execute", action="store_true", help="LIVE: opens the TV assistant")
    args = parser.parse_args(argv)
    audio = None
    if args.wav:
        try:
            audio = read_audio(args.wav, RATE)
        except (ValueError, OSError, EOFError, wave.Error) as error:
            parser.error("Invalid WAV fixture: " + type(error).__name__)
    if not args.execute:
        print(
            json.dumps(
                {
                    "mode": "offline_plan",
                    "rate": RATE,
                    "fixture_validated": audio is not None,
                    "ready_delay": args.ready_delay,
                    "startup": args.startup,
                    "processing_grace": args.processing_grace,
                    "audio_delay": args.audio_delay,
                    "pace": args.pace,
                    "live_requires": "--execute and explicit start authorization",
                }
            )
        )
        return 0
    if not all((args.host, args.cert, args.key, audio)):
        parser.error("Live execution requires --host, --cert, --key and a valid --wav")
    assert audio is not None
    report = asyncio.run(run_trial(args, audio))
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["outcome"] == "transport_completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
