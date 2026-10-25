# WebSocket protocol

All commands use HA's authenticated WebSocket connection and require TV-control permission, checked again on every audio and stop operation. Each TV can have one active recording; TVs are independent.

## Commands

| Command | Takes | Result and effect |
| --- | --- | --- |
| `tv_voice_bridge/start` | Fresh 32-character lowercase hex `request_id`, optional `remote_entity` | Reserves the TV, connects and requests voice. Returns `session_id`, `binary_handler_id`, `protocol_version: 2`, `sample_rate: 16000`, `chunk_bytes: 8192`, `max_seconds: 15`, `max_bytes: 480000`. |
| `tv_voice_bridge/progress` | `session_id`, next expected `sequence` | Returns `received_bytes`. |
| `tv_voice_bridge/stop` | `session_id`, `cancel` (default false), `expected_bytes` | When `expected_bytes` matches the received total, forwards the held audio to the TV in `chunk_bytes` pieces and ends voice; with `cancel`, discards it. Replies after the TV connection closes with `received_bytes`, `forwarded_bytes`, `peak`, `delivery_failed` and `error`. |
| `tv_voice_bridge/cancel` | `request_id` | Cancels the connection's pending or ready session, including during start. Idempotent. |
| `tv_voice_bridge/list` | — | TVs the user may control. |

## Audio frames

Audio travels only as binary frames on the same WebSocket: one HA handler byte, the 16-byte session token, a uint32 little-endian sequence starting at zero, then 1–16384 bytes of even-length PCM16LE. Frames and commands keep WebSocket order. The bridge holds the audio in memory and forwards it to the TV only on stop.

## Limits

| Limit | Value |
| --- | --- |
| TV connection | 10 s |
| Voice start after the 1 s readiness delay | 5 s |
| First audio after voice start | 30 s |
| Upload inactivity after that | 15 s |
| Session lifetime | 90 s |
| Audio per session | 480000 bytes |

Uploaded frames extend the inactivity deadline, never the session lifetime.

## Errors and cleanup

Errors are stable codes that frontends localize. Logs never include audio payloads or exception text. After a frame failure or timeout, the owning connection receives the original code on progress or stop for 30 seconds (at most 128 retained across the integration); other connections receive `session_ended`. Disconnect, entry unload and HA shutdown clean up sessions.

## TV messages

`custom_components/tv_voice_bridge/voice.proto` defines the voice messages: client field 30 configures the session, 31 carries raw audio and 32 ends voice; server field 30 requests voice and 31 closes the session. Handshake, ping and key messages follow upstream `remotemessage.proto` numbering, and tests check them against `tests/upstream_schema.proto`, a fixed copy of the androidtvremote2 0.3.2 layout. Session behaviour on the TV side is described in [Compatibility](compatibility.md).
