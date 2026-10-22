# Unreleased protocol lifecycle validation — 2026-10-22

Implements the agreed improvements 1–3, following the [protocol investigation](protocol-findings-2026-10-22.md).
The product remains version **1.0.0** while preparing v1.1.0. No release, tag,
installed HACS component update, Home Assistant restart or pairing change was made.

## Implementation

1. Replace the fixed 15-second post-upload sleep with immediate graceful close and
   an awaited transport-completion signal. The five-second close deadline is a
   failure bound; it does not impose a minimum wait. A failed/stalled shutdown
   reports delivery failure; a stalled transport is aborted. The stop WebSocket
   reply waits for shutdown. A TV remains reserved while its connection drains.
   Cancellation, late startup and unload retain ownership of cleanup.
2. Decode server field 31 as session-close. A matching close stops forwarding,
   drops the partial unsent chunk and unregisters upload. Missing, stale and
   duplicate closes do not end another session. A close immediately following a
   server offer cannot be undone by a later client begin. The next owning client
   progress/stop receives `session_ended`; this is not recognition confirmation.
3. Use generated protobuf client/server voice schemas instead of handwritten
   production field tags and varint serialization. Preserve TLS, pairing,
   handshake and framing through androidtvremote2. Keep private hooks isolated in
   `protocol.py` and retain the **0.3.2** version gate: there is still no verified
   released upstream API that removes the adapter. Redact echoed remote errors,
   which can otherwise include client audio in debug logging.

The one-second pre-search startup policy remains unchanged. Backend close does
not push a microphone-stop event to the existing browser card, which buffers
recordings before uploading. No new recognition-success signal is asserted.

## Automated checks

- Python 3.14.2, Home Assistant 2026.10.2, androidtvremote2 0.3.2: **52 tests passed**,
  plus 8 parameterized subtests; **93%** overall statement coverage, including
  generated code. `protocol.py` has 100% statement coverage.
- Real upstream framing checks cover raw PCM alignment, signed/zero session IDs,
  audio configuration, handshake/voice-begin/ping behavior, server close matching,
  an early-close race, malformed messages and audio-echo privacy.
- Session and real HA WebSocket tests cover queued tail preservation, awaiting
  close, network failure, abort deadline, TV reservation while draining, cancelled
  waiters, unload, cancellation races and terminal error ownership.
- Frontend PCM, card and AudioWorklet tests and JavaScript syntax checks passed.
- Ruff lint/format, mypy, release metadata validation and `git diff --check` passed.
- Generated schema checked through the offline lab with protobuf **4.21.12** and
  **4.25.9**; the HA suite uses **7.36.2**. Compiler-only dependencies remain in a
  temporary environment; no new Home Assistant runtime dependency was added.

## Live checks of the production session

These tests imported the actual checkout's `VoiceSession` and adapter without
loading or replacing the installed HA integration. Existing paired credentials
were reused. Generic prerecorded fixtures were sent on dedicated connections;
recognition was reviewed from TV screenshots separately from transport counters.
The [sanitized trial metadata](protocol-lifecycle-trials-2026-10-22.json) contains
no host addresses, credentials, protocol session identifiers or audio.

| Trial | Scenario | Observed result |
|---|---|---|
| 35 | Short recording, burst submission | Correct transcript and time answer; close awaited in 22.3 ms. |
| 36 | Full 15-second / 480,000-byte recording, burst submission | Long transcript and final time answer; 198,336 bytes were buffered before final flush; close awaited in 86.6 ms. |
| 37 | Same full-length fixture, real-time pacing | TV close at 14.158 s from trial start stopped forwarding at 425,984 bytes; transport closed at 14.161 s. Final time answer observed. Remaining fixture bytes were not uploaded after TV close. |
| 38 | Cancel with a 100-byte unsent partial chunk | Zero bytes forwarded; no question transcript or answer observed; returned to Home; close awaited in 7.4 ms. |
| 39 | Fresh short recording after cancellation and TV-close cases | Correct transcript and time answer; close awaited in 17.7 ms. |

Long transcripts are ellipsized by the TV UI; the final answer establishes that
its last question arrived, not perfect recognition of every word. Measurements
are observations on this installation, not universal timing guarantees.

HA Browser was used to wake/reset the TV and restore its original **off** state,
verified as `Spento` after testing. Every test process closed its own connections.
The pre-existing mute and debugging settings were preserved.

## Release evidence limits

The subsequent installed dashboard / real-phone acceptance is recorded below.
Other manufacturers and Remote Service versions remain unverified. Upstream
adoption is still pending; the adapter must not be presented as an
unpatched-library solution. These limits remain part of the compatibility contract.

## Subsequent installation for phone acceptance

The owner later authorized installation of the unreleased test build. All 26
installed files now match the tested checkout, HA's configuration check passed,
and HA was fully restarted. Runtime diagnostics confirm the configured entry
and idle session state. See [phone setup](phone-validation-setup-2026-10-22.md)
and the [exact build manifest](phone-validation-build-2026-10-22.json). This
supersedes the earlier installed-component status above.

After receiving the phone validation checklist, the owner reported “everything
works” on 2026-10-22. Phone acceptance is recorded as passed for this installed
build on the existing TCL. This is owner-reported evidence; no extra hardware
or browser coverage is inferred. No release or tag was issued.
