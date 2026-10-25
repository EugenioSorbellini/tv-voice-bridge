# Development

For a manual installation, copy `custom_components/tv_voice_bridge` into Home Assistant's `custom_components` directory and restart, then add the integration as described in the [README](../README.md#installation).

The repository follows the [HACS integration layout](https://www.hacs.dev/docs/publish/integration/): `custom_components/tv_voice_bridge/` contains the complete integration, including frontend modules, translations and brand assets. Tests, development tools and documentation live at the repository root. Development and release commands run from this checkout.

Use Python 3.14.2+ and Node 22+:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pip install $(python tools/ha_requirements.py androidtv_remote)
pytest
ruff check custom_components tests tools
ruff format --check custom_components tests tools
mypy custom_components/tv_voice_bridge
npm run check
npm test
python tools/check_release.py
```

The pinned development requirements reproduce the minimum supported Home Assistant release and its matching official test-fixture plugin. Tests use a real HA WebSocket server, schemas, config flows and entity registry while mocking TV transport. They cover cancellation races, permissions, binary payload privacy under debug logging, deadlines, the full buffer, the client's wire format checked against a fixed copy of the upstream schema, bundled frontend registration, translations, worklet limits and accessibility. Browser smoke tests are documented in `tests/browser/README.md`.

The generated `voice_pb2.py` and `voice_pb2.pyi` are checked in and excluded from Ruff formatting. After changing `voice.proto`, regenerate them from the repository root in a separate compiler environment:

```sh
python3.14 -m venv /tmp/tv-voice-protoc
/tmp/tv-voice-protoc/bin/pip install grpcio-tools==1.84.1
/tmp/tv-voice-protoc/bin/python -m grpc_tools.protoc -I. --python_out=. --pyi_out=. custom_components/tv_voice_bridge/voice.proto
```

grpcio-tools 1.84.1 bundles protoc 35.1, so the module requires protobuf 7.35.1 or later at import. Keep it at or below the protobuf of the minimum supported Home Assistant (7.36.2 for 2026.10.2), and regenerate with a matching compiler when Home Assistant moves to a new protobuf major; the weekly compatibility workflow imports the module against HA beta first.

Release checks and hardware acceptance are summarized per version in the [Changelog](../CHANGELOG.md). The [voice protocol research](voice-protocol-research.md) records the tested hardware, the live TV trials and why the bridge has its own voice client.

CI also runs official hassfest and HACS validation. Release automation checks the tag against all version declarations and attaches a component-only ZIP to a published GitHub release. Publishing is a separate maintainer action; local tests do not certify compatibility with untested TVs or future HA releases.

A weekly **Home Assistant compatibility** workflow (also runnable manually) tests the current stable and beta HA releases ahead of users. It runs the Python tests with the androidtvremote2 (used by the core Android TV Remote integration) and frontend versions each release pins. It also starts the official HA container with this integration, onboards it, saves a dashboard containing the card, and checks on five page loads that HA renders `tv-voice-card` rather than an error card. HA betas usually appear about a week before each monthly release.
