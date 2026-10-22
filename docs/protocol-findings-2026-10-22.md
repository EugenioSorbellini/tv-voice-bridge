# Remote voice investigation — 2026-10-22

## Conclusion and scope

The raw field-31 payload matches the implementation in the installed **Google
Android TV Remote Service**, rather than a discovered TCL-specific branch. This
supports a service-implementation compatibility explanation. It does **not**
establish recognition compatibility with every Google TV or Android TV device:
only one physical TV was available, and a second vendor was not tested.

The existing adapter combines two separate choices. Removing the nested payload
wrapper corrects the receiver's audio input. Declaring 16 kHz enables the bridge's
chosen recording rate, but **16 kHz itself is not required**: raw 8 kHz also works
with the receiver's default configuration. “Google TV requires our TCL audio
settings” would therefore be an unsupported explanation.

This investigation changes diagnostic tools and documentation. The running HA
integration, its dependencies and release metadata were preserved. It is not
v1.1.0 release acceptance.

## Tested installation

| Item | Observed value |
| --- | --- |
| Manufacturer / reported model | TCL / Smart TV Pro (retail model unconfirmed) |
| Product | G08_4K_GB |
| Android version / API | 14 / 34 |
| Build | tcl9618-user 14 UTT2.250416.001 AU02 release-keys |
| Security patch | 2025-12-05 |
| Locale | it-IT |
| Active Remote Service | com.google.android.tv.remote.service 7.00.956317615, code 95855578 |
| Active assistant | com.google.android.katniss 7.55.87+964183260.01 |
| Active Google TV launcher | 1.0.994451607 |
| Home Assistant / Python remote library | 2026.10.2 / androidtvremote2 0.3.2 |
| Product baseline | commit 588424d; product version 1.0.0 |

The handshake's `sw_version` matches the Remote Service version, not the TV
firmware. Package inspection also listed factory versions; these were not
downgraded or substituted for the active packages.

## Method and recognition evidence

The owner authorized a live window and approved the existing ADB key. Home
Assistant's browser remote was used to power on and reset the TV to Home between
trials. An isolated Python process used the existing paired TLS certificate and
one dedicated remote connection per trial. ADB supplied package/build inventory
and screenshots; it did not carry production voice audio.

The successful fixture was natural Italian synthetic speech, **“Dimmi che ore
sono”**, converted from one master to mono signed PCM16 at 8 and 16 kHz. Both WAVs
contain 0.3 seconds of leading silence and 0.6 seconds of trailing silence and last
3.516 seconds. No personal speech or microphone recording was collected.

| Rate | PCM input bytes | SHA-256 of PCM input |
| --- | --- | --- |
| 8000 | 56256 | 41313a404c3ae97091882e9b0b8cfb0b65d0ac766da5e637d851fa8dd6240c5d |
| 16000 | 112512 | 92200d22acd0af2127cad6c21268e252093c6c464da7b685620b928844496f41 |

Unless explicitly stated otherwise, trials use a one-second delay before
requesting voice, a two-second delay after the voice-begin reply before first
audio, 8192-byte input chunks, burst submission, and 15 seconds before connection
close. Smaller final chunks receive upstream's minimum-size padding. The initial
format matrix received voice-begin replies and accepted all input locally; later
startup failures are reported separately. Transport acceptance alone is not a
recognition result.

Screenshots were requested at 1.5, 3, 6 and 10 seconds from trial start. Transfer
can take several seconds, so JSON capture completion times are **not exact screen
capture or recognition times**. The format-matrix successes below visibly contain
the expected transcript and a time answer. Later trials distinguish transcription
from an assistant answer in their observation metadata. An unrecognized trial means no
transcript/result was seen in those captures, not a quantified recognition rate
for every possible recording or proof that the service can never answer later.

The first three trials used a robotic eSpeak fixture and did not establish a
working control. They are excluded from format comparisons; natural speech
established the first positive control at trial 04.

