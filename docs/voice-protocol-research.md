# Voice protocol research

Live trials and receiver inspection behind the bridge's voice client, all run on one TV between 2026-10-22 and 2026-10-25. Counts are observations, not reliability rates. Per-trial details, fixture hashes and APK hashes remain in Git history (for example commit `0b43e1a`).

## Tested hardware

| Item | Value |
| --- | --- |
| TV | TCL Smart TV Pro (product G08_4K_GB), Android 14 / API 34 |
| Remote Service | com.google.android.tv.remote.service 7.00.956317615, then 7.00.999235495 |
| Assistant | com.google.android.katniss 7.55.87, locale it-IT |
| Home Assistant | 2026.10.2 with androidtvremote2 0.3.2; 2026.10.3 with the bridge's client |

Trials ran `tools/protocol_lab.py` (see `--help`) on a dedicated connection with the existing core pairing. Synthetic Italian speech (TTS, 1–15 s) was sent, and recognition was judged from the TV screen, since the TV accepts even malformed audio without an error.

## What was tested

| Area | Result on the tested TV |
| --- | --- |
| Audio format | Raw PCM16 in field 31 recognized at 16 kHz and 8 kHz (5/5); upstream's nested message at 8 kHz never recognized (0/4) |
| Startup delay | 1 s before requesting voice: 4/4. Zero delay never got voice-begin (0/3); 0.25–0.5 s and readiness polling lost speech or failed intermittently |
| Delivery | Graceful close flushes queued audio: a full 15 s burst closed with zero wait was still answered |
| TV voice-close | Server field 31 with the session ID arrives when the TV stops listening (about 14.2 s into real-time sends) |
| Production path | Short and full-length recordings, a TV close mid-send, cancel (nothing forwarded) and a fresh recording after cancel all behaved as specified |
| Bridge client | Through the HA WebSocket path: TLS 1.3 handshake, 2.7 s and 1.2 s phrases forwarded in full and answered |
| Phone | Recording from the dashboard card on a phone confirmed by the owner |

## Why androidtvremote2 0.3.2 could not be used as is

- **Wrong audio field type.** It defines client field 31 as a nested session/samples message. The Remote Service APK defines it as `bytes` and passes it unchanged to the PCM decoder. Both share a wire type, so the TV accepts the packet and plays the wrapper as sound: a five-byte prefix per 8192-byte chunk, which also shifts PCM16 sample alignment. Unchanged upstream was not recognized in any trial.
- **No audio configuration.** It lacks voice-begin fields 10–12 (rate, channel mask, format), so only the receiver defaults (8 kHz mono PCM16) are reachable.
- **No voice-close.** It does not expose the TV's stop-listening message.
- Other open-source clients ([jkiddo/atvremote](https://github.com/jkiddo/atvremote/blob/main/pkg/v2/remote/protocol.go), [LibreControl/google-tv](https://github.com/LibreControl/google-tv/blob/main/src/codec/remote.ts)) nest the payload the same way.

## Why a custom client

Patching the library meant replacing its internals, which any HA release bumping androidtvremote2 could break. The bridge's own voice-only client (`client.py`) instead:

- sends field 31 as raw bytes and declares 16 kHz explicitly, with separate client and server schemas in `voice.proto`;
- reacts to the TV's voice-close;
- reuses the core integration's pairing but owns its connection, so HA's androidtvremote2 version does not affect voice.

Its handshake replies, identity and feature flags copy 0.3.2, the client used for the format and timing trials. An upstream fix would need the same three changes.

## Compatibility with other Google TVs

- **Likely shared:** the audio format. The receiver is Google's Remote Service, not TCL code. The factory 6.4.746386949 and current 7.00 versions have the same schema, handler and defaults, with no vendor-specific branch, and [independent notes](https://github.com/sonalder-darlene/libremote-android-tv/blob/main/PROTOCOL.md) on 7.00.999235495 describe the same raw payload.
- **Assumed, not verified:** that other vendors ship this service unchanged, and that the 1 s startup delay suffices elsewhere. It is tuned to this TV; a shorter delay failed silently here.
- **Not assumed:** recognition quality, which depends on the assistant, language and account settings.
- Avoid model allowlists or format fallbacks keyed on branding. Report new devices with model and Remote Service version.
