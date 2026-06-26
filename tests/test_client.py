"""Tests for DeepOriginClient construction and tag functionality."""

from datetime import datetime, timezone
import json

import pytest

from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.constants import TOOL_EXECUTION_POST_TIMEOUT_SECONDS


def test_client_tag_set_on_creation():
    """Tag can be set directly after creating a client."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local()
    client.tag = "test-tag-1"
    assert client.tag == "test-tag-1"


def test_org_key_set_after_creation():
    """Organization key can be overridden on the client after construction."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local()
    assert client.org_key == "deeporigin"

    client.org_key = "foo-bar"
    assert client.org_key == "foo-bar"


def test_client_tag_set_on_existing_client():
    """Tag can be set on an existing client instance."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local()
    assert client.tag is None

    client.tag = "test-tag-2"
    assert client.tag == "test-tag-2"


def test_client_tag_mutable_on_shared_instance():
    """Tag is a mutable attribute; updating it affects all references to the same instance."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local()
    client.tag = "tag-a"

    # Same singleton: second call returns the same object
    client2 = DeepOriginClient.from_local()
    assert client2 is client
    assert client2.tag == "tag-a"

    client2.tag = "tag-b"
    assert client.tag == "tag-b"


def _stub_post_json_capturing_body(client: DeepOriginClient) -> dict:
    """Replace ``client.post_json`` with a stub that records the request body.

    Returns the captured-body dict (mutated in place by the stub) so tests can
    assert on the JSON sent to ``executions.create``.
    """
    captured: dict = {}

    def mock_post_json(
        endpoint: str,
        *,
        body: dict,
        **kwargs: object,
    ) -> dict:
        captured.clear()
        captured.update(body)
        captured["__endpoint__"] = endpoint
        captured["__timeout__"] = kwargs.get("timeout")
        return {
            "executionId": "exec-stub",
            "status": "Completed",
            "jobOutputs": [{"result": "success"}],
            "tool": {
                "key": "test.tool",
                "version": "1.0.0",
            },
        }

    client.post_json = mock_post_json  # type: ignore[method-assign]
    return captured


def test_executions_create_includes_app_and_session():
    """``executions.create`` propagates the client's ``_app`` and ``_session``."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local(_session="sess-1")
    captured = _stub_post_json_capturing_body(client)

    client.clusters.get_default_cluster_id = (  # type: ignore[method-assign]
        lambda: "test-cluster-id"
    )

    response = client.executions.create(
        tool_key="test.tool",
        tool_version="1.0.0",
        data={"inputs": {"test": "param"}, "outputs": {}, "metadata": {}},
    )

    assert captured["app"] == "python-client"
    assert captured["session"] == "sess-1"
    assert captured["clusterId"] == "test-cluster-id"
    assert response["status"] == "Completed"


def test_executions_create_uses_long_timeout():
    """``executions.create`` passes ``TOOL_EXECUTION_POST_TIMEOUT_SECONDS`` to httpx."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local()
    captured = _stub_post_json_capturing_body(client)

    client.clusters.get_default_cluster_id = (  # type: ignore[method-assign]
        lambda: "test-cluster-id"
    )

    client.executions.create(
        tool_key="test.tool",
        tool_version="1.0.0",
        data={"inputs": {"test": "param"}, "outputs": {}, "metadata": {}},
    )

    assert captured["__timeout__"] == TOOL_EXECUTION_POST_TIMEOUT_SECONDS


