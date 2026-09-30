"""Tests for client project scoping helpers."""

from __future__ import annotations

import pytest

from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.project_scope import (
    adopt_client_project_from_execution_dto,
    execution_project_scope,
    require_client_project_id,
)


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


def test_execution_project_scope_clears_client_for_null_project_id() -> None:
    client = DeepOriginClient.from_local()
    client.project_id = "proj-notebook"
    dto = {"projectId": None}
    with execution_project_scope(client, dto):
        assert client.project_id is None
    assert client.project_id == "proj-notebook"


def test_execution_project_scope_noop_when_project_id_missing() -> None:
    client = DeepOriginClient.from_local()
    client.project_id = "proj-notebook"
    with execution_project_scope(client, {}):
        assert client.project_id == "proj-notebook"


def test_adopt_client_project_from_execution_dto_sets_project() -> None:
    client = DeepOriginClient.from_local()
    client.project_id = "proj-notebook"
    adopt_client_project_from_execution_dto(
        client,
        {"projectId": "proj-exec"},
    )
    assert client.project_id == "proj-exec"


def test_adopt_client_project_from_execution_dto_clears_when_null() -> None:
    client = DeepOriginClient.from_local()
    client.project_id = "proj-notebook"
    adopt_client_project_from_execution_dto(client, {"projectId": None})
    assert client.project_id is None
