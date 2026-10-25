# Card configuration

TV Voice Bridge includes a microphone card that can be added through the dashboard card picker or YAML:

```yaml
type: custom:tv-voice-card
entity: remote.living_room_tv
activation: hold
```

The selected TV must already have a TV Voice Bridge integration entry. The integration automatically loads the card and its frontend modules.

| Option | Default | Behavior |
| --- | --- | --- |
| `type` | Required | `custom:tv-voice-card`. |
| `entity` | Automatic selection | Android TV Remote entity configured in TV Voice Bridge. May be omitted when exactly one TV is configured. |
| `activation` | `hold` | `hold` records while pressed and submits on release; `toggle` starts on one activation and submits on the next. |

The visual editor exposes `entity` and `activation`. English and Italian follow the Home Assistant user's language, with English fallback. In hold mode, Space and Enter support keyboard holds; assistive activation supports start/stop toggling. Both activation modes share the 15-second capture cap. Escape, hiding the page, an interrupted touch, removing the card or losing the Home Assistant connection cancels a recording and anything not yet sent.

## Composition and styling

Dashboard projects can compose this microphone with other cards and own their layout and artwork. The microphone card handles capture, permissions, delivery and cancellation. Removing a parent wrapper from the page disconnects the microphone card and cancels its active recording or pending delivery automatically.

The constructor returned by `customElements.get('tv-voice-card')` exposes `stylingVersion === 1`. A wrapper can wait for `customElements.whenDefined('tv-voice-card')` and check this marker before using the public styling interface. It does not need to import the integration's versioned frontend URL.

| CSS part | Element |
| --- | --- |
| `card` | Outer card container. |
| `button` | Recording button; preserves keyboard, pointer and assistive activation. |
| `icon` | Microphone or stop icon. |
| `label` | Visible button label; the button also retains its localized accessible name. |
| `status` | Live status text. |
| `hint` | Additional part on the status element when displaying idle instructions. |
| `feedback` | Additional part on the status element when displaying recording, delivery, result or error feedback. |
| `meter` | Audio level meter, hidden outside recording. |
| `level` | Meter fill; its width is managed by capture. |

For example, a dashboard wrapper's stylesheet can style the button without accessing the microphone's shadow DOM:

```css
tv-voice-card::part(button) {
  border-radius: 999px;
}
tv-voice-card[data-state="recording"]::part(button) {
  background: #c62832;
}
```

The microphone host reflects a read-only `data-state` attribute: `idle`, `starting` (microphone startup), `recording`, or `sending` (capture cleanup, waiting for TV readiness, upload or cancellation cleanup). An idle card can display a recording result through the `feedback` part. Error text remains localized and announced through the status element's live region.

Use these CSS parts and state attributes for appearance. Keep accessible names, visible focus and error feedback intact. Wrappers should pass configuration through `setConfig()` and Home Assistant state through `hass`, and let DOM removal handle cancellation. Recording internals and shadow DOM structure are private.
