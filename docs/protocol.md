# WebSocket protocol

All control commands use HA's authenticated WebSocket connection and require TV-control permission. Each configured TV can have one active recording. Multiple TVs have independent reservations.

1. `tv_voice_bridge/start` takes a fresh 32-character lowercase hexadecimal `request_id` and optionally `remote_entity`. It reserves the TV before awaiting network setup. The result includes `session_id`, `binary_handler_id`, `protocol_version: 2`, `sample_rate: 16000`, `chunk_bytes: 8192`, `max_seconds: 15`, and `max_bytes: 480000`.
2. Send binary frames on that same WebSocket: one HA handler byte, 16 raw session-token bytes, a uint32 little-endian sequence (starting at zero), then even-length PCM16LE. The PCM part is non-empty and at most 16384 bytes. This token protects against stale frames reaching a reused handler slot. HA routes binary frames without logging their payload as JSON.
3. After a frame, `tv_voice_bridge/progress` takes `session_id` and the next expected `sequence`. Its result acknowledges `received_bytes`. Clients use this to bound outstanding work. Frames and control messages retain WebSocket order.
4. `tv_voice_bridge/stop` takes `session_id`, `cancel` (default false), and `expected_bytes` for submission. The byte count must equal the received total before the bridge flushes the final partial chunk and ends voice. The result contains `received_bytes`, `forwarded_bytes`, `peak`, `delivery_failed`, and `error`. Forwarded bytes measure acceptance by the TV transport, not recognition.
5. `tv_voice_bridge/cancel` takes `request_id` and cancels a pending or ready session owned by that connection. It is idempotent and can run while start is awaiting the TV.
6. `tv_voice_bridge/list` lists configured TVs visible to that user's control permissions.

Audio is accepted only through binary frames. JSON audio commands are unsupported because HA debug logging records JSON commands before component dispatch.

Limits are independent: at most 10 seconds for connection setup, a bounded readiness delay and 5 seconds for voice negotiation; 30 seconds until first audio after readiness; 15 seconds of upload inactivity thereafter; 90 seconds total session lifetime. Every PCM input is bounded by 480000 bytes. The browser independently caps capture at 15 seconds in its worklet. Uploaded chunks extend the idle deadline but never the absolute deadline.

Errors are stable codes. Frontends localize codes and never display raw exceptions. The binary handler catches failures without including payloads or exception contents in logs. Both startup and every audio/finalization operation check ownership and current permissions. Socket disconnect, integration unload and HA shutdown clean up sessions.