def test_executions_create_includes_client_project_id():
    """When ``client.project_id`` is set, the request body includes ``projectId``."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local()
    client.project_id = "test-project-uuid"
    captured = _stub_post_json_capturing_body(client)

    client.clusters.get_default_cluster_id = (  # type: ignore[method-assign]
        lambda: "test-cluster-id"
    )

    client.executions.create(
        tool_key="test.tool",
        tool_version="1.0.0",
        data={"inputs": {"test": "param"}, "outputs": {}, "metadata": {}},
    )

    assert captured["projectId"] == "test-project-uuid"


def test_executions_create_includes_client_tag():
    """``executions.create`` sends ``client.tag`` as ``tag`` when set."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local()
    client.tag = "billing-tag-abc"
    captured = _stub_post_json_capturing_body(client)

    client.clusters.get_default_cluster_id = (  # type: ignore[method-assign]
        lambda: "test-cluster-id"
    )

    client.executions.create(
        tool_key="test.tool",
        tool_version="1.0.0",
        data={"inputs": {"test": "param"}, "outputs": {}, "metadata": {}},
    )

    assert captured["tag"] == "billing-tag-abc"


def test_executions_create_data_tag_overrides_client_tag():
    """An explicit ``tag`` in ``data`` is not replaced by ``client.tag``."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local()
    client.tag = "client-default"
    captured = _stub_post_json_capturing_body(client)

    client.clusters.get_default_cluster_id = (  # type: ignore[method-assign]
        lambda: "test-cluster-id"
    )

    client.executions.create(
        tool_key="test.tool",
        tool_version="1.0.0",
        data={
            "inputs": {},
            "outputs": {},
            "metadata": {},
            "tag": "explicit-tag",
        },
    )

    assert captured["tag"] == "explicit-tag"


def test_executions_create_targets_tool_endpoint():
    """``executions.create`` POSTs to ``/tools/{org}/tools/{key}/{version}/executions``."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local()
    captured = _stub_post_json_capturing_body(client)

    client.clusters.get_default_cluster_id = (  # type: ignore[method-assign]
        lambda: "test-cluster-id"
    )

    client.executions.create(
        tool_key="test.tool",
        tool_version="1.0.0",
        data={"inputs": {"a": 1}, "outputs": {}, "metadata": {}},
    )

    assert captured["__endpoint__"].endswith("/tools/test.tool/1.0.0/executions")


def test_executions_list_includes_project_id_filter():
    """``executions.list(project_id=...)`` sends a tools-service filter on ``projectId``."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local()
    captured: dict = {}

    def mock_get_json(path: str, **kwargs: object) -> dict:
        captured["path"] = path
        captured["params"] = kwargs.get("params")
        return {"data": [], "count": 0}

    client.get_json = mock_get_json  # type: ignore[method-assign]

    client.executions.list(project_id="proj-filter-1")

    params = captured["params"]
    assert params is not None
    filt = json.loads(str(params["filter"]))
    assert filt["projectId"] == "proj-filter-1"


def test_executions_list_includes_created_after_filter():
    """``executions.list(created_after=...)`` sends MikroORM ``$gt`` on ``createdAt``."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local()
    captured: dict = {}

    def mock_get_json(path: str, **kwargs: object) -> dict:
        captured["params"] = kwargs.get("params")
        return {"data": [], "count": 0}

    client.get_json = mock_get_json  # type: ignore[method-assign]

    cutoff = datetime(2026, 5, 7, 15, 13, 25, 254000, tzinfo=timezone.utc)
    client.executions.list(created_after=cutoff)

    params = captured["params"]
    assert params is not None
    filt = json.loads(str(params["filter"]))
    assert filt["createdAt"] == {"$gt": "2026-05-07T15:13:25.254Z"}


def test_executions_list_created_after_accepts_iso_string():
    """String ``created_after`` is forwarded without rewriting."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local()
    captured: dict = {}

    def mock_get_json(path: str, **kwargs: object) -> dict:
        captured["params"] = kwargs.get("params")
        return {"data": [], "count": 0}

    client.get_json = mock_get_json  # type: ignore[method-assign]

    iso = "2026-01-02T00:00:00.000Z"
    client.executions.list(created_after=iso)

    params = captured["params"]
    assert params is not None
    filt = json.loads(str(params["filter"]))
    assert filt["createdAt"] == {"$gt": iso}


def test_no_arg_constructor_returns_same_instance():
    """DeepOriginClient() called twice with the same resolved config returns the same instance."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local()
    client.tag = "test-2"
    assert client.tag == "test-2"

    # Second call with same resolved config returns the cached instance
    client2 = DeepOriginClient.from_local()
    assert client2 is client
    assert client2.tag == "test-2"


