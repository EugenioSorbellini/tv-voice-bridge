# Voice protocol research

These are the conclusions from live trials and receiver inspection that shaped the
bridge's voice wire format and its timing. Everything here was observed on **one TV**.
Treat counts as observations, not reliability rates. Raw per-trial metadata for the
2026-10-22 trials remains in the repository history, for example at commit `0b43e1a`.

## Summary

| Question | Answer on the tested TV | Production consequence |
| --- | --- | --- |
| What does the TV expect in client field 31? | Raw PCM bytes, not upstream's nested session/samples message | `client.py` sends raw audio through generated `voice.proto` schemas |
| Is 16 kHz required? | No. Raw 8 kHz works with the receiver defaults | 16 kHz kept for the browser pipeline; declared explicitly |
| Can the 1 s pre-request delay be removed or shortened? | No. Zero delay intermittently gets no voice-begin; 0.25–0.5 s can lose the start of speech | 1 s fixed delay kept |
| Is a long post-upload grace needed? | No. Graceful transport close delivers queued audio | v1.1.0 awaits close with a 5 s failure deadline |
| Does the TV signal when it stops listening? | Yes. Server field 31 carries a matching session-close | v1.1.0 stops forwarding and reports `session_ended` |

## Tested installation

| Item | Observed value |
| --- | --- |
| Manufacturer / reported model | TCL / Smart TV Pro (retail model unconfirmed) |
| Product / build | G08_4K_GB / tcl9618-user 14 UTT2.250416.001 AU02 release-keys |
| Android version / API / security patch | 14 / 34 / 2025-12-05 |
| Locale | it-IT |
| Remote Service | com.google.android.tv.remote.service 7.00.956317615 (2026-10-22), 7.00.999235495 (2026-10-24) |
| Assistant | com.google.android.katniss 7.55.87+964183260.01 |
| Home Assistant / library | 2026.10.2 / androidtvremote2 0.3.2 |

The handshake's `device_info.sw_version` reports the Remote Service version, not
the TV firmware.

## Method

Each trial used `tools/protocol_lab.py` on one dedicated remote connection with the
existing paired certificate, outside Home Assistant. ADB checked that the TV was
awake (`mWakefulness=Awake`), reset it to Home, and captured screenshots. ADB never
carried voice audio. Recognition was judged from the screenshots: a visible
transcript, and separately an assistant answer. Transport acceptance alone is not
recognition, because the TV accepts malformed audio without an error.

Fixtures were synthetic Italian speech with 0.3 s leading and 0.6 s trailing
silence. No personal speech was recorded.

| Fixture | Use | PCM SHA-256 |
| --- | --- | --- |
| "Dimmi che ore sono", 16 kHz, 3.516 s | Format, startup and grace trials | `92200d22acd0af2127cad6c21268e252093c6c464da7b685620b928844496f41` |
| Same, 8 kHz | Rate trials | `41313a404c3ae97091882e9b0b8cfb0b65d0ac766da5e637d851fa8dd6240c5d` |
| Continuous utterance ending in a time request, 16 kHz, 15 s | Full-length and close trials | `0ea947d5559fa185e50b948ae5fcd111e8de42eb1a218642f577ac31ed36db35` |
| TTS "Che ore sono?", 16 kHz, 2.124 s | 2026-10-24 startup trials | `2004e1968c2003a46bbc01e7a34357ae6f73dd2a2bca9fff2bbca0ea90883e5f` |

Unless stated otherwise: 1 s before requesting voice, 8192-byte chunks, burst
submission. Trial numbers without a date are from 2026-10-22. Its trials 01–03
used a robotic eSpeak fixture that never produced a working control and are
excluded.

## Wire format and rate

| Case | Trials | Recognized | Meaning |
| --- | --- | --- | --- |
| Raw 16 kHz, configured (production) | 04 | 1/1 | Positive control |
| Nested 16 kHz, configured | 06 | 1/1 | Corrupted input can still be recognized |
| Raw 8 kHz, configured | 07 | 1/1 | 16 kHz is optional |
| Raw 8 kHz, default configuration | 08, 11, 13 | 3/3 | Explicit audio fields are optional |
| Upstream: nested 8 kHz, default | 05, 09, 12 | 0/3 | Unchanged upstream was not recognized |
| Nested 8 kHz, configured | 10 | 0/1 | Declaring defaults does not fix nesting |

All ten trials were run interleaved and accepted every input byte with no remote error.

