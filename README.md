# TV Voice Bridge

Use the microphone on your phone, tablet, or browser to speak to an already-paired Android TV's voice assistant from a Home Assistant dashboard.

Hold the microphone button to record and release it to send. Recording starts while the TV connects. If you release before the connection is ready, the recording waits in memory and is sent once connected. Capture stops at 15 seconds; upload time has separate limits. A toggle mode and assistive activation are also available.

## Requirements and compatibility

- Home Assistant **2026.10.2 or later**, with the **Android TV Remote** integration already configured and paired.
- The currently supported protocol library is **androidtvremote2 0.3.2**, supplied by Home Assistant. Other versions are rejected explicitly until tested. A later HA release that changes this library may need a TV Voice Bridge update.
- HTTPS (or a secure localhost context), a microphone, and a browser supporting AudioWorklet. Browser microphone permission is requested only when recording is deliberately started.
- A TV that advertises voice support. Speech recognition also depends on its installed assistant, network access, language and account settings.

Real speech delivery has been verified on one TCL installation. Other Android TV models are **unverified**. The dedicated protocol adapter and its limitations are described in [Compatibility](docs/compatibility.md).

## Installation with HACS

1. In HACS, add `https://github.com/EugenioSorbellini/tv-voice-bridge` as a **custom repository**, category **Integration**.
2. Download TV Voice Bridge and restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → TV Voice Bridge** and select an already-paired Android TV remote. Add one integration entry per TV.
4. Add **TV Voice Bridge** to a dashboard using the card picker, or use the YAML below.

The integration serves and registers its bundled microphone card automatically.

```yaml
type: custom:tv-voice-card
entity: remote.living_room_tv
activation: hold
```

`entity` selects the configured TV. It may be omitted when exactly one TV is configured. Set `activation: toggle` to press once to record and again to send. Screen-reader/switch-generated activation supports this start/stop behavior even in hold mode. Space and Enter support holds on the focused button.

The card's editor exposes TV selection and activation behavior. English and Italian translations follow the active Home Assistant user's language; unsupported languages fall back to English. More translations are welcome. See [Card configuration](docs/card-configuration.md) for options and dashboard styling hooks.

For manual installation, copy `custom_components/tv_voice_bridge` into your Home Assistant `custom_components` directory, restart, and follow steps 3–4.

After updating through HACS, restart Home Assistant and refresh open dashboards to load the updated card.

## Recording, cancellation and privacy

- Audio is mono PCM16LE at 16 kHz, with a **480,000-byte / 15-second cap** enforced in the AudioWorklet and again as a backend byte cap.
- Audio remains in memory. It is transmitted as authenticated binary frames rather than base64 JSON, so normal HA WebSocket JSON debug logs do not contain speech payloads.
- Binary frames are bound to the initiating connection and session token, sequenced, size checked, and authorized against the selected TV. Metadata-only acknowledgements provide upload backpressure.
- Audio is forwarded to the TV's configured Google/Gemini or other assistant; the assistant's own processing and retention policies apply. This integration does not provide local speech recognition.
- Closing/removing the card, hiding the page, Escape, pointer cancellation, or losing the HA connection cancels recording and pending delivery. Cancellation also cancels an in-progress TV handshake.
- Startup, first audio, upload inactivity, and total session lifetime have separate bounded deadlines. The 15-second recording limit is not an upload deadline.
- The card also times out missing server replies and releases local audio on cancellation without waiting for the network. Transfer failures retain their specific error code briefly after backend cleanup.
- Submitted audio ends once; the dedicated TV transport remains alive briefly while the assistant processes it. Unloading an entry or stopping HA closes every transport and cancels pending tasks/timers.

Diagnostics contain only version information and session counts, with no audio, tokens, host addresses or pairing material. See [Protocol](docs/protocol.md) for the transport contract.

## Troubleshooting

- **No microphone access:** open HA using HTTPS, allow microphone access in browser permissions, and press again after granting a first-time permission prompt.
- **No audio:** check the device's microphone selection/mute settings and watch the level meter.
- **TV unavailable / pairing required:** verify the core Android TV Remote integration can control the TV and repair its pairing there. TV Voice Bridge reuses the pairing; it does not generate or replace credentials.
- **Unsupported version:** use a supported HA/library combination or wait for an adapter update. Do not override HA's library pin independently.
- **Sent but no response:** delivery counters mean the transport accepted the audio, not that the assistant recognized or executed a command. Check the TV assistant itself.
- **Wrong TV / multiple TVs:** select `entity` explicitly in the card.

Include integration/library/HA/browser versions and redacted diagnostics in bug reports. Never attach recordings, pairing keys or unredacted WebSocket dumps.

## Development

The repository follows the [HACS integration layout](https://www.hacs.dev/docs/publish/integration/): `custom_components/tv_voice_bridge/` contains the complete integration, including frontend modules, translations and brand assets. Tests, development tools and documentation live at the repository root. Development and release commands run from this checkout.

Use Python 3.14.2+ and Node 22+:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest
ruff check custom_components tests tools
ruff format --check custom_components tests tools
mypy custom_components/tv_voice_bridge
npm run check
npm test
python tools/check_release.py
```

The pinned development requirements reproduce the minimum supported Home Assistant release and its matching official test-fixture plugin. Tests use a real HA WebSocket server, schemas, config flows and entity registry while mocking TV transport. They cover cancellation races, permissions, binary payload privacy under debug logging, deadlines, the full buffer, real upstream wire framing, bundled frontend registration, translations, worklet limits and accessibility. Browser smoke tests are documented in `tests/browser/README.md`.

See the [Validation record](docs/validation.md) for release checks, test coverage and hardware acceptance results.

CI also runs official hassfest and HACS validation. Release automation checks the tag against all version declarations and attaches a component-only ZIP to a published GitHub release. Publishing is a separate maintainer action; local tests do not certify compatibility with untested TVs or future HA releases.

## Removal

Remove TV Voice Bridge entries under Devices & services, remove its dashboard cards, uninstall it through HACS, and restart HA. No pairing credentials or core Android TV Remote entries are removed.

## License

[MIT](LICENSE). TV Voice Bridge is independent of Home Assistant, HACS and TV/assistant vendors.