def test_client_app_session_same_params_same_instance():
    """Same (base_url, token, org_key, project_id, _app, _session) yields same cached instance."""
    DeepOriginClient.close_all()

    client1 = DeepOriginClient.from_local()
    session1 = client1._session
    assert client1._app == "python-client"

    client2 = DeepOriginClient.from_local()
    assert client2 is client1
    assert client2._session == session1


def test_client_app_session_different_app_different_instances():
    """Different _app yields different cached instances."""
    DeepOriginClient.close_all()

    client1 = DeepOriginClient.from_local(_app="python-client")
    client2 = DeepOriginClient.from_local(_app="other-app")

    assert client2 is not client1
    assert client1._app == "python-client"
    assert client2._app == "other-app"


def test_client_app_session_different_session_different_instances():
    """Different _session yields different cached instances."""
    DeepOriginClient.close_all()

    client1 = DeepOriginClient.from_local(_session="session-a")
    client2 = DeepOriginClient.from_local(_session="session-b")

    assert client2 is not client1
    assert client1._session == "session-a"
    assert client2._session == "session-b"


def test_client_close_detaches_from_registry():
    """close() removes the instance from the singleton registry."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local()
    assert len(DeepOriginClient._instances) == 1

    client.close()
    assert len(DeepOriginClient._instances) == 0


def test_client_close_all_clears_registry():
    """close_all() closes all cached instances and clears the registry."""
    DeepOriginClient.close_all()

    DeepOriginClient.from_local(_app="app-a")
    DeepOriginClient.from_local(_app="app-b")
    assert len(DeepOriginClient._instances) == 2

    DeepOriginClient.close_all()
    assert len(DeepOriginClient._instances) == 0


def test_from_headers_accepts_lowercase_dict_keys():
    """``dict(request.headers)`` uses lowercase keys; ``from_headers`` still resolves."""
    DeepOriginClient.close_all()
    headers = {
        "x-do-auth-token": "tok",
        "x-do-org-key": "org",
        "x-do-base-url": "https://api.example.com",
    }
    client = DeepOriginClient.from_headers(headers)
    assert client.token == "tok"
    assert client.org_key == "org"
    assert client.base_url == "https://api.example.com/"


def test_from_headers_accepts_canonical_header_names():
    """Canonical ``X-Do-*`` header names still work."""
    DeepOriginClient.close_all()
    headers = {
        "X-Do-Auth-Token": "tok2",
        "X-Do-Org-Key": "org2",
        "X-Do-Base-Url": "https://api2.example.com",
    }
    client = DeepOriginClient.from_headers(headers)
    assert client.token == "tok2"
    assert client.org_key == "org2"
    assert client.base_url == "https://api2.example.com/"


def test_from_headers_optional_project_id_lowercase_key():
    """``X-Do-Project-Id`` is read when the dict uses lowercase keys."""
    DeepOriginClient.close_all()
    headers = {
        "x-do-auth-token": "t",
        "x-do-org-key": "o",
        "x-do-base-url": "https://api.example.com",
        "x-do-project-id": "proj-1",
    }
    client = DeepOriginClient.from_headers(headers)
    assert client.project_id == "proj-1"


def test_from_headers_still_raises_when_required_missing():
    """Missing required headers still raises ``ValueError``."""
    DeepOriginClient.close_all()
    headers = {"x-do-auth-token": "t"}
    with pytest.raises(ValueError) as exc_info:
        DeepOriginClient.from_headers(headers)
    msg = str(exc_info.value)
    assert "X-Do-Org-Key" in msg
    assert "X-Do-Base-Url" in msg
