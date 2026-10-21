"""Voice wire format used by the installed Android TV Remote Service.

androidtvremote2 0.3.2 models field 31 as a nested session_id/samples
message. This TV reads field 31 as raw bytes. Its five-byte nested header
misaligns PCM16 samples. Adapt only this bridge's dedicated connection.
"""

from importlib.metadata import version
from typing import Any

from .const import SAMPLE_RATE, SUPPORTED_LIBRARY_VERSION
from .errors import VoiceError

# Read package metadata once during executor-based integration import.
LIBRARY_VERSION = version("androidtvremote2")


def validate_compatibility() -> None:
    """Fail clearly before touching private APIs of an untested library."""
    if LIBRARY_VERSION != SUPPORTED_LIBRARY_VERSION:
        raise VoiceError("unsupported_version")


def varint(value: int) -> bytes:
    output = bytearray()
    while value > 127:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)
    return bytes(output)


class WireMessage:
    """Minimal serialized message consumed by the upstream framed transport."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    def ByteSize(self) -> int:
        return len(self.data)

    def SerializeToString(self) -> bytes:
        return self.data


def configure_voice_protocol(remote: Any) -> None:
    """Preserve upstream pairing/handshake, correct outgoing voice messages."""
    validate_compatibility()
    protocol = remote._remote_message_protocol
    original_send = protocol._send_message

    def send(message: Any, should_debug_log: bool = True) -> None:
        if message.HasField("remote_voice_begin"):
            # VoiceBegin: session_id=1, sample_rate=10, channel_config=11
            # (Android CHANNEL_IN_MONO=16), audio_format=12 (PCM_16BIT=2).
            begin = (
                b"\x08"
                + varint(message.remote_voice_begin.session_id)
                + b"\x50"
                + varint(SAMPLE_RATE)
                + b"\x58\x10\x60\x02"
            )
            data = b"\xf2\x01" + varint(len(begin)) + begin
        elif message.HasField("remote_voice_payload"):
            samples = message.remote_voice_payload.samples
            data = b"\xfa\x01" + varint(len(samples)) + samples
        else:
            original_send(message, should_debug_log)
            return
        # Do not pass audio to protobuf's debug logger.
        original_send(WireMessage(data), False)

    protocol._send_message = send
