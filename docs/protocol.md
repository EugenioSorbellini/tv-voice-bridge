# WebSocket protocol

All control commands use HA's authenticated WebSocket connection and require TV-control permission. Each configured TV can have one active recording. Multiple TVs have independent reservations.

1. `tv_voice_bridge/start` takes a fresh 32-character lowercase hexadecimal `request_id` and optionally `remote_entity`. It reserves the TV before awaiting network setup. The result includes `session_id`, `binary_handler_id`, `protocol_version: 2`, `sample_rate: 16000`, `chunk_bytes: 8192`, `max_seconds: 15`, and `max_bytes: 480000`.
2. Send binary frames on that same WebSocket: one HA handler byte, 16 raw session-token bytes, a uint32 little-endian sequence (starting at zero), then even-length PCM16LE. The PCM part is non-empty and at most 16384 bytes. This token protects against stale frames reaching a reused handler slot. HA routes binary frames without logging their payload as JSON.
3. After a frame, `tv_voice_bridge/progress` takes `session_id` and the next expected `sequence`. Its result acknowledges `received_bytes`. Clients use this to bound outstanding work. Frames and control messages retain WebSocket order.
4. `tv_voice_bridge/stop` takes `session_id`, `cancel` (default false), and `expected_bytes` for submission. The byte count must equal the received total before the bridge flushes the final partial chunk and ends voice. The result contains `received_bytes`, `forwarded_bytes`, `peak`, `delivery_failed`, and `error`. The stop reply waits for graceful transport shutdown, with a five-second failure deadline that aborts a stalled close and sets `delivery_failed`. The TV remains reserved until cleanup completes. Forwarded bytes measure acceptance by the TV transport, not recognition.
5. `tv_voice_bridge/cancel` takes `request_id` and cancels a pending or ready session owned by that connection. It is idempotent and can run while start is awaiting the TV. The bundled card uses this command alone for cancellation and releases local audio without waiting for its reply.
6. `tv_voice_bridge/list` lists configured TVs visible to that user's control permissions.

Audio is accepted only through binary frames. JSON audio commands are unsupported because HA debug logging records JSON commands before component dispatch.

Limits are independent: at most 10 seconds for connection setup, a bounded readiness delay and 5 seconds for voice negotiation; 30 seconds until first audio after readiness; 15 seconds of upload inactivity thereafter; 90 seconds total session lifetime. Every PCM input is bounded by 480000 bytes. The browser independently caps capture at 15 seconds in its worklet. Uploaded chunks extend the idle deadline but never the absolute deadline.

The bundled card also bounds its waits when a socket remains open but replies stop arriving: 20 seconds for start, 10 seconds per progress/stop request, and 90 seconds overall from the start request. A timeout discards local audio and sends a best-effort cancellation. Cancellation interrupts pending waits; late replies cannot resume an abandoned recording.

Errors are stable codes. Frontends localize codes and never display raw exceptions. The binary handler catches failures without including payloads or exception contents in logs. Both startup and every audio/finalization operation check ownership and current permissions. Socket disconnect, integration unload and HA shutdown clean up sessions.

After a binary failure or session timeout, the server retains only failure metadata for 30 seconds, with at most 128 terminal errors across the integration. Progress/stop requests from the owning connection receive the original error code, subject to current TV-control permission. Other connections receive `session_ended`. Retained errors do not reserve a TV or retain its session, transport or audio, and are removed on connection close, entry unload or HA shutdown.

## TV voice transport (v1.1.0)

`custom_components/tv_voice_bridge/voice.proto` defines distinct client and server voice messages. Client field 30 declares session and PCM configuration, field 31 contains raw audio bytes, and field 32 ends voice. Server field 30 requests voice; server field 31 closes a session. Only a close carrying the active session identifier stops forwarding. The server close is neither a general readiness hook nor proof of recognition.

A TV close drops the pending partial chunk and unregisters the binary upload handler. The owning client's next progress/stop request receives `session_ended`. The browser's existing recording buffer and capture limit are unchanged; this protocol version does not push a microphone-stop event.

The generated Python module and type stub are checked in. Regenerate them from the repository root in a separate compiler environment (the compiler is not a runtime dependency):

```sh
python3.12 -m venv /tmp/tv-voice-protoc
/tmp/tv-voice-protoc/bin/pip install grpcio-tools==1.60.2 setuptools==80.9.0
/tmp/tv-voice-protoc/bin/python -m grpc_tools.protoc -I. --python_out=. --pyi_out=. custom_components/tv_voice_bridge/voice.proto
```

Generated files are excluded from Ruff formatting to preserve reproducibility. This compiler generates descriptor-based code compatible with the existing dependency runtime range; it does not add a runtime-version gate. Home Assistant supplies the protobuf runtime. Keep the private adapter version gate until a released upstream voice API supports the verified schema and lifecycle hooks.
