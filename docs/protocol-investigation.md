# Protocol investigation for v1.1.0

Prepared 2026-10-22. The owner authorized live testing and approved the existing
ADB key. The first investigation is recorded in
[the findings report](protocol-findings-2026-10-22.md). This document preserves
the experimental plan; unchecked completion criteria below remain release gates.

No incremental releases, tags, HACS updates or changes to the running integration.
The target is one v1.1.0 release after the investigation and implementation are
validated. The existing product version remains 1.0.0 during preparation.

## Questions and evidence limits

1. Which parts of the current adapter are necessary on this particular TV?
2. Do those requirements follow a Remote Service/assistant version, a firmware
   family, a manufacturer, or a generally shared Google TV implementation?
3. Can an existing maintained library deliver the working format through a public
   API, or can the current upstream library be corrected/extended?

A single TV cannot establish that a workaround is common to Google TV. A failure
of upstream also does not by itself prove that the nested payload is the cause:
audio configuration, rate, pacing and timing have to be separated. Widespread
behavior does not guarantee an existing library implements it correctly.

Maintain three evidence levels: observed on this TV; independently reproduced on
another device or established in the receiver implementation; untested hypothesis.
Do not describe any untested case as supported or publish a model allowlist based
only on the Google TV label.

## Inventory obtained without contacting the TV

The existing HA configuration identifies one TV Voice Bridge entry bound to
`remote.tv_salotto`. HA's device registry calls it TCL **Smart TV Pro**; firmware
and hardware versions are empty. This is a generic reported model, not a confirmed
retail model. HA is 2026.10.2. The running component is a HACS-owned installation;
the development checkout is separate.

At the start of a live window, record the retail model, Android TV OS version,
build/firmware, Android TV Remote Service package version/code, assistant package
and version, locale, network path, library version and test commit. The remote
handshake's `device_info.sw_version` is populated from its advertised
`app_version`; do not label it TV firmware without checking.

Use the paired certificate and key by file path, without printing, copying into
Git, replacing or regenerating them. Local test output must omit host addresses,
pairing material, audio bytes and session identifiers. Record only the fixture
digest, settings, durations, byte counts and relevant reply names/error counts.

## Live observation setup

Use one dedicated test connection at a time, outside HA, so variants do not require
HA restarts, edits to HACS-owned files or prototype releases. Preserve the current
working installation as the control. End each session and close every transport.

Prefer ADB for objective observation when the owner enables debugging during the
live window: read selected build properties and package versions, and inspect the
assistant's visible transcript/result using UI hierarchy or a screenshot. Avoid
broad dumps of unrelated app state, full logcat or audio-bearing protocol logs.
Normal TLS captures are encrypted and cannot establish the voice payload shape.

ADB is diagnostic only; production microphone delivery must remain independent
of debugging. If its UI is not observable through ADB, use the owner's explicit
transcript/result observations and mark missing observations as inconclusive.

Use one short, known Italian phrase such as **Dimmi che ore sono**, at the TV assistant's
configured language. Prepare matching 8 kHz and 16 kHz mono PCM16 WAVs from the
same clean master recording with a verified offline converter. Keep those fixtures
outside Git. Do not count a synthetic tone/silence as a recognition test.

For every trial record handshake success, assistant activation, TV error/close
events, input bytes accepted by the transport, displayed transcript, assistant
response, and time to result. Transport acceptance alone is not recognition.
An observation window ending before a result is an inconclusive trial, rather
than an automatic failure. Record any delayed result.

## Stage 1: isolate the wire format and rate

First confirm the current baseline recognizes the known phrase. Run upstream
as a comparison, then use the following matrix to explain any difference. Start
with the same one-second readiness delay, 15-second processing grace, 8192-byte
chunks, burst upload, IME enabled and identical assistant/app state for every case.

| Runner case | PCM rate | Payload in field 31 | Voice-begin audio config |
| --- | --- | --- | --- |
| `current` | 16000 | Raw | Fields 10/11/12; actual production adapter |
| `nested-16k` | 16000 | Upstream nested session/samples | Fields 10/11/12 |
| `raw-8k` | 8000 | Raw | Fields 10/11/12 |
| `nested-8k` | 8000 | Upstream nested session/samples | Fields 10/11/12 |
| `upstream` | 8000 | Upstream nested session/samples | Session ID only; upstream sender unchanged |
| `raw-8k-default` | 8000 | Raw | Session ID only |

Useful contrasts: `current` versus `nested-16k` changes payload only;
`raw-8k` versus `nested-8k` repeats that contrast at 8 kHz;
`nested-8k` versus `upstream` tests explicit audio configuration;
`raw-8k` versus `raw-8k-default` repeats that contrast with raw payloads.
Compare rates only within the same payload/configuration family. Configured-rate
tests change the audio and its matching declaration together.

Repeat the decisive promising/failed contrasts at least three times and interleave a working
baseline before/after them. Reset to the same idle assistant/app state and wait
for the previous session to settle. Record the actual order. This distinguishes
format effects from a transient assistant/network failure or a stale session.

## Stage 2: isolate timing and pacing

With one known working format fixed, compare readiness delays 1 / 0.25 / 0 seconds;
processing grace 15 / 5 / 2 / 0 seconds; and burst versus real-time upload. Change
one setting per contrast and repeat. Extend only the observation window if the
assistant is still processing. Compare each experiment to the working control.

Distinguish the delay before requesting voice from the delay between the TV's
voice-begin reply and the first audio chunk (`--audio-delay`). Browser recording
can introduce the latter naturally; a pre-recorded upload does not. Do not infer
that either delay is necessary from the other's result.

