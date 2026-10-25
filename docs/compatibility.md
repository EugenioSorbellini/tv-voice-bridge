# Compatibility contract

## Requirements

- Home Assistant **2026.10.2** or later, as declared in hacs.json. CI tests that exact release, and a weekly workflow tests the current stable and beta releases.
- The core Android TV Remote integration, set up and paired. The bridge takes the TV host from its config entry and the certificate and key from its pairing files; a test compares those paths with core's own client factory.
- No extra Python packages. Home Assistant supplies the protobuf runtime.

## Verified hardware

Speech recognition is verified on one TCL with Google Android TV Remote Service **7.00.999235495**. Device reports should include the TV model and Remote Service version, without speech content.

## Voice client

The bridge's voice-only client (`client.py`) opens its own TLS connection to the TV with the core pairing. Its handshake replies, client identity and feature flags match androidtvremote2 **0.3.2**, and it handles the handshake, pings and idle timeout itself.

- **Audio:** raw PCM16, 16 kHz mono (Android channel mask 16, format 2), sent as bytes in protobuf field 31 in 8192-byte chunks. The client and server messages are defined in `voice.proto`.
- **Start:** after connecting, the bridge waits one second, requests voice and waits for the TV's voice-begin reply before sending audio. The one-second delay is tuned on the tested TV.
- **Submission:** the card streams its recording to Home Assistant while capturing; the bridge holds it and forwards it to the TV only on stop. It then sends voice-end, closes the connection gracefully and waits up to five seconds for the close, reporting a delivery failure if it stalls. The TV stays reserved until the connection has closed. Forwarded bytes mean the TV transport accepted the audio, not that the assistant recognized it.
- **TV voice-close:** a matching close from the TV stops further audio, discards any unsent chunk and is reported to the card as `session_ended` on its next progress or stop request. Closes for other sessions are ignored.
- **Cancellation and unload** discard held audio and close the connection with the same five-second limit.

The [voice protocol research](voice-protocol-research.md) records the tested installation, trial results and evidence behind these choices.
