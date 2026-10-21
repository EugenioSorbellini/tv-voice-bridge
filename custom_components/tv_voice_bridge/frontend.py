"""Serve and register the bundled dashboard assets."""

from pathlib import Path
from urllib.parse import urlsplit

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant

from .const import VERSION


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
    resources = hass.data[LOVELACE_DATA].resources
    if hasattr(resources, "async_update_item"):
        await resources.async_get_info()
        for item in resources.async_items():
            path = urlsplit(item["url"]).path
            ours = path.startswith("/tv_voice_bridge/frontend/") and path.endswith(
                "/tv-voice-card.js"
            )
            if ours and item["url"] != url:
                await resources.async_update_item(item["id"], {"url": url, "res_type": "module"})
    frontend.add_extra_js_url(hass, url)
    return url
