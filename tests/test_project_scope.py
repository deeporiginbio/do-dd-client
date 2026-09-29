"""Tests for client project scoping helpers."""

from __future__ import annotations

import pytest

from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.project_scope import require_client_project_id


def test_require_client_project_id_returns_client_value() -> None:
    client = DeepOriginClient.from_local()
    client.project_id = "proj-1"
    assert require_client_project_id(client) == "proj-1"


def test_require_client_project_id_rejects_missing() -> None:
    client = DeepOriginClient.from_local()
    client.project_id = None
    with pytest.raises(DeepOriginException, match="client.project_id"):
        require_client_project_id(client)


def test_require_client_project_id_rejects_entity_mismatch() -> None:
    client = DeepOriginClient.from_local()
    client.project_id = "proj-1"
    with pytest.raises(DeepOriginException, match="does not match"):
        require_client_project_id(client, entity_project_id="proj-2")
