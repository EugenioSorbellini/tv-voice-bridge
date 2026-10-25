"""Serve and register the bundled dashboard assets."""

from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
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
    frontend.add_extra_js_url(hass, url)
    return url