The ordered [trial metadata](protocol-trials-2026-10-22.json) contains input
digests, settings, transport events and separately reviewed recognition outcomes.
Screenshot digests identify the retained local observations; screenshots, audio,
network addresses, credentials and session identifiers are excluded from Git.

| Case | Trial IDs | Recognition observed | Meaning |
| --- | --- | --- | --- |
| Current: raw 16 kHz, configured | 04 | 1/1 | Production adapter positive control |
| Nested 16 kHz, configured | 06 | 1/1 | Corrupted input can still be recognized |
| Raw 8 kHz, configured | 07 | 1/1 | 16 kHz is optional |
| Raw 8 kHz, default configuration | 08, 11, 13 | 3/3 | Explicit default audio fields are optional |
| Upstream: nested 8 kHz, default configuration | 05, 09, 12 | 0/3 | No recognition seen with unchanged upstream |
| Nested 8 kHz, configured | 10 | 0/1 | Declaring defaults does not fix this trial |

The actual chronological order is 04 through 13, not table order. The repeated
raw/default and upstream trials were interleaved. Counts describe these fixtures
and conditions only; they are not statistical estimates of general reliability.
All ten trials accepted all input bytes locally and emitted no observed remote
error. This demonstrates why transport success is an insufficient acceptance test.

Trial 14 repeated the production-format control with **zero delay after the
voice-begin reply** and again displayed the complete phrase and time answer.
Thus the two-second delay used to stabilize the initial matrix is not a demonstrated
requirement. This is one timing observation, not a measured safe lower bound for
every assistant state or a justification to change production timing constants.

Trials 15 (zero pre-search delay) and 16 (one-second pre-search delay) both timed
out waiting for voice-begin, before accepting any audio. Home Assistant subsequently
showed the TV off, and trial 16's final screenshot was black. Their power/session
state was not controlled sufficiently to attribute the failures to delay length.
Both are retained in the metadata as **inconclusive timing observations**. The
TV was explicitly powered on again for a control; no production delay was
changed.

Trial 17's attempted recovery still produced a black screen and no voice-begin.
ADB then reported `mWakefulness=Asleep` and `mLastSleepReason=screenless_mode`.
Using the remote power control restored a visibly awake Home screen; trial 18
then recognized the phrase and answered. No cause is assigned to the intervening
standby transition. The owner's subsequent pause was respected, with no live
test process running while the TV was in use.

After the owner resumed, a guard checked `mWakefulness=Awake` before every further
trial and recorded power state afterwards. Trials 19, 21 and 23, all with zero
pre-search delay, timed out waiting for voice-begin, with no audio accepted and
the TV awake before and after. Trial 20 with one second reached the full expected
transcript (no answer observed); trial 22 with 0.25 seconds reached both transcript
and time answer. These support a startup-readiness race hypothesis. They do not
prove a universal minimum delay or identify which asynchronous initialization
step is responsible. The production one-second policy is retained.

Trials 24 and 25 recognized the short question and answered with post-upload
graces of two seconds and zero seconds respectively. The local TLS write buffer
reported zero queued bytes at voice-end and before disconnect in both. These
observations do not establish that a 15-second grace is required for short
commands. They are single trials per setting, not a replacement timing policy.

The first 15-second fixture (trial 26) contained multiple sentences. The TV
transcribed and answered only the first sentence. All 480000 input bytes were
accepted locally, but that does **not** prove recognition of the end of the
recording. At voice-end 330610 bytes remained in the local TLS write buffer;
that buffer drained to zero during the 15-second grace. Assistant endpointing
at the first sentence is a hypothesis, not a diagnosed transport failure. A
continuous utterance with its question at the end was prepared to distinguish
these cases.

