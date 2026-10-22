# Phone validation setup — 2026-10-22

The owner authorized installation of the unreleased implementation for phone acceptance testing. The 26 installed component files were verified against the checkout by SHA256, Home Assistant's configuration check passed, and HA was fully restarted. Runtime diagnostics confirm `configured: true`, androidtvremote2 `0.3.2`, zero active sessions and zero processing sessions.

This supersedes the earlier investigation's statement that the installed component was unchanged. No GitHub release or tag was created. Version metadata intentionally remains `1.0.0` while preparing v1.1.0; use the [build manifest](phone-validation-build-2026-10-22.json) to identify the exact test code.

A rollback ZIP of the previously installed 23 files is saved locally at `validation-backups/tv-voice-bridge-before-validation-20261022T114634Z.zip` (ignored by Git). SHA256: `397df9cc5d5008391375814d124e927d1e2c222d600184383964c41816b80953`.

## Phone checks

1. Fully refresh the Home Assistant dashboard or close/reopen the app so it loads the updated microphone JavaScript.
2. Turn on the TV, then open **Elettrodomestici → Telecomando → Apri**. The direct full-page view is `/dashboard-elettrodomestici/telecomando-tv`.
3. Hold the microphone, ask a short question such as “Dimmi che ore sono”, and release. Check the TV transcript and response separately from the card's sent indicator.
4. Start again and release quickly while connection setup is still in progress. The captured phrase should still be delivered after readiness.
5. Record up to the automatic 15-second cap; finish with a recognizable question. Confirm recording stops and the final question reaches the TV.
6. Send several recordings in succession. Check that no old audio replays and no session stays busy after completion.
7. Cancel with Escape where available, hide the app/page, or close the popup during recording. Reopen it and check that a fresh recording works.

Record any error text, whether a transcript appeared on the TV, and which case failed. No audio recording, credential, or unredacted WebSocket log is needed. The one-second startup delay remains in place. The TV close event stops backend forwarding but does not push an immediate microphone-stop notification to the existing browser card.

Phone acceptance passed on 2026-10-22: after receiving the checklist above, the owner reported “everything works”. This is owner-reported acceptance on the existing TCL installation, not independent evidence for other hardware or browsers. No release or tag has been issued.

After restart, a full dashboard reload rendered the existing TV Salotto popup
and the Italian **Parla alla TV** microphone successfully. No TV controls or
microphone were activated for this readiness check; the TV remained off.
