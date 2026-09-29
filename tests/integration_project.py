"""Shared integration-test project selection (local mock vs live platforms)."""

from __future__ import annotations

import os

from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.constants import ENV_VARIABLES
from tests.mock_server.routers.data_platform import (
    MOCK_DEFAULT_PROJECT_ID,
    MOCK_DEFAULT_PROJECT_NAME,
)

# Display name for the shared project on dev / staging / prod (id resolved at runtime).
LIVE_INTEGRATION_PROJECT_NAME = "do-dd-client-tests"
LIVE_INTEGRATION_PROJECT_DESCRIPTION = (
    "Shared data-platform project for do-dd-client integration and level-1 tests."
)


def integration_project_name(env: str) -> str:
    """Return the project display name used by tests for ``env``."""

    if env == "local":
        return MOCK_DEFAULT_PROJECT_NAME
    return LIVE_INTEGRATION_PROJECT_NAME


def integration_project_id_for_env(env: str) -> str | None:
    """Return the expected project id for ``env`` when it is known without API calls."""

    if env == "local":
        return MOCK_DEFAULT_PROJECT_ID
    return None


def ensure_live_integration_project_id() -> str:
    """Resolve or create the integration project on a live platform.

    Uses ``DO_PROJECT_ID`` when already set (manual/CI override). Otherwise
    upserts :data:`LIVE_INTEGRATION_PROJECT_NAME` via the projects API and
    stores the canonical id in ``DO_PROJECT_ID`` for the rest of the session.

    Returns:
        Canonical project id string.
    """

    from deeporigin import projects

    existing = os.environ.get(ENV_VARIABLES["project_id"])
    if existing and existing.strip():
        return existing.strip()

    client = DeepOriginClient()
    pid = projects.create(
        LIVE_INTEGRATION_PROJECT_NAME,
        description=LIVE_INTEGRATION_PROJECT_DESCRIPTION,
        load=True,
        client=client,
    )
    os.environ[ENV_VARIABLES["project_id"]] = pid
    DeepOriginClient.close_all()
    return pid


def apply_integration_project(client: DeepOriginClient, env: str) -> None:
    """Set ``client.project_id`` for integration tests."""

    if env == "local":
        client.project_id = MOCK_DEFAULT_PROJECT_ID
        return

    pid = os.environ.get(ENV_VARIABLES["project_id"])
    if pid and pid.strip():
        client.project_id = pid.strip()
        return

    client.project_id = ensure_live_integration_project_id()
