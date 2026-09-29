"""Unit tests for integration project helpers."""

from tests.integration_project import (
    LIVE_INTEGRATION_PROJECT_NAME,
    integration_project_id_for_env,
    integration_project_name,
)
from tests.mock_server.routers.data_platform import (
    MOCK_DEFAULT_PROJECT_ID,
    MOCK_DEFAULT_PROJECT_NAME,
)


def test_integration_project_name_local() -> None:
    assert integration_project_name("local") == MOCK_DEFAULT_PROJECT_NAME
    assert integration_project_name("dev") == LIVE_INTEGRATION_PROJECT_NAME


def test_integration_project_id_local_only() -> None:
    assert integration_project_id_for_env("local") == MOCK_DEFAULT_PROJECT_ID
    assert integration_project_id_for_env("dev") is None
