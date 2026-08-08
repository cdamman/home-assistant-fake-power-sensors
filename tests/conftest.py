"""Shared test fixtures."""

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(request):
    """Allow custom integrations to be loaded during the tests.

    `enable_custom_integrations` needs `hass`, and being autouse this fixture
    would therefore build `hass` before anything a test asks for itself. The
    recorder cannot be set up that way round: `recorder_db_url` refuses to
    prepare a database once `hass` exists. So a test that wants the recorder
    has to be handed it first, hence the explicit ordering below.
    """
    if "recorder_mock" in request.fixturenames:
        request.getfixturevalue("recorder_mock")

    request.getfixturevalue("enable_custom_integrations")
    yield
