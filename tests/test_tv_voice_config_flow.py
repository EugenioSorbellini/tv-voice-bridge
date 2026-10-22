"""Real UI config flows, entity registry selection, setup and unload."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tv_voice_bridge import async_setup_entry, async_unload_entry
from custom_components.tv_voice_bridge.const import DOMAIN, VERSION
from custom_components.tv_voice_bridge.frontend import async_register_frontend
from custom_components.tv_voice_bridge.manager import BridgeManager


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
async def test_flow_reports_missing_pairing_without_contacting_tv(hass, paired_tv):
    entity, _ = paired_tv
    Path(hass.config.path(".storage", "androidtv_remote_key.pem")).unlink()
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"remote_entity": entity.entity_id}
    )
    assert result["errors"] == {"base": "pairing_required"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"remote_entity": "remote.missing"}
    )
    assert result["errors"] == {"base": "invalid_target"}


@pytest.mark.asyncio
async def test_setup_unload_and_rename(hass, paired_tv):
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
async def test_frontend_registers_bundled_resource_and_preserves_other_resources(hass):
    resources = Mock()
    resources.async_get_info = AsyncMock()
    resources.async_items.return_value = [
        {"id": "ours", "url": "/tv_voice_bridge/frontend/1.0.0/tv-voice-card.js?cache=example"},
        {"id": "unrelated", "url": "/local/another-card.js?v=3"},
    ]
    resources.async_update_item = AsyncMock()
    hass.data[LOVELACE_DATA] = SimpleNamespace(resources=resources)
    hass.http = Mock(async_register_static_paths=AsyncMock())
    with patch("custom_components.tv_voice_bridge.frontend.frontend.add_extra_js_url") as register:
        url = await async_register_frontend(hass)
    assert f"/{VERSION}/" in url
    resources.async_update_item.assert_awaited_once_with("ours", {"url": url, "res_type": "module"})
    register.assert_called_once_with(hass, url)
    registration = hass.http.async_register_static_paths.call_args.args[0][0]
    assert registration.url_path == f"/tv_voice_bridge/frontend/{VERSION}"
    assert Path(registration.path, "tv-voice-card.js").is_file()


@pytest.mark.asyncio
async def test_complete_setup_serves_assets_and_unloads(hass, paired_tv, hass_client):
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
async def test_diagnostics_omit_device_identity_and_audio(hass, paired_tv):
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
        "library_version": "0.3.2",
        "configured": True,
        "active_sessions": 0,
        "processing_sessions": 0,
    }


@pytest.mark.asyncio
async def test_options_http_serialization(hass, paired_tv, hass_client):
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
