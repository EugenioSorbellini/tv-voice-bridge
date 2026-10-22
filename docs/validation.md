# Validation record

## v1.0.0 — 2026-10-21

Local release validation completed on 2026-10-21 against Home Assistant 2026.10.2 and androidtvremote2 0.3.2:

- All 19 Home Assistant regression tests passed, with 92% statement coverage.
- Frontend tests passed for PCM conversion, worklet limits, recording, cancellation, accessibility, translations, target selection and public styling state. Unsupported card configuration produces an explicit localized error.
- The synthetic browser harness passed real AudioWorklet delivery, CSS styling across a wrapper shadow boundary, dynamic custom-element creation and cancellation when a wrapper is removed during pending delivery. No real microphone or TV was used.
- A separate dashboard-owned wrapper was tested with Universal Remote Card. Its remote dimensions and microphone position were verified at 1440 × 900, 390 × 740, 360 × 640 and 320 × 568 viewports. Dashboard composition is maintained outside this repository.
- Ruff lint/format, mypy and release metadata checks passed. Published CI and packaging results are linked from the v1.0.0 release notes.

Real phone-to-TV speech, early release during connection, the 15-second limit and consecutive recordings have been verified on one TCL installation using the Home Assistant phone app. Other hardware/browser combinations remain unverified.

## v1.1.0 — 2026-10-22

See the [implementation validation](protocol-lifecycle-validation-2026-10-22.md):
52 tests, 93% statement coverage, frontend/lint/type checks, and five live TV
trials covering short/full-length speech, server close, cancellation and recovery.
The unreleased build was subsequently installed and HA restarted; all 26 files
matched the tested checkout. On 2026-10-22, the owner reported “everything works”
after the requested phone validation checklist. Real-phone/dashboard acceptance
is recorded as passed on this TCL installation. See the [phone acceptance record](phone-validation-setup-2026-10-22.md).
No v1.1.0 release or tag has been issued.


### Final release checks

The v1.1.0 metadata was checked again after the version bump: 52 Python tests
passed with 93% statement coverage, frontend tests and JavaScript syntax checks
passed, and Ruff, mypy, tag/version validation and diff checks passed. The
component-only ZIP contains exactly 26 files, all matching the release checkout.
The phone test manifest above is retained as historical evidence for the
accepted pre-release build; it is not the final release version manifest.
