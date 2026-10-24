"""Isolated protocol experiments. Default invocation is offline; --execute is live.

Run directly from the checkout. No Home Assistant imports, pairing changes,
microphone capture, automatic device discovery, or release operations.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import importlib
from importlib.metadata import version
import json
import logging
import math
from pathlib import Path
import sys
import time
import types
from typing import Any
import wave

LIBRARY_VERSION = "0.3.2"
CHUNK_BYTES = 8192


@dataclass(frozen=True)
class Case:
    name: str
    rate: int
    payload: str
    configured_begin: bool


CASES = {
    case.name: case
    for case in (
        Case("current", 16000, "raw", True),
        Case("nested-16k", 16000, "nested", True),
        Case("raw-8k", 8000, "raw", True),
        Case("nested-8k", 8000, "nested", True),
        Case("upstream", 8000, "nested", False),
        Case("raw-8k-default", 8000, "raw", False),
    )
}


def varint(value: int) -> bytes:
    """Encode positive fixture values for the legacy comparison cases only."""
    output = bytearray()
    while value > 127:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)
    return bytes(output)


class WireMessage:
    """Legacy comparison message; production uses generated protobuf schemas."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    def ByteSize(self) -> int:
        return len(self.data)

    def SerializeToString(self) -> bytes:
        return self.data


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
            raise ValueError("Use an uncompressed mono PCM16 WAV at the case rate, up to 15s")
        expected = wav.getnframes() * 2
        audio = wav.readframes(wav.getnframes())
    if len(audio) != expected:
        raise ValueError("Truncated WAV")
    return audio


def bridge_protocol() -> Any:
    """Load the actual production adapter without executing HA's __init__.py."""
    package_name = "_tv_voice_lab_bridge"
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [
            str(Path(__file__).resolve().parents[1] / "custom_components/tv_voice_bridge")
        ]
        sys.modules[package_name] = package
    return importlib.import_module(package_name + ".protocol")


def install_case(remote: Any, case: Case) -> None:
    """Use production unchanged for current, upstream unchanged for upstream.

    Experimental variants alter only the selected outgoing voice fields.
    These private API accesses belong to this version-gated diagnostic tool.
    """
    if version("androidtvremote2") != LIBRARY_VERSION:
        raise ValueError("Protocol lab requires androidtvremote2 0.3.2")
    if case.name == "upstream":
        return
    adapter = bridge_protocol()
    if case.name == "current":
        adapter.configure_voice_protocol(remote)
        return
    protocol = remote._remote_message_protocol
    original_send = protocol._send_message

    def send(message: Any, should_debug_log: bool = True) -> None:
        if case.configured_begin and message.HasField("remote_voice_begin"):
            begin = (
                b"\x08"
                + varint(message.remote_voice_begin.session_id)
                + b"\x50"
                + varint(case.rate)
                + b"\x58\x10\x60\x02"
            )
            data = b"\xf2\x01" + varint(len(begin)) + begin
        elif case.payload == "raw" and message.HasField("remote_voice_payload"):
            samples = message.remote_voice_payload.samples
            data = b"\xfa\x01" + varint(len(samples)) + samples
        else:
            original_send(message, should_debug_log)
            return
        original_send(WireMessage(data), False)

    protocol._send_message = send


def observe_messages(remote: Any, events: list[dict[str, Any]], started: float) -> None:
    """Count TV replies without logging audio, echoed payloads or transcripts."""
    from androidtvremote2.remotemessage_pb2 import RemoteMessage

    protocol = remote._remote_message_protocol
    original_handle = protocol._handle_message
    session_id = None

    def handle(raw: bytes) -> None:
        nonlocal session_id
        message = RemoteMessage()
        try:
            message.ParseFromString(raw)
            if message.HasField("remote_voice_begin"):
                session_id = message.remote_voice_begin.session_id
            for field in ("remote_voice_begin", "remote_voice_end", "remote_error"):
                if message.HasField(field):
                    events.append({"event": field, "seconds": round(time.monotonic() - started, 3)})
            # The inspected TV-to-client schema assigns field 31 to a close
            # request. Upstream's shared-direction schema calls it a payload.
            if message.HasField("remote_voice_payload"):
                payload = message.remote_voice_payload
                events.append(
                    {
                        "event": "server_field_31",
                        "seconds": round(time.monotonic() - started, 3),
                        "session_matches": session_id is not None
                        and payload.session_id == session_id,
                        "has_samples": bool(payload.samples),
                    }
                )
        except Exception:
            events.append({"event": "unparsed_reply"})
        original_handle(raw)

    protocol._handle_message = handle


def observe_payload_shape(remote: Any, report: dict[str, Any]) -> None:
    """Record wrapper size only, without retaining session IDs or audio bytes."""
    protocol = remote._remote_message_protocol
    original_send = protocol._send_message
    overheads: set[int] = set()
    report["upstream_payload_wrapper_bytes"] = []

    def send(message: Any, should_debug_log: bool = True) -> None:
        if message.HasField("remote_voice_payload"):
            payload = message.remote_voice_payload
            overheads.add(payload.ByteSize() - len(payload.samples))
            report["upstream_payload_wrapper_bytes"] = sorted(overheads)
        original_send(message, should_debug_log)

    protocol._send_message = send


