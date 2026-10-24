# Changelog

## 1.2.2 — 2026-10-24

- Keep loading if Home Assistant changes Lovelace internals. The migration of pre-1.0 dashboard resources is now optional: it is skipped, not fatal, when the resource collection is missing or changed, and `lovelace` is no longer a hard dependency.
- Report moved pairing files clearly. If the core Android TV Remote integration is connected but its pairing files are not where the bridge expects them, setup and the config flow report `pairing_not_found` ("Update TV Voice Bridge") instead of asking to pair the TV again. A test compares the bridge's paths with core's own client factory.
- Define the card after a 10-second fallback if Home Assistant's root element never appears, so a renamed root element cannot leave the card unregistered.
- Add a weekly compatibility workflow against Home Assistant stable and beta: Python tests with each release's pinned library versions, and a browser check that a dashboard renders the card on repeated loads.

## 1.2.1 — 2026-10-24

- Fix the microphone card not being found on Home Assistant 2026.10.3 (`Custom element doesn't exist: tv-voice-card`, or wrapper cards waiting forever). HA imports integration frontend modules in parallel with its app bundle, which can replace `window.customElements` with a scoped-registry polyfill that ignores elements defined before it. The card and its editor now define themselves after HA's root element is registered, so they land in the registry dashboards use.

Validated with frontend tests that simulate the registry being replaced after the module loads; the previous eager definition fails them. Not yet verified on a live installation.

## 1.2.0 — 2026-10-24

- Stream audio to Home Assistant while recording, with up to four unacknowledged frames in flight, instead of buffering the whole recording and acknowledging each frame after release. Releasing the button now leaves only the final partial chunk and in-flight acknowledgements to wait for.
- Hold received audio in the bridge until a non-cancelled stop, then forward it to the TV as a burst (the submission path validated in trials 35–36). Cancellation still guarantees that no speech reaches the TV.
- Surface upload failures, including a TV voice-close, while still recording instead of after release.
- Stop re-rendering the card on every Home Assistant state update; only a language or connection change now does any work.
- Preallocate the recording buffer instead of copying it on every worklet message, and compute the server-side peak with `array` rather than per-sample `struct` unpacking.
- Protocol lab: add `--startup poll` and record whether voice is enabled at connection. Live trials rejected polling and shorter delays as replacements for the one-second startup delay.
- Consolidate the research and validation notes into `docs/voice-protocol-research.md`, and move per-release validation into this changelog.

Validated against Home Assistant 2026.10.2 and androidtvremote2 0.3.2 with 54 Python tests (93% statement coverage), frontend tests, Ruff, mypy and tag/version checks, and GitHub CI including hassfest and HACS validation. On one TCL, the streaming build measured 163 ms from release to sent (v1.1.0: 910 ms, ending in `session_ended`); release before the TV was ready was sent once ready, and Escape mid-stream forwarded nothing. The later dead-code cleanup was not live-tested and does not change behaviour. Other devices remain unverified.

## 1.1.0 — 2026-10-22

- Replace fixed post-upload processing grace with awaited graceful transport shutdown and a bounded abort deadline.
- Stop audio on matching TV voice-close events, including stale/duplicate/early-close handling.
- Generate separate client/server voice schemas, removing handwritten production protobuf serialization while retaining the isolated library compatibility gate.
- Prevent remote error echoes from logging voice audio; add protocol, shutdown and real HA WebSocket regression coverage.
- Bound browser startup, upload and finalization waits, with a separate overall deadline.
- Release local audio immediately on cancellation without waiting for server replies or overwriting the original feedback.
- Preserve binary failure and timeout codes briefly after session cleanup, with bounded, connection-owned metadata and complete lifecycle cleanup.
- Add regression coverage for stalled replies, cancellation races, late responses and terminal-error ownership, expiry and eviction.

Validated against Home Assistant 2026.10.2 and androidtvremote2 0.3.2 with 52 Python tests (93% statement coverage), frontend tests, Ruff, mypy and tag/version checks, five live TV trials and owner-reported phone acceptance on one TCL. The component-only release ZIP contains exactly 26 files matching the release checkout. Other devices remain unverified. The one-second startup delay and version-gated private protocol adapter remain; transport completion does not confirm recognition.

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

Validated against Home Assistant 2026.10.2 and androidtvremote2 0.3.2 with 19 Python tests (92% statement coverage), frontend and synthetic-browser tests, and Ruff, mypy and release metadata checks. Real phone-to-TV speech, early release during connection, the 15-second limit and consecutive recordings were verified on one TCL using the Home Assistant phone app.
