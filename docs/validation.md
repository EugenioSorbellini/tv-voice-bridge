# Validation record — 1.0.0

Local release validation completed on 2026-10-21 against Home Assistant 2026.10.2 and androidtvremote2 0.3.2:

- All 19 Home Assistant regression tests passed, with 92% statement coverage.
- Frontend tests passed for PCM conversion, worklet limits, recording, cancellation, accessibility, translations, target selection and public styling state. Unsupported card configuration produces an explicit localized error.
- The synthetic browser harness passed real AudioWorklet delivery, CSS styling across a wrapper shadow boundary, dynamic custom-element creation and cancellation when a wrapper is removed during pending delivery. No real microphone or TV was used.
- A separate dashboard-owned wrapper was tested with Universal Remote Card. Its remote dimensions and microphone position were verified at 1440 × 900, 390 × 740, 360 × 640 and 320 × 568 viewports. Dashboard composition is maintained outside this repository.
- Ruff lint/format, mypy and release metadata checks passed. Published CI and packaging results are linked from the v1.0.0 release notes.

Real phone-to-TV speech, early release during connection, the 15-second limit and consecutive recordings have been verified on one TCL installation using the Home Assistant phone app. Other hardware/browser combinations remain unverified.