async def run_case(args: argparse.Namespace, case: Case, audio: bytes) -> dict[str, Any]:
    """Open one dedicated connection, send one fixture, and always disconnect."""
    from androidtvremote2 import AndroidTVRemote

    started = time.monotonic()
    events: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "started_utc": datetime.now(UTC).isoformat(),
        "case": asdict(case),
        "library_version": version("androidtvremote2"),
        "ready_delay": args.ready_delay,
        "startup": getattr(args, "startup", "delay"),
        "processing_grace": args.processing_grace,
        "audio_delay": getattr(args, "audio_delay", 0),
        "pace": args.pace,
        "fixture_sha256": hashlib.sha256(audio).hexdigest(),
        "input_bytes": len(audio),
        "transport_accepted_bytes": 0,
        "recognition": "not_observed",
        "events": events,
    }
    remote = AndroidTVRemote(
        "TV Voice Protocol Lab",
        str(args.cert),
        str(args.key),
        args.host,
        enable_ime=True,
        enable_voice=True,
    )
    stream = None
    app_ready = asyncio.Event()

    def on_app(_app: str) -> None:
        if not app_ready.is_set():
            events.append(
                {"event": "initial_app_report", "seconds": round(time.monotonic() - started, 3)}
            )
            app_ready.set()

    wait_for_app = getattr(args, "startup", "delay") == "ime"
    if wait_for_app:
        remote.add_current_app_updated_callback(on_app)
    # Upstream remote_error logging can include the TV's echoed audio message.
    logger = logging.getLogger("androidtvremote2")
    was_disabled = logger.disabled
    logger.disabled = True
    try:
        async with asyncio.timeout(90):
            async with asyncio.timeout(10):
                await remote.async_connect()
            report["device_info"] = remote.device_info
            report["connect_seconds"] = round(time.monotonic() - started, 3)
            report["voice_enabled_at_connect"] = bool(remote.is_voice_enabled)
            install_case(remote, case)
            observe_payload_shape(remote, report)
            observe_messages(remote, events, started)
            if wait_for_app:
                async with asyncio.timeout(5):
                    await app_ready.wait()
            elif getattr(args, "startup", "delay") == "poll":
                # Rejected review proposal: poll the handshake flag, delay as ceiling.
                deadline = time.monotonic() + args.ready_delay
                while not remote.is_voice_enabled and time.monotonic() < deadline:  # noqa: ASYNC110
                    await asyncio.sleep(0.05)
            else:
                await asyncio.sleep(args.ready_delay)
            if not remote.is_voice_enabled:
                raise RuntimeError("voice_unsupported")
            report["voice_request_seconds"] = round(time.monotonic() - started, 3)
            stream = await remote.start_voice(timeout=5)
            report["voice_ready_seconds"] = round(time.monotonic() - started, 3)
            await asyncio.sleep(getattr(args, "audio_delay", 0))
            report["first_audio_seconds"] = round(time.monotonic() - started, 3)
            audio_started = time.monotonic()
            for offset in range(0, len(audio), CHUNK_BYTES):
                if args.pace == "realtime":
                    await asyncio.sleep(
                        max(0, audio_started + offset / (case.rate * 2) - time.monotonic())
                    )
                chunk = audio[offset : offset + CHUNK_BYTES]
                if not stream.send_chunk(chunk):
                    raise RuntimeError("stream_closed")
                report["transport_accepted_bytes"] += len(chunk)
            if args.pace == "realtime":
                await asyncio.sleep(
                    max(0, audio_started + len(audio) / (case.rate * 2) - time.monotonic())
                )
            stream.end()
            stream = None
            report["buffered_bytes_at_end"] = (
                remote._remote_message_protocol.transport.get_write_buffer_size()
            )
            await asyncio.sleep(args.processing_grace)
            report["buffered_bytes_before_disconnect"] = (
                remote._remote_message_protocol.transport.get_write_buffer_size()
            )
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
            try:
                remote.disconnect()
            finally:
                try:
                    if wait_for_app:
                        remote.remove_current_app_updated_callback(on_app)
                finally:
                    logger.disabled = was_disabled
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return report


def bounded_seconds(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or not 0 <= seconds <= 15:
        raise argparse.ArgumentTypeError("Use a finite delay between 0 and 15 seconds")
    return seconds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, default="current")
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
    case = CASES[args.case]
    audio = None
    if args.wav:
        try:
            audio = read_audio(args.wav, case.rate)
        except (ValueError, OSError, EOFError, wave.Error) as error:
            parser.error("Invalid WAV fixture: " + type(error).__name__)
    if not args.execute:
        print(
            json.dumps(
                {
                    "mode": "offline_plan",
                    "case": asdict(case),
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
    if version("androidtvremote2") != LIBRARY_VERSION:
        parser.error("Install androidtvremote2==0.3.2 in an isolated environment")
    assert audio is not None
    report = asyncio.run(run_case(args, case, audio))
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["outcome"] == "transport_completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
