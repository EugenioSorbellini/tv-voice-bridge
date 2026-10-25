"""Real UI config flows, entity registry selection, setup and unload."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tv_voice_bridge import async_setup_entry, async_unload_entry
from custom_components.tv_voice_bridge.const import DOMAIN, VERSION
from custom_components.tv_voice_bridge.frontend import async_register_frontend
from custom_components.tv_voice_bridge.manager import BridgeManager
from custom_components.tv_voice_bridge.target import resolve_target


@pytest.fixture
async def paired_tv(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    storage = tmp_path / ".storage"
    storage.mkdir(exist_ok=True)
    for name in ("androidtv_remote_cert.pem", "androidtv_remote_key.pem"):
        (storage / name).write_text("synthetic test pairing placeholder")
    source = MockConfigEntry(
        domain="androidtv_remote", data={"host": "tv.invalid"}, entry_id="source-tv"
    )
    source.add_to_hass(hass)
    entity = er.async_get(hass).async_get_or_create(
        "remote", "androidtv_remote", "tv-1", suggested_object_id="test_tv", config_entry=source
    )
    hass.states.async_set(entity.entity_id, "on", {"friendly_name": "Test TV"})
    return entity, source


@pytest.mark.asyncio
async def test_real_flow_create_and_duplicate(hass, paired_tv):
    """Adding a TV through the real UI config flow, then adding it again.

    Runs the user flow with a paired Android TV Remote TV and selects its remote entity,
    then repeats the flow for the same TV.

    Verifies: the first flow shows a form and creates an entry storing the remote entity
    and the source Android TV Remote entry id; the second aborts with already_configured.
    """
    entity, source_entry = paired_tv
    with patch.object(hass.config_entries, "async_setup", return_value=True):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        assert result["type"] == FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"remote_entity": entity.entity_id}
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"] == {
            "remote_entity": entity.entity_id,
            "androidtv_entry_id": source_entry.entry_id,
        }
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"remote_entity": entity.entity_id}
        )
        assert result["reason"] == "already_configured"


@pytest.mark.asyncio
async def test_flow_aborts_without_android_tv_remote(hass):
    """Adding the integration with no Android TV Remote TV.

    Starts the user config flow in a Home Assistant with no androidtv_remote remote
    entities.

    Verifies: the flow aborts immediately with reason no_android_tv instead of showing a
    form with an empty TV list.
    """
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "no_android_tv"


@pytest.mark.asyncio
async def test_flow_reports_missing_pairing_without_contacting_tv(hass, paired_tv):
    """Missing pairing files and unknown entities are reported on the form.

    Deletes the pairing key, marks the core Android TV Remote entry as retrying setup and
    submits the TV; then submits a nonexistent entity. Validation only reads the registry
    and the pairing files, so no TV is contacted.

    Verifies: the first submit shows pairing_required and the second invalid_target, and
    neither creates an entry.
    """
    entity, source = paired_tv
    Path(hass.config.path(".storage", "androidtv_remote_key.pem")).unlink()
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    # Without pairing files, the core integration cannot connect and retries setup.
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"remote_entity": entity.entity_id}
    )
    assert result["errors"] == {"base": "pairing_required"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"remote_entity": "remote.missing"}
    )
    assert result["errors"] == {"base": "invalid_target"}


@pytest.mark.asyncio
async def test_pairing_paths_match_core_integration(hass, paired_tv):
    """The bridge reads the pairing files from the same paths as core's client.

    Resolves the bridge's target, and calls core's create_api with its client class
    patched to capture the certificate and key paths it is given.

    Verifies: both paths match. Fails when a Home Assistant release moves the pairing
    files, before users see pairing errors.
    """
    from homeassistant.components.androidtv_remote import helpers

    entity, source = paired_tv
    target = resolve_target(hass, entity.entity_id, source.entry_id)
    # Read core's choice from the client it constructs, not from library internals.
    with patch.object(helpers, "AndroidTVRemote") as client:
        helpers.create_api(hass, "tv.invalid", False)
    assert (target.certfile, target.keyfile) == (
        client.call_args.kwargs["certfile"],
        client.call_args.kwargs["keyfile"],
    )


@pytest.mark.asyncio
async def test_moved_pairing_is_not_reported_as_unpaired(hass, paired_tv):
    """Pairing files missing while core is connected are reported as moved, not unpaired.

    Deletes the pairing key while the core Android TV Remote entry is loaded, submits the
    TV in the config flow, then sets up an existing bridge entry.

    Verifies: the form shows pairing_not_found rather than pairing_required, and entry
    setup raises ConfigEntryError, a permanent error, rather than retrying.
    """
    entity, source = paired_tv
    Path(hass.config.path(".storage", "androidtv_remote_key.pem")).unlink()
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    source.mock_state(hass, ConfigEntryState.LOADED)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"remote_entity": entity.entity_id}
    )
    assert result["errors"] == {"base": "pairing_not_found"}
    hass.data[DOMAIN] = BridgeManager(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"remote_entity": entity.entity_id, "androidtv_entry_id": source.entry_id},
    )
    entry.add_to_hass(hass)
    with pytest.raises(ConfigEntryError):
        await async_setup_entry(hass, entry)


@pytest.mark.asyncio
async def test_setup_unload_and_rename(hass, paired_tv):
    """Entry setup, an entity rename, and unload.

    Sets up a bridge entry, renames the TV's remote entity in the registry, then unloads
    the entry.

    Verifies: the manager resolves the TV before and after the rename, using the new
    entity id; unload removes the TV from the manager.
    """
    entity, source = paired_tv
    manager = hass.data[DOMAIN] = BridgeManager(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"remote_entity": entity.entity_id, "androidtv_entry_id": source.entry_id},
    )
    entry.add_to_hass(hass)
    assert await async_setup_entry(hass, entry)
    assert manager.target(None)[1].entity_id == entity.entity_id
    renamed = er.async_get(hass).async_update_entity(
        entity.entity_id, new_entity_id="remote.renamed"
    )
    assert manager.target(None)[1].entity_id == renamed.entity_id
    assert await async_unload_entry(hass, entry)
    assert not manager.targets


@pytest.mark.asyncio
async def test_frontend_registers_the_bundled_module(hass):
    """The bundled card is served under a versioned path and added to the frontend.

    Registers the frontend with HA's static path registration and add_extra_js_url
    patched.

    Verifies: the module URL contains the integration version and is passed to
    add_extra_js_url once; the static path /tv_voice_bridge/frontend/<version> points at
    the directory holding tv-voice-card.js.
    """
    hass.http = Mock(async_register_static_paths=AsyncMock())
    with patch("custom_components.tv_voice_bridge.frontend.frontend.add_extra_js_url") as register:
        url = await async_register_frontend(hass)
    assert f"/{VERSION}/" in url
    register.assert_called_once_with(hass, url)
    registration = hass.http.async_register_static_paths.call_args.args[0][0]
    assert registration.url_path == f"/tv_voice_bridge/frontend/{VERSION}"
    assert Path(registration.path, "tv-voice-card.js").is_file()


@pytest.mark.asyncio
async def test_complete_setup_serves_assets_and_unloads(hass, paired_tv, hass_client):
    """Full setup through Home Assistant serves the card's files and unloads cleanly.

    Sets up the integration with a stored entry, fetches each frontend file over HA's
    HTTP server, then unloads the entry.

    Verifies: one entry is loaded and its TV is known to the manager; the card module is
    in the frontend's extra module list; tv-voice-card.js, pcm-worklet.js, pcm.mjs and
    localize.mjs return 200 with a JavaScript content type; unload removes the TV.
    """
    from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
    from homeassistant.setup import async_setup_component

    entity, source = paired_tv
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=source.entry_id,
        data={"remote_entity": entity.entity_id, "androidtv_entry_id": source.entry_id},
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    manager = hass.data[DOMAIN]
    assert entries[0].entry_id in manager.targets
    assert manager.frontend_url in hass.data[DATA_EXTRA_MODULE_URL].urls
    client = await hass_client()
    for name in ("tv-voice-card.js", "pcm-worklet.js", "pcm.mjs", "localize.mjs"):
        response = await client.get(f"/tv_voice_bridge/frontend/{VERSION}/" + name)
        assert response.status == 200
        assert "javascript" in response.content_type
    assert await hass.config_entries.async_unload(entries[0].entry_id)
    assert not manager.targets


@pytest.mark.asyncio
async def test_options_and_reconfigure_same_tv(hass, paired_tv):
    """Options and reconfigure flows accept the entry's own TV.

    Opens the options flow and submits the entry's TV, then runs the reconfigure flow with
    the same TV.

    Verifies: options shows a form and saves; reconfigure finishes with
    reconfigure_successful.
    """
    entity, source = paired_tv
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=source.entry_id,
        data={
            "remote_entity": entity.entity_id,
            "androidtv_entry_id": source.entry_id,
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"remote_entity": entity.entity_id}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    with patch.object(hass.config_entries, "async_reload", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": "reconfigure",
                "entry_id": entry.entry_id,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"remote_entity": entity.entity_id}
        )
        assert result["reason"] == "reconfigure_successful"


@pytest.mark.asyncio
async def test_options_and_reconfigure_refuse_a_different_tv(hass, paired_tv):
    """Options and reconfigure can't move an entry to another TV.

    Adds a second paired TV, then submits it in the options flow and in the
    reconfigure flow of the first TV's entry.

    Verifies: options shows different_target on the form; reconfigure aborts with
    unique_id_mismatch; the entry still points at the first TV.
    """
    entity, source = paired_tv
    other_source = MockConfigEntry(
        domain="androidtv_remote", data={"host": "tv2.invalid"}, entry_id="source-tv-2"
    )
    other_source.add_to_hass(hass)
    other = er.async_get(hass).async_get_or_create(
        "remote",
        "androidtv_remote",
        "tv-2",
        suggested_object_id="second_tv",
        config_entry=other_source,
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=source.entry_id,
        data={"remote_entity": entity.entity_id, "androidtv_entry_id": source.entry_id},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"remote_entity": other.entity_id}
    )
    assert result["errors"] == {"base": "different_target"}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"remote_entity": other.entity_id}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"
    assert entry.data["androidtv_entry_id"] == source.entry_id


@pytest.mark.asyncio
async def test_diagnostics_omit_device_identity_and_audio(hass, paired_tv):
    """Diagnostics contain only the version and session counts.

    Registers a configured TV in the manager and requests the entry's diagnostics.

    Verifies: the result is exactly the integration version, configured true and zero
    active and processing sessions, with no entity, host or pairing data.
    """
    from custom_components.tv_voice_bridge.diagnostics import async_get_config_entry_diagnostics

    entity, source = paired_tv
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "remote_entity": entity.entity_id,
            "androidtv_entry_id": source.entry_id,
        },
    )
    manager = hass.data[DOMAIN] = BridgeManager(hass)
    manager.targets[entry.entry_id] = (entity.entity_id, source.entry_id)
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result == {
        "integration_version": VERSION,
        "configured": True,
        "active_sessions": 0,
        "processing_sessions": 0,
    }


@pytest.mark.asyncio
async def test_options_http_serialization(hass, paired_tv, hass_client):
    """The options flow serializes over HA's HTTP API.

    Sets up the integration and opens the options flow through
    /api/config/config_entries/options/flow, as the frontend does.

    Verifies: the request succeeds and returns a form whose schema has the remote_entity
    field, so the entity selector serializes to JSON.
    """
    from homeassistant.setup import async_setup_component

    entity, source = paired_tv
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=source.entry_id,
        data={"remote_entity": entity.entity_id, "androidtv_entry_id": source.entry_id},
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    client = await hass_client()
    response = await client.post(
        "/api/config/config_entries/options/flow", json={"handler": entry.entry_id}
    )
    assert response.status == 200, await response.text()
    result = await response.json()
    assert result["type"] == "form"
    assert result["data_schema"][0]["name"] == "remote_entity"
