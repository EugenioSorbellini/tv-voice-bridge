"""Serve and register the bundled dashboard assets."""

import logging
from pathlib import Path
from urllib.parse import urlsplit

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import VERSION

_LOGGER = logging.getLogger(__name__)


async def async_register_frontend(hass: HomeAssistant) -> str:
    """Register the current bundled module and its static assets."""
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                f"/tv_voice_bridge/frontend/{VERSION}",
                str(Path(__file__).parent / "frontend"),
                False,
            )
        ]
    )
    url = f"/tv_voice_bridge/frontend/{VERSION}/tv-voice-card.js"
    await _migrate_resources(hass, url)
    frontend.add_extra_js_url(hass, url)
    return url


async def _migrate_resources(hass: HomeAssistant, url: str) -> None:
    """Point dashboard resources left by pre-1.0 releases at the current module.

    Lovelace's resource collection is internal to Home Assistant. If it changes,
    skip this optional migration instead of failing to load the integration.
    """
    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA

        resources = hass.data[LOVELACE_DATA].resources
        if not hasattr(resources, "async_update_item"):
            return  # YAML-mode resources are read-only.
        await resources.async_get_info()
        for item in resources.async_items():
            path = urlsplit(item["url"]).path
            ours = path.startswith("/tv_voice_bridge/frontend/") and path.endswith(
                "/tv-voice-card.js"
            )
            if ours and item["url"] != url:
                await resources.async_update_item(item["id"], {"url": url, "res_type": "module"})
    except Exception as error:
        _LOGGER.debug("Skipped dashboard resource migration (%s)", type(error).__name__)
