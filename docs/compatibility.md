# Compatibility contract

The wire adapter is currently tested against androidtvremote2 **0.3.2** and Home Assistant **2026.10.2**. Home Assistant owns that dependency; the integration does not introduce a competing package requirement. The minimum HA version is declared in hacs.json. CI uses the exact minimum HA and library versions so a current development environment cannot accidentally hide a compatibility break.

The tested TCL Remote Service consumes protobuf field 31 as raw PCM bytes. Upstream 0.3.2 nests a session/samples message there, which introduces an odd-length header into audio and shifts PCM16 alignment. `protocol.py` corrects outgoing voice begin/payload messages only on the bridge's dedicated connection. It preserves pairing and the core integration connection. It declares 16 kHz, Android mono channel mask 16, PCM16 format 2.

This adapter accesses private protocol internals and is deliberately isolated and version-gated. If Home Assistant upgrades androidtvremote2, the integration reports `unsupported_version` rather than silently applying the patch to an untested implementation. Updating support requires reviewing upstream framing, running the real VoiceStream framing test, and testing recognition on supported hardware. Prefer removing this adapter after an upstream fix is available; do not extend its version allowlist without evidence.

The one-second voice-readiness delay and 15-second post-submission processing grace come from observations on the tested TCL. They are named policy constants, not evidence that every Android TV needs the same timing. Other device reports should include model and Remote Service version without speech content. Hardware compatibility is verified only on the tested TCL installation.
