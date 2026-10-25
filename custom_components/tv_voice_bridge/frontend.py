"""Serve and register the bundled dashboard assets."""

import hashlib
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import VERSION

FRONTEND_DIR = Path(__file__).parent / "frontend"


def frontend_hash(directory: Path = FRONTEND_DIR) -> str:
    """Blocking; changes with any asset, so caches and CDNs never mix deployments.

    It goes in the path, not a query: the card resolves its modules and worklet
    relative to its own URL, which drops the query string.
    """
    digest = hashlib.sha256()
    for file in sorted(path for path in directory.rglob("*") if path.is_file()):
        digest.update(file.relative_to(directory).as_posix().encode() + b"\0")
        digest.update(file.read_bytes())
    return digest.hexdigest()[:12]


async def async_register_frontend(hass: HomeAssistant) -> str:
    """Register the current bundled module and its static assets."""
    content = await hass.async_add_executor_job(frontend_hash)
    url_path = f"/tv_voice_bridge/frontend/{VERSION}-{content}"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(url_path, str(FRONTEND_DIR), False)]
    )
    url = f"{url_path}/tv-voice-card.js"
    frontend.add_extra_js_url(hass, url)
    return url