The continuous fixture contains 12.816 seconds of speech, preceded by 0.3 seconds
of silence and padded to exactly 15 seconds (480000 PCM bytes at 16 kHz). Its PCM
SHA-256 is `0ea947d5559fa185e50b948ae5fcd111e8de42eb1a218642f577ac31ed36db35`.
Its single utterance asks the TV to verify delivery through the end of the phrase,
then asks the time. Trial 27 (burst, 15-second grace) displayed the long leading
transcript and a current-time answer corresponding to the final request. The UI
ellipsizes the long transcript, so an exact word-for-word transcript score is not
claimed. Trial 32 repeated this with real-time pacing and again answered the final
request. This verifies the long fixture through the diagnostic connection, not
the browser microphone/HA websocket path.

Trial 32's control trace received server field 31 at 14.202 seconds, before the
client's scheduled voice-end at roughly 16.1 seconds. This agrees with the
receiver's audio-close request callback. No server field 31 appeared in short
burst traces 29/30, where the client had already ended its audio. Therefore it is
a useful candidate for stopping a live stream on TV request, **not a demonstrated
universal acknowledgement of client voice-end or assistant completion**. The
upstream handler does not currently expose it as a close notification.

Trial 34 repeated the real-time fixture with zero processing grace. The server's
field-31 message carried the matching voice-session identifier and no samples,
received at 14.425 seconds on the runner's clock. The final question was answered.
This confirms the direction-specific close event on this installation; no
session identifier or audio payload was retained in the diagnostic report.

Trial 33 repeated the continuous burst fixture with **zero processing grace** and
again displayed the long transcript and answered the final time request. At
disconnect 338874 bytes were still queued in the TLS transport, so “buffer empty
before close” was not a prerequisite in this test. The upstream disconnect calls
transport `close()`, not `abort()`; the observation process kept the event loop
running after that call, as HA's event loop would remain running. This successful
trial supports graceful transport shutdown as an alternative to a fixed wait;
it does not prove arbitrary loop termination or abort would deliver buffered audio.