Zero grace may drop bytes still buffered in the transport: a failure would not
alone establish that the assistant needs a long-lived connection. Distinguish
delivery completion from assistant processing before choosing a smaller value.

## Stage 3: decide how widely the result applies

If needed, inspect the installed Remote Service's parsing behavior after obtaining
its exact package version. Receiver code can establish whether field 31 is raw
bytes for that implementation. Compare the official Google TV phone app as another
working client, without assuming encrypted packet lengths reveal protobuf fields.

For a broader claim, obtain the same trial record from at least one other vendor's
Google TV with its Remote Service version identified, ideally plus a different
service generation. Source-code identity across devices supports an inference
about parsing, but does not prove end-to-end recognition on all those devices.
If no second device/equivalent evidence is available, report that limitation and
keep support claims restricted to the tested installation.

## Library investigation and current leads

These are candidates and source observations, not hardware compatibility claims:

- [androidtvremote2 0.3.2 schema](https://github.com/tronikos/androidtvremote2/blob/v0.3.2/src/androidtvremote2/remotemessage.proto):
  nested payload, 8 kHz default, and no fields 10/11/12 in its voice-begin schema.
  Its [voice-support PR](https://github.com/tronikos/androidtvremote2/pull/35)
  documents incomplete audio-configuration knowledge and Shield-based chunk limits.
  The [release list](https://github.com/tronikos/androidtvremote2/releases) still
  lists 0.3.2 as latest when checked on 2026-10-22.
- [jkiddo/atvremote](https://pkg.go.dev/github.com/jkiddo/atvremote/pkg/v2/remote)
  describes itself as a Go port of androidtvremote2. Its inspected
  [voice sender](https://github.com/jkiddo/atvremote/blob/main/pkg/v2/remote/protocol.go)
  constructs `RemoteVoicePayload{SessionId, Samples}` and its
  [schema](https://github.com/jkiddo/atvremote/blob/main/pkg/v2/proto/remotemessage.proto)
  nests that message in field 31. It therefore does not directly replace our raw
  field-31 behavior. Shared assumptions are not independent confirmation.
- [LibreControl/google-tv](https://github.com/LibreControl/google-tv) documents
  8 kHz PCM and the same chunk-size bounds. Inspection of its
  [serializer](https://github.com/LibreControl/google-tv/blob/main/src/codec/remote.ts)
  confirms field 31 contains an encoded message with session ID field 1 and samples
  field 2. Its phrase “raw PCM” describes uncompressed audio, not a raw protobuf
  field 31. This is not a direct replacement for our current wire format either.
- [harimoradiya/androidtvremote](https://github.com/harimoradiya/androidtvremote)
  contains Android protocol sources worth checking, but is an application, not
  a demonstrated Python/HA replacement.

The two alternative serializers above were inspected on 2026-10-22. This narrow
comparison has not identified an existing implementation of our exact format;
it is not an exhaustive finding that no such library exists.

Evaluate byte layout, supported configuration/rates, lifecycle, audio logging,
maintenance, license, runtime requirements, and public API before adopting a
candidate. A Go/Android/Node implementation may be useful protocol evidence while
being an unsuitable HA runtime dependency. Prefer a verified upstream change or
supported extension point over replacing one private patch with another.

## Runner and offline verification

`tools/protocol_lab.py` prints an offline plan unless explicitly passed `--execute`.
It has no scanner, microphone capture, pairing flow, HA import or release operation.
The `current` case loads the production adapter directly; `upstream` leaves its
sender unchanged. Other cases are deliberately isolated experimental encodings.

Preparation environment (temporary; no HA dependency):

```sh
python3 -m venv /tmp/tv-voice-protocol-lab
/tmp/tv-voice-protocol-lab/bin/python -m pip install androidtvremote2==0.3.2
/tmp/tv-voice-protocol-lab/bin/python tools/protocol_lab.py --case current
/tmp/tv-voice-protocol-lab/bin/python -m unittest discover -s tests -p test_protocol_lab.py
```

Only after the owner's start signal, run one selected trial with the correct
fixture and the existing paired credentials. Paths and host are supplied locally,
never committed. A live command opens the TV assistant:

```sh
/tmp/tv-voice-protocol-lab/bin/python tools/protocol_lab.py \
  --case current --wav /tmp/tv-voice-fixtures/question-16k.wav \
  --host TV_HOST --cert EXISTING_CERT_PATH --key EXISTING_KEY_PATH --execute
```

The JSON report intentionally leaves `recognition` as `not_observed`: supplement
it with the separately observed transcript/result. Input counts do not include
silence padding added internally by the upstream stream, and do not prove delivery.

## Completion criteria before v1.1.0

- Reproducible results identify the minimum working format and timing on this TV.
- Each generalization is backed by identified receiver code or independent device
  evidence; remaining uncertainties appear in compatibility documentation.
- Any chosen library/profile/adapter has matching packet regression tests and
  real recognition evidence, including the full 15-second path and repeated use.
- Cancellation, deadlines, permissions, privacy and integration unload still pass;
  real phone/dashboard acceptance is repeated after the final implementation.
- Temporary test connections/debug settings are cleaned up, and the existing HA
  configuration is preserved. Incremental experiments remain unreleased.

## Unreleased implementation follow-up

The agreed improvements 1–3 are implemented in the checkout and validated in
[the lifecycle report](protocol-lifecycle-validation-2026-10-22.md). The installed
component remains unchanged, and the real-phone/dashboard release gate above is
still open. The historical lab's configurable grace delay remains an experiment
parameter; production submission now awaits graceful transport shutdown.
