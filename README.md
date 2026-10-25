# TV Voice Bridge

[![Coverage](https://raw.githubusercontent.com/EugenioSorbellini/tv-voice-bridge/python-coverage-comment-action-data/badge.svg)](https://github.com/EugenioSorbellini/tv-voice-bridge/tree/python-coverage-comment-action-data)

Talk to your Android TV's voice assistant from a Home Assistant dashboard, using the microphone on your phone, tablet or computer. Hold the button, speak and release: the TV receives your request as if you had used its own remote's microphone.

Nothing reaches the TV until you release, so you can still cancel: press Escape or switch away from the page. Recordings are capped at 15 seconds.

## Requirements

- Home Assistant **2026.10.2** or later.
- The **Android TV Remote** integration, set up and paired with your TV.
- Home Assistant opened over **HTTPS** (browsers only allow the microphone there), on a device with a microphone.
- A TV with Google Assistant or another voice assistant. Verified on a TCL Google TV; other models are likely to work but untested (see [Compatibility](docs/compatibility.md)).

## Installation

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=EugenioSorbellini&repository=tv-voice-bridge&category=integration)

1. Click the button above, or in HACS add `https://github.com/EugenioSorbellini/tv-voice-bridge` as a custom repository (category **Integration**). Then download **TV Voice Bridge** and restart Home Assistant.
2. Go to **Settings → Devices & services → Add integration → TV Voice Bridge** and pick your TV. Repeat for each TV.
3. Add the **TV Voice Bridge** card to a dashboard.

The card is loaded automatically; don't add it as a dashboard resource. After an update, restart Home Assistant and refresh your dashboards.

## Using the card

```yaml
type: custom:tv-voice-card
entity: remote.living_room_tv
```

| Option | Default | Description |
| --- | --- | --- |
| `entity` | The only TV | The TV's `remote.*` entity. Required when you have more than one TV. |
| `activation` | `hold` | `hold`: talk while pressed. `toggle`: press once to start, again to send. |

Both options are also in the card's visual editor. The card follows your Home Assistant language (English and Italian; others fall back to English).

### Examples

**Phone-friendly toggle.** Holding a button on a touch screen can be awkward:

```yaml
type: custom:tv-voice-card
entity: remote.living_room_tv
activation: toggle
```

**With the TV's media controls:**

```yaml
type: vertical-stack
cards:
  - type: media-control
    entity: media_player.living_room_tv
  - type: custom:tv-voice-card
    entity: remote.living_room_tv
```

**Only while the TV is on:**

```yaml
type: conditional
conditions:
  - condition: state
    entity: media_player.living_room_tv
    state_not: "off"
card:
  type: custom:tv-voice-card
  entity: remote.living_room_tv
```

**One microphone per TV:**

```yaml
type: horizontal-stack
cards:
  - type: custom:tv-voice-card
    entity: remote.living_room_tv
  - type: custom:tv-voice-card
    entity: remote.bedroom_tv
```

**In a pop-up** with [Bubble Card](https://github.com/Clooos/Bubble-Card) (this syntax was tested with Bubble Card v3.4.2), opened by a button that navigates to the pop-up's hash:

```yaml
- type: button
  name: Talk to the TV
  icon: mdi:microphone
  tap_action:
    action: navigate
    navigation_path: "#tv-voice"
- type: custom:bubble-card
  card_type: pop-up
  hash: "#tv-voice"
  name: Living room TV
  icon: mdi:television
  cards:
    - type: custom:tv-voice-card
      entity: remote.living_room_tv
```

**Inside a full remote.** [Remote Card for TCL Google TV](https://github.com/EugenioSorbellini/tcl-google-tv-remote) puts this microphone in the centre of a remote layout:

```yaml
type: custom:tcl-google-tv-remote
remote_id: remote.living_room_tv
media_player_id: media_player.living_room_tv
microphone_activation: toggle
```

To restyle the button or build your own card around it, see [Card configuration](docs/card-configuration.md).

## Privacy

- Audio stays in memory and never appears in Home Assistant's logs.
- Only the user who started a recording can send it, and only to a TV they're allowed to control.
- Your TV's assistant (Google or other) processes the speech under its own policies; there's no local speech recognition.
- Diagnostics contain only version information and session counts.

## Troubleshooting

- **No microphone access:** open HA using HTTPS, allow microphone access in browser permissions, and press again after granting a first-time permission prompt.
- **No audio:** check the device's microphone selection/mute settings and watch the level meter.
- **TV unavailable / pairing required:** verify the core Android TV Remote integration can control the TV and repair its pairing there. TV Voice Bridge reuses the pairing; it does not generate or replace credentials.
- **Card out of date:** after an update, the dashboard can still run the previous card from the browser or app cache. Refresh the page. If the card still shows an old error or the out-of-date message, reset the cache:
  - **Android Companion app:** **Settings → Companion app → Troubleshooting → Reset frontend cache**, then reopen the dashboard.
  - **iOS Companion app:** **Settings → Companion app → Debugging → Reset frontend cache**, then pull down on the dashboard to refresh.
  - **Browser:** reload while bypassing the cache (Ctrl+Shift+R, or Cmd+Shift+R on macOS).
- **Sent but no response:** delivery counters mean the transport accepted the audio, not that the assistant recognized or executed a command. Check the TV assistant itself.
- **Wrong TV / multiple TVs:** select `entity` explicitly in the card.

Include the integration, HA, browser and TV Remote Service versions and redacted diagnostics in bug reports. Never attach recordings, pairing keys or unredacted WebSocket dumps.

## Removal

Remove TV Voice Bridge entries under Devices & services, remove its dashboard cards, uninstall it through HACS, and restart HA. No pairing credentials or core Android TV Remote entries are removed.

## Development

Building, testing and releasing are described in [Development](docs/development.md).

## License

[MIT](LICENSE). TV Voice Bridge is independent of Home Assistant, HACS and TV/assistant vendors.
