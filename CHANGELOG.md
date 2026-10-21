# Changelog

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
