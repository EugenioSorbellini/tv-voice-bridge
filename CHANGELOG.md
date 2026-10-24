# Changelog

## Unreleased

- Stream audio to Home Assistant while recording, with up to four unacknowledged frames in flight, instead of buffering the whole recording and acknowledging each frame after release. Releasing the button now leaves only the final partial chunk and in-flight acknowledgements to wait for.
- Hold received audio in the bridge until a non-cancelled stop, then forward it to the TV as a burst (the submission path validated in trials 35–36). Cancellation still guarantees that no speech reaches the TV.
- Surface upload failures, including a TV voice-close, while still recording instead of after release.
- Stop re-rendering the card on every Home Assistant state update; only a language or connection change now does any work.
- Preallocate the recording buffer instead of copying it on every worklet message, and compute the server-side peak with `array` rather than per-sample `struct` unpacking.

## 1.1.0 — 2026-10-22

- Replace fixed post-upload processing grace with awaited graceful transport shutdown and a bounded abort deadline.
- Stop audio on matching TV voice-close events, including stale/duplicate/early-close handling.
- Generate separate client/server voice schemas, removing handwritten production protobuf serialization while retaining the isolated library compatibility gate.
- Prevent remote error echoes from logging voice audio; add protocol, shutdown and real HA WebSocket regression coverage.
- Bound browser startup, upload and finalization waits, with a separate overall deadline.
- Release local audio immediately on cancellation without waiting for server replies or overwriting the original feedback.
- Preserve binary failure and timeout codes briefly after session cleanup, with bounded, connection-owned metadata and complete lifecycle cleanup.
- Add regression coverage for stalled replies, cancellation races, late responses and terminal-error ownership, expiry and eviction.

Validated against Home Assistant 2026.10.2 and androidtvremote2 0.3.2 with 52 Python tests, frontend tests, five live TV trials and owner-reported phone acceptance on one TCL. Other devices remain unverified. The one-second startup delay and version-gated private protocol adapter remain; transport completion does not confirm recognition.

## 1.0.0 — 2026-10-21

Baseline release of the standalone microphone integration.

- HACS installation with a bundled, automatically registered microphone card.
- UI configuration, one entry per TV, reconfiguration, cleanup and redacted diagnostics.
- Immediate microphone capture during TV connection, buffered delivery after early release, and a 15-second recording cap.
- Authenticated binary audio delivery with independent session deadlines and cancellation.
- Hold, toggle, keyboard and assistive activation, with English and Italian translations.
- Generic CSS parts and recording-state styling for composition in dashboard projects.
- A version-gated androidtvremote2 adapter, with real speech verified on one TCL installation.
- Home Assistant and frontend tests, CI validation, release packaging and MIT licensing.
