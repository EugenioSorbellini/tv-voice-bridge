"""Real Home Assistant fixtures, with all network connections mocked in tests."""

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Enable integration discovery from this repository."""


@pytest.fixture(autouse=True)
def mock_core_tv_setup():
    """Never open the real core integration transport while testing config flows."""
    from unittest.mock import AsyncMock, patch

    with patch(
        "homeassistant.components.androidtv_remote.async_setup_entry",
        new=AsyncMock(return_value=True),
    ):
        yield
