"""Tests for DeepOriginClient construction and tag functionality."""

from unittest.mock import patch

from deeporigin.platform.client import DeepOriginClient


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


def test_client_tag_used_in_function_run():
    """Client's tag is used in function runs when tag parameter is None."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local()
    client.tag = "test-function-tag"

    captured_body = {}

    original_post_json = client.post_json

    def mock_post_json(endpoint: str, *, body: dict) -> dict:
        nonlocal captured_body
        captured_body = body.copy()
        return {
            "status": "Completed",
            "functionOutputs": {"result": "success"},
        }

    client.post_json = mock_post_json

    with patch.object(
        client.clusters, "get_default_cluster_id", return_value="test-cluster-id"
    ):
        response = client.functions.run(
            key="test.function",
            params={"test": "param"},
        )

        assert "tag" in captured_body
        assert captured_body["tag"] == "test-function-tag"
        assert response["status"] == "Completed"

    client.post_json = original_post_json


def test_client_tag_explicit_override():
    """Explicitly passing tag parameter overrides client's default tag."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local()
    client.tag = "default-tag"

    captured_body = {}

    original_post_json = client.post_json

    def mock_post_json(endpoint: str, *, body: dict) -> dict:
        nonlocal captured_body
        captured_body = body.copy()
        return {
            "status": "Completed",
            "functionOutputs": {"result": "success"},
        }

    client.post_json = mock_post_json

    with patch.object(
        client.clusters, "get_default_cluster_id", return_value="test-cluster-id"
    ):
        response = client.functions.run(
            key="test.function",
            params={"test": "param"},
            tag="override-tag",
        )

        assert "tag" in captured_body
        assert captured_body["tag"] == "override-tag"
        assert captured_body["tag"] != "default-tag"
        assert response["status"] == "Completed"

    client.post_json = original_post_json


def test_functions_run_includes_client_project_id():
    """When client.project_id is set, function run body includes projectId."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local()
    client.project_id = "test-project-uuid"

    captured_body = {}

    original_post_json = client.post_json

    def mock_post_json(endpoint: str, *, body: dict) -> dict:
        nonlocal captured_body
        captured_body = body.copy()
        return {
            "status": "Completed",
            "functionOutputs": {"result": "success"},
        }

    client.post_json = mock_post_json

    with patch.object(
        client.clusters, "get_default_cluster_id", return_value="test-cluster-id"
    ):
        client.functions.run(
            key="test.function",
            params={"test": "param"},
        )

        assert captured_body["projectId"] == "test-project-uuid"

    client.post_json = original_post_json


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


def test_client_tag_none_explicitly_passed():
    """Explicitly passing tag=None in function run uses the client's default tag."""
    DeepOriginClient.close_all()

    client = DeepOriginClient.from_local()
    client.tag = "default-tag"

    captured_body = {}

    original_post_json = client.post_json

    def mock_post_json(endpoint: str, *, body: dict) -> dict:
        nonlocal captured_body
        captured_body = body.copy()
        return {
            "status": "Completed",
            "functionOutputs": {"result": "success"},
        }

    client.post_json = mock_post_json

    with patch.object(
        client.clusters, "get_default_cluster_id", return_value="test-cluster-id"
    ):
        response = client.functions.run(
            key="test.function",
            params={"test": "param"},
            tag=None,
        )

        # None means use client.tag
        assert "tag" in captured_body
        assert captured_body["tag"] == "default-tag"
        assert response["status"] == "Completed"

    client.post_json = original_post_json


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