**Receiver implementation.** The active Remote Service APK (4,838,691 bytes,
SHA-256 `12b03f82d80eaefb2d7972e8af67ac90ea2466faecc76f2a9e417c4e17a9579b`) was read
without modification. Its protobuf metadata and voice handler show:

- Remote message field **30** is voice-begin; field **31** is **bytes**.
- The handler passes field 31's bytes to the decoder, and PCM mode returns them
  unchanged. There is no nested session/samples parsing.
- Voice-begin fields **1, 10, 11, 12** are session, rate, channel mask and format,
  with defaults **8000, 16, 2**.
- The path is `com/google/android/tv/remote/service/VoiceFeature$ClientMessageHandler`.
  No TCL-specific condition was found. Obfuscated classes in `classes2.dex`:
  `Lbzn;` (message), `Lcao;` (begin/config), `Lbup;` (handler), `Lbvb;` (PCM).

The factory Remote Service **6.4.746386949** (4,249,012 bytes, SHA-256
`494d1fa21edb13986aeb7be47a78ede7fd73503dbdf222ba0681e9cdc4246e6f`; classes
`Lbtr;`, `Lbur;`, `Lbou;`, `Lbpe;`) has the same schema, handler and defaults.
This points to a Google Remote Service behaviour rather than a TCL dialect. It
does not prove every vendor ships the same service.

**Why nesting is fragile.** androidtvremote2 0.3.2 defines field 31 as a message.
A message and a bytes field share the same wire type, so the TV accepts the packet
and plays the wrapper as sound. With 8192-byte chunks the wrapper was five bytes,
and an odd prefix shifts PCM16 sample alignment. The size depends on varints, so
five is not a protocol constant. An occasional correct transcript does not
validate the mismatched schema.

## Startup readiness

The bridge waits a fixed 1 s after connecting before requesting voice. Every
attempt to shorten it has failed on this TV.

| Startup | Trials | Voice-begin | Full phrase recognized |
| --- | --- | --- | --- |
| Fixed 1 s | 20; 2026-10-24: 01, 03, 05 | 4/4 | 4/4 |
| Zero delay | 19, 21, 23 | 0/3 | 0/3 |
| Poll `is_voice_enabled` (effectively zero) | 2026-10-24: 02, 04, 06, 07, 09, 11, 13, 15, 17 | 7/9 | 7/9 |
| Wait for initial app/IME callback | 29, 30, 31 | 2/3 | 2/3 |
| Fixed 0.5 s | 2026-10-24: 10, 14, 18 | 3/3 | 2/3 (10 heard only "sono") |
| Fixed 0.25 s | 22; 2026-10-24: 08, 12, 16 | 4/4 | 2/4 (08, 12 heard nothing) |

Trials 19–23 ran after a guard confirmed the TV was awake before and after. Earlier
failures 15–17 coincided with the TV dropping into standby and are inconclusive.

- `is_voice_enabled` is already true when `async_connect()` returns, because it
  comes from the feature handshake. Polling it therefore gives zero delay.
- Zero-delay failures time out before voice-begin with no audio accepted. They are
  loud: the user sees an error. When voice-begin did arrive at zero delay, it took
  0.10–0.21 s and the phrase was recognized.
- Short fixed delays fail quietly: the TV acknowledges and accepts all audio, but
  the start of speech is lost. The bridge cannot detect this.

This suggests two TV-side readiness stages, one gating voice-begin and one gating
audio capture, and no current signal exposes either. The handshake signals do not
help: SetActive (server field 2) arrived before the power message in failing trial
28, power (field 40) does not imply voice readiness, and the initial app report
(field 20) failed in trial 31. The lab keeps `--startup ime` and `--startup poll`
for further testing.

An untested option is to request voice immediately with a short voice-begin
timeout, falling back to the 1 s path. It needs trials covering what the TV does
after an abandoned request. With streaming upload, recording overlaps the delay,
so it only costs time when the button is released within about 1.2 s.

## Post-upload grace and transport shutdown

v1.0.0 kept the connection open for a fixed 15 s after sending audio.

- Trials 14, 24 and 25 recognized the phrase with zero delay after voice-begin and
  with 2 s and 0 s post-upload grace.