[Python's transport contract](https://docs.python.org/3.14/library/asyncio-protocol.html#asyncio.BaseTransport.close)
specifies that `close()` flushes queued output asynchronously, then invokes
`connection_lost`; `abort()` discards queued output. A future cleanup change
should await graceful-close completion with a maximum failure deadline rather
than treating a fixed sleep as proof of delivery. Transport closure still is not
proof of speech recognition. Production's 15-second grace remains unchanged in
this investigation.

## Receiver implementation evidence

The active Remote Service APK was read from this TV without modifying it.
SHA-256: `12b03f82d80eaefb2d7972e8af67ac90ea2466faecc76f2a9e417c4e17a9579b`
(4,838,691 bytes). APKs and disassembly remain outside this repository.

Inspection of its protobuf metadata and voice handler establishes:

- Remote message field **30** is a voice-begin message; field **31** is **bytes**.
- The voice handler extracts field 31 as a ByteString and passes its byte array
  to the selected decoder. In PCM mode the decoder returns that array unchanged.
  There is no nested session/samples parsing on this path.
- Voice-begin fields **1, 10, 11, 12** represent session, rate, channel configuration
  and audio format. Defaults are **8000, 16, 2** respectively for the audio fields.
- The examined voice path is named
  `com/google/android/tv/remote/service/VoiceFeature$ClientMessageHandler` in the
  app's own logging metadata. No TCL condition was found in that parsing path.

For reproducibility against this exact APK, the obfuscated classes in
`classes2.dex` are `Lbzn;` (remote message), `Lcao;` (begin/config), `Lbup;`
(handler), and `Lbvb;` (PCM pass-through). These names are version-specific.

An offline comparison of the TV's factory Google Remote Service
**6.4.746386949** found the same field-31 bytes schema, PCM pass-through handler,
and 8000/16/2 audio defaults. Its APK is 4,249,012 bytes, SHA-256
`494d1fa21edb13986aeb7be47a78ede7fd73503dbdf222ba0681e9cdc4246e6f`.
Its corresponding classes are `Lbtr;`, `Lbur;`, `Lbou;`, and `Lbpe;`.
The factory APK was read without activating it or downgrading the installed
service. This establishes consistency across two Google service versions on
this TV; it is not a second-device recognition test and does not date when this
wire format first appeared.

This is evidence about the installed Google package's implementation. It is not
a claim that Google publishes or guarantees this protocol, that the APK is
identical on every manufacturer, or that other service generations behave the
same way.

## Why the nested format is fragile even if speech sometimes works

[androidtvremote2's 0.3.2 schema](https://github.com/tronikos/androidtvremote2/blob/v0.3.2/src/androidtvremote2/remotemessage.proto)
defines field 31 as a message containing session ID and samples. Both a protobuf
message and a bytes field use the same outer wire type, so the TV can accept the
packet without a protocol error while interpreting the inner metadata as sound.

The diagnostic run records the upstream source message's wrapper **length only**,
never the session ID or audio. Raw cases discard that wrapper before transmission;
the reported source-wrapper length is not an on-wire prefix for those cases.
With the observed sessions and 8192-byte blocks the nested wrapper was
five bytes. An odd-length prefix changes PCM16 sample alignment. Wrapper size
depends on varint values and chunk lengths; five bytes is not a universal
protocol constant. An occasional correct transcript is weaker evidence than the
actual receiving parser and does not validate a mismatched schema.

The bridge's own fragility is a separate maintenance problem: it accesses
`_remote_message_protocol` and replaces `_send_message`, serializes protobuf
fields by hand, and relies on the library's transport and voice lifecycle.
Pinning and regression checks reduce this risk but do not create a supported
extension API. The workaround addresses a protocol mismatch; there is no
evidence that it encodes a TCL model-specific audio dialect.

## Existing libraries and the implementation direction

### Online documentation and hook investigation

The [original Aymkdn walkthrough](https://github.com/Aymkdn/assistant-freebox-cloud/wiki/Google-TV-(aka-Android-TV)-Remote-Control-(v2))
describes configuration, activation, state notifications and keepalive, but has
no voice section. The upstream voice PR explicitly records incomplete knowledge
of audio configuration, so its schema is not a complete protocol specification.

The newer [Libremote protocol notes](https://github.com/sonalder-darlene/libremote-android-tv/blob/main/PROTOCOL.md)
independently describe raw client-to-TV voice payloads and separate the two wire
directions. Their static analysis uses Google Remote Service 7.00.999235495;
their reported live emulator tests cover non-voice operations on 5.99.551144881.
Those tests are not independent end-to-end voice confirmation. Its
[client](https://github.com/sonalder-darlene/libremote-android-tv/blob/main/protocol/src/main/kotlin/app/libremotetvservice/protocol/RemoteConnection.kt)
exposes `Listener.onReady` on SetActive, but its default feature set excludes
voice and the inspected client has no voice sender. It is useful protocol evidence,
not a demonstrated voice-library replacement. The notes' brief “start / ready”
label for server voice fields 30/31 needs checking against actual handler semantics.

An [independent app author's report](https://www.reddit.com/r/SideProject/comments/1vo2ra7/i_reverseengineered_googles_android_tv_remote/)
also describes bare audio bytes on Google TV. This is supporting testimony; its
source and per-device voice results are not available for verification here.

The relevant signals are distinct:

- **SetActive (server field 2):** feature activation handshake. In trace trial 28
  it arrived *before* the power message that releases upstream `async_connect`.
  Merely waiting for it again would not explain or cure that zero-delay failure.
- **Power (server field 40):** upstream's connection-return trigger. Power state
  does not itself prove that voice-trigger injection is ready.
- **Initial IME/app report (server field 20):** arrived just after connection
  return in trial 28. The public `add_current_app_updated_callback` can await this
  notification without a fixed sleep. It is being evaluated as a startup barrier,
  not assumed to be an audio-readiness contract.
- **Voice-begin (server field 30):** already awaited by `start_voice` before the
  bridge sends audio; it is not replaced by the one-second pre-search delay.
- **Server voice-close (server field 31):** the installed receiver's close-session
  callback sends a nested session identifier here. Client field 31, by contrast,
  is audio bytes, and client voice-end is field 32. Upstream's shared-direction
  schema/handler does not expose a corresponding close callback. Its occurrence
  and meaning for cleanup must be verified live before replacing processing grace.

Fixed readiness sleeps and maximum failure deadlines are different concerns.
Even an event-driven implementation needs bounded waits and cancellation when a
TV never sends the expected signal. The existing version gate stays in place.

Trials 29–31 awaited the public initial-app callback, then requested voice with
no fixed sleep. Trials 29 and 30 recognized the phrase and answered; trial 31
timed out before voice-begin despite receiving the callback. This candidate is
**not a reliable readiness replacement** on the available evidence. It is exposed
as `--startup ime` in the diagnostic runner for further testing only; production
keeps its existing startup policy. No evidence supports using the power callback
as voice readiness, and SetActive alone had already occurred in failing trial 28.

The [2025 firsthand voice implementation answer](https://stackoverflow.com/questions/79322816/voice-input-in-android-tv-remote-control/79447824)
describes SEARCH → server begin → client begin → audio. The
[2024 firsthand payload discussion](https://stackoverflow.com/questions/78438608/sending-voice-input-to-android-tv-using-android-tv-remote-control-v2)
confirms bytes payloads. These are interoperability reports with incomplete device
and version details, not normative specifications or proof of universal support.

The checked [release list](https://github.com/tronikos/androidtvremote2/releases)
still lists androidtvremote2 0.3.2 as latest. Its
[voice implementation discussion](https://github.com/tronikos/androidtvremote2/pull/35)
describes incomplete configuration knowledge. The inspected alternatives also
serialize the nested payload:

- [jkiddo/atvremote voice sender](https://github.com/jkiddo/atvremote/blob/main/pkg/v2/remote/protocol.go)
  uses `RemoteVoicePayload{SessionId, Samples}`.
- [LibreControl/google-tv serializer](https://github.com/LibreControl/google-tv/blob/main/src/codec/remote.ts)
  wraps session field 1 and audio field 2 inside field 31. Its “raw PCM” description
  refers to uncompressed sound, not the absence of that wrapper.

These are source comparisons, not live tests of those libraries. They do not
identify a verified drop-in replacement, and are not an exhaustive claim that
none exists. Switching to one of these encoders would retain the mismatch.

The preferred correction is a supported upstream sender/schema matching the
receiver: field 31 as audio bytes and explicit audio configuration when choosing
a non-default rate. Preserve the current isolated adapter until such an API is
available and verified. Avoid a TCL model allowlist or automatic format fallback
based on branding. Retain 16 kHz for the current browser audio pipeline unless
quality/latency measurements justify changing it; 8 kHz working is not evidence
that it is the better recording choice.

## Remaining v1.1.0 acceptance

This investigation answers the format/rate hypothesis on one installation.
Cross-vendor recognition, broader timing/pacing conditions, and real phone
microphone use through the final dashboard implementation (including its full
15-second path) remain separate acceptance work. The diagnostic connection's
continuous 15-second burst and real-time paths have been observed successfully.
Do not treat limited timing trials as universal safe limits. Any upstream/library
change must pass packet, lifecycle,
cancellation, privacy and HA integration checks before the single planned release.

## Investigation status

The evidence file contains 31 reviewed trials (04–34), including failures and
inconclusive power-state cases. The protocol lab's eight offline checks, repository
lint/format checks, and release metadata contract passed. Product version is
still 1.0.0. Production runtime changes in this checkout are limited to a corrected
module docstring; all experimental behavior lives in diagnostic tooling. No
release, push, TV package installation, downgrade, HA restart, or HACS-owned
component edit was performed for these experiments.