- Trial 33 sent the full 15 s fixture in a burst with **zero grace**: 338,874 bytes
  were still queued in the TLS transport at disconnect, and the final question was
  still answered. Upstream's `disconnect()` calls transport `close()`, which
  [flushes queued output before `connection_lost`](https://docs.python.org/3.14/library/asyncio-protocol.html#asyncio.BaseTransport.close);
  `abort()` would discard it.
- Trial 26's multi-sentence fixture was answered only for its first sentence,
  likely assistant endpointing. The continuous fixture fixed that: trials 27
  (burst) and 32 (real-time) answered its final question.

v1.1.0 therefore closes immediately and awaits `on_con_lost`, with a 5 s **failure
deadline** that aborts a stalled close and reports delivery failure. Closure is not
proof of recognition.

## TV voice-close

The receiver sends **server** field 31 with the matching voice-session ID and no
samples when it stops listening. Client field 31 is audio and client voice-end is
field 32, so the two directions need separate schemas. In real-time trials 32 and
34 it arrived at 14.2–14.4 s, before the client finished. It did not appear in short
burst trials, where the client had already ended. It is a stop-listening request,
not an acknowledgement of voice-end or assistant completion. Upstream does not
expose it.

## v1.1.0 production validation

These trials imported the checkout's real `VoiceSession` and adapter.

| Trial | Scenario | Result |
| --- | --- | --- |
| 35 | Short recording, burst | Transcript and answer; close awaited in 22.3 ms |
| 36 | Full 15 s / 480,000 bytes, burst | Final question answered; close awaited in 86.6 ms |
| 37 | Full length, real-time pacing | TV close at 14.158 s stopped forwarding at 425,984 bytes; final question answered |
| 38 | Cancel with an unsent partial chunk | Zero bytes forwarded; nothing transcribed |
| 39 | Fresh recording after the cancel and close cases | Transcript and answer |

Phone-to-TV acceptance through the dashboard card was then confirmed by the owner
on the same TV. The later streaming upload, which holds audio until submission
and forwards it as in trials 35–36, measured 163 ms from release to sent, against
910 ms for v1.1.0.

## Libraries and upstream

- [androidtvremote2 0.3.2](https://github.com/tronikos/androidtvremote2/blob/v0.3.2/src/androidtvremote2/remotemessage.proto)
  nests field 31 and lacks voice-begin fields 10–12. Its
  [voice PR](https://github.com/tronikos/androidtvremote2/pull/35) notes incomplete
  audio-configuration knowledge. 0.3.2 was the latest release when checked.
- [jkiddo/atvremote](https://github.com/jkiddo/atvremote/blob/main/pkg/v2/remote/protocol.go)
  and [LibreControl/google-tv](https://github.com/LibreControl/google-tv/blob/main/src/codec/remote.ts)
  also nest the payload, so switching to them would keep the mismatch.
- [Libremote protocol notes](https://github.com/sonalder-darlene/libremote-android-tv/blob/main/PROTOCOL.md)
  independently describe raw client voice payloads (static analysis of 7.00.999235495),
  but their client has no voice sender.
- Stack Overflow reports ([2025](https://stackoverflow.com/questions/79322816/voice-input-in-android-tv-remote-control/79447824),
  [2024](https://stackoverflow.com/questions/78438608/sending-voice-input-to-android-tv-using-android-tv-remote-control-v2))
  describe SEARCH → server begin → client begin → audio, and bytes payloads.

An upstream fix would need field 31 as bytes, explicit audio configuration for
non-default rates, and a voice-close callback. The bridge no longer waits for it:
its own client (`client.py`) implements these directly. Avoid model allowlists or
format fallbacks keyed on branding.

## Open questions

- Recognition on another vendor's TV or another Remote Service generation.
- A real readiness signal, or the immediate-request-with-fallback option above.
- Whether 8 kHz would be a better recording rate. That 8 kHz works is not evidence
  that it is better.

## Running the protocol lab

`tools/protocol_lab.py` prints an offline plan unless passed `--execute`. It has no
scanner, microphone capture, pairing flow or Home Assistant import. The `current`
case runs the production client and needs no extra package. The comparison cases
need `androidtvremote2==0.3.2`: `upstream` leaves the library unchanged and the
others are isolated experimental encodings. Trials before the client replaced the
adapter ran `current` through androidtvremote2 with the old adapter. Run one live trial at a time, with the TV owner's agreement, because it
opens the assistant on screen:

```sh
python tools/protocol_lab.py --case current --wav FIXTURE_16K.wav \
  --host TV_HOST --cert PAIRED_CERT --key PAIRED_KEY \
  --startup delay --ready-delay 1 --processing-grace 8 --execute
```

Keep fixtures, screenshots, hosts and pairing material out of Git. The JSON report
leaves `recognition` as `not_observed`: judge recognition from the screen.
