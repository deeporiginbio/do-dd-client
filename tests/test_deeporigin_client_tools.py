"""Tests for DeepOriginClient Tools, Functions, and Clusters API wrappers."""

from unittest.mock import MagicMock, patch

import pytest

from deeporigin.platform.client import DeepOriginClient


@pytest.fixture
def mock_client():
    """Create a mock DeepOriginClient for testing."""
    with patch("deeporigin.platform.client.httpx.Client") as mock_httpx_client:
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"key": "test-tool", "version": "1.0.0"},
            {"key": "test-tool", "version": "2.0.0"},
        ]
        mock_response.raise_for_status = MagicMock()
        mock_httpx_client.return_value.get.return_value = mock_response

        client = DeepOriginClient(
            token="test-token",
            org_key="test-org",
            base_url="https://api.test.deeporigin.io/",
        )
        yield client


def test_tools_get_all(mock_client):
    """Test listing all tools."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"tools": []}
    mock_response.raise_for_status = MagicMock()
    mock_client._client.get.return_value = mock_response

    result = mock_client.tools.get_all()

    assert isinstance(result, dict)
    mock_client._client.get.assert_called_once_with(
        "/tools/protected/tools/definitions"
    )


def test_tools_get_by_key(mock_client):
    """Test getting tool definitions by key."""
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {"key": "test-tool", "version": "1.0.0"},
        {"key": "test-tool", "version": "2.0.0"},
    ]
    mock_response.raise_for_status = MagicMock()
    mock_client._client.get.return_value = mock_response

    result = mock_client.tools.get_by_key(tool_key="test-tool")

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["key"] == "test-tool"
    mock_client._client.get.assert_called_once_with(
        "/tools/protected/tools/test-tool/definitions"
    )


def test_tools_get_by_key_empty_result(mock_client):
    """Test getting tool definitions by key when no versions exist."""
    mock_response = MagicMock()
    mock_response.json.return_value = []
    mock_response.raise_for_status = MagicMock()
    mock_client._client.get.return_value = mock_response

    result = mock_client.tools.get_by_key(tool_key="nonexistent-tool")

    assert isinstance(result, list)
    assert len(result) == 0
    mock_client._client.get.assert_called_once_with(
        "/tools/protected/tools/nonexistent-tool/definitions"
    )


def test_functions_run_latest(mock_client):
    """Test running the latest version of a function."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"executionId": "exec-123"}
    mock_response.raise_for_status = MagicMock()
    mock_client._client.post.return_value = mock_response

    result = mock_client.functions.run_latest(
        key="test-function",
        params={"input": "test"},
        cluster_id="cluster-123",
    )

    assert isinstance(result, dict)
    assert result["executionId"] == "exec-123"
    mock_client._client.post.assert_called_once_with(
        "/tools/test-org/functions/test-function",
        json={"params": {"input": "test"}, "clusterId": "cluster-123"},
    )


def test_functions_run_latest_with_tag(mock_client):
    """Test running the latest version of a function with a tag."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"executionId": "exec-456"}
    mock_response.raise_for_status = MagicMock()
    mock_client._client.post.return_value = mock_response

    result = mock_client.functions.run_latest(
        key="test-function",
        params={"input": "test"},
        cluster_id="cluster-123",
        tag="my-tag",
    )

    assert isinstance(result, dict)
    assert result["executionId"] == "exec-456"
    mock_client._client.post.assert_called_once_with(
        "/tools/test-org/functions/test-function",
        json={
            "params": {"input": "test"},
            "clusterId": "cluster-123",
            "tag": "my-tag",
        },
    )


def test_functions_run_latest_with_default_cluster_id(mock_client):
    """Test running the latest version of a function with default cluster ID."""
    # Mock the clusters.list() response for get_default_cluster_id
    clusters_response = MagicMock()
    clusters_response.json.return_value = {
        "data": [
            {"id": "cluster-dev-1", "hostname": "dev-cluster.example.com"},
            {"id": "cluster-prod-1", "hostname": "prod-cluster.example.com"},
        ],
        "pagination": {"count": 2},
    }
    clusters_response.raise_for_status = MagicMock()
    mock_client._client.get.return_value = clusters_response

    # Mock the function execution response
    exec_response = MagicMock()
    exec_response.json.return_value = {"executionId": "exec-789"}
    exec_response.raise_for_status = MagicMock()
    mock_client._client.post.return_value = exec_response

    result = mock_client.functions.run_latest(
        key="test-function",
        params={"input": "test"},
    )

    assert isinstance(result, dict)
    assert result["executionId"] == "exec-789"
    # Verify it called clusters.list() to get default cluster ID
    assert mock_client._client.get.call_count == 1
    # Verify it used the default cluster ID in the POST request
    mock_client._client.post.assert_called_once_with(
        "/tools/test-org/functions/test-function",
        json={"params": {"input": "test"}, "clusterId": "cluster-prod-1"},
    )


def test_clusters_list(mock_client):
    """Test listing all clusters."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {"id": "cluster-1", "hostname": "cluster1.example.com"},
            {"id": "cluster-2", "hostname": "cluster2.example.com"},
        ],
        "pagination": {"count": 2},
    }
    mock_response.raise_for_status = MagicMock()
    mock_client._client.get.return_value = mock_response

    result = mock_client.clusters.list()

    assert isinstance(result, dict)
    assert "data" in result
    assert len(result["data"]) == 2
    assert result["data"][0]["id"] == "cluster-1"
    mock_client._client.get.assert_called_once_with(
        "/tools/test-org/clusters",
        params=None,
    )


def test_clusters_list_with_params(mock_client):
    """Test listing clusters with query parameters."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [{"id": "cluster-1", "hostname": "cluster1.example.com"}],
        "pagination": {"count": 1},
    }
    mock_response.raise_for_status = MagicMock()
    mock_client._client.get.return_value = mock_response

    result = mock_client.clusters.list(
        page=1,
        page_size=10,
        order="hostname? asc",
        filter="enabled=true",
    )

    assert isinstance(result, dict)
    assert "data" in result
    assert len(result["data"]) == 1
    mock_client._client.get.assert_called_once_with(
        "/tools/test-org/clusters",
        params={
            "page": 1,
            "pageSize": 10,
            "order": "hostname? asc",
            "filter": "enabled=true",
        },
    )


def test_clusters_list_partial_params(mock_client):
    """Test listing clusters with some query parameters."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": [], "pagination": {"count": 0}}
    mock_response.raise_for_status = MagicMock()
    mock_client._client.get.return_value = mock_response

    result = mock_client.clusters.list(page=0, page_size=20)

    assert isinstance(result, dict)
    assert "data" in result
    mock_client._client.get.assert_called_once_with(
        "/tools/test-org/clusters",
        params={"page": 0, "pageSize": 20},
    )


def test_clusters_get_default_cluster_id(mock_client):
    """Test getting the default cluster ID."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {"id": "cluster-dev-1", "hostname": "dev-cluster.example.com"},
            {"id": "cluster-prod-1", "hostname": "prod-cluster.example.com"},
            {"id": "cluster-prod-2", "hostname": "another-prod.example.com"},
        ],
        "pagination": {"count": 3},
    }
    mock_response.raise_for_status = MagicMock()
    mock_client._client.get.return_value = mock_response

    cluster_id = mock_client.clusters.get_default_cluster_id()

    assert cluster_id == "cluster-prod-1"
    mock_client._client.get.assert_called_once_with(
        "/tools/test-org/clusters",
        params=None,
    )


def test_clusters_get_default_cluster_id_no_non_dev_clusters(mock_client):
    """Test getting default cluster ID when only dev clusters exist."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {"id": "cluster-dev-1", "hostname": "dev-cluster.example.com"},
            {"id": "cluster-dev-2", "hostname": "another-dev.example.com"},
        ],
        "pagination": {"count": 2},
    }
    mock_response.raise_for_status = MagicMock()
    mock_client._client.get.return_value = mock_response

    with pytest.raises(RuntimeError, match="No clusters found"):
        mock_client.clusters.get_default_cluster_id()


def test_files_list_files_in_dir(mock_client):
    """Test listing files in a directory."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {"Key": "entities/file1.txt", "Size": 1024},
            {"Key": "entities/file2.txt", "Size": 2048},
            {"Key": "entities/subdir/file3.txt", "Size": 512},
        ],
    }
    mock_response.raise_for_status = MagicMock()
    mock_client._client.get.return_value = mock_response

    result = mock_client.files.list_files_in_dir(file_path="entities/")

    assert isinstance(result, list)
    assert len(result) == 3
    assert result[0] == "entities/file1.txt"
    assert result[1] == "entities/file2.txt"
    assert result[2] == "entities/subdir/file3.txt"
    mock_client._client.get.assert_called_once_with(
        "/files/test-org/directory/entities/",
        params={"recursive": True},
    )


def test_files_list_files_in_dir_with_params(mock_client):
    """Test listing files in a directory with additional parameters."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [{"Key": "entities/file1.txt", "Size": 1024}],
        "continuationToken": "token-123",
    }
    mock_response.raise_for_status = MagicMock()
    mock_client._client.get.return_value = mock_response

    result = mock_client.files.list_files_in_dir(
        file_path="entities/",
        recursive=False,
        last_count=10,
        continuation_token="token-123",
        delimiter="/",
        max_keys=100,
        prefix="entities/subdir/",
    )

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0] == "entities/file1.txt"
    mock_client._client.get.assert_called_once_with(
        "/files/test-org/directory/entities/",
        params={
            "last-count": "10",
            "continuation-token": "token-123",
            "delimiter": "/",
            "max-orgKeys": 100,
            "prefix": "entities/subdir/",
        },
    )


def test_files_list_files_in_dir_empty_response(mock_client):
    """Test listing files in a directory when no files are found."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": []}
    mock_response.raise_for_status = MagicMock()
    mock_client._client.get.return_value = mock_response

    result = mock_client.files.list_files_in_dir(file_path="empty_dir/")

    assert isinstance(result, list)
    assert len(result) == 0
    mock_client._client.get.assert_called_once_with(
        "/files/test-org/directory/empty_dir/",
        params={"recursive": True},
    )


def test_files_upload_file(mock_client, tmp_path):
    """Test uploading a file."""
    # Create a temporary test file
    test_file = tmp_path / "test_file.txt"
    test_file.write_text("test content")

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "eTag": "etag-123",
        "s3": {
            "bucketName": "test-bucket",
            "bucketRegion": "us-east-1",
            "bucketorgKey": "test-key",
        },
    }
    mock_response.raise_for_status = MagicMock()
    mock_client._client.put.return_value = mock_response

    result = mock_client.files.upload_file(
        local_path=str(test_file),
        remote_path="test/uploaded_file.txt",
    )

    assert isinstance(result, dict)
    assert result["eTag"] == "etag-123"
    assert "s3" in result

    # Verify the PUT request was made with correct parameters
    mock_client._client.put.assert_called_once()
    call_args = mock_client._client.put.call_args
    assert call_args[0][0] == "/files/test-org/test/uploaded_file.txt"
    assert "files" in call_args[1]
    assert "file" in call_args[1]["files"]
    file_tuple = call_args[1]["files"]["file"]
    assert file_tuple[0] == "test_file.txt"
    assert file_tuple[1] == b"test content"
    assert file_tuple[2] == "application/octet-stream"


def test_files_upload_file_with_path_objects(mock_client, tmp_path):
    """Test uploading a file using Path objects."""
    from pathlib import Path

    # Create a temporary test file
    test_file = tmp_path / "test_file.txt"
    test_file.write_text("test content")

    mock_response = MagicMock()
    mock_response.json.return_value = {"eTag": "etag-456"}
    mock_response.raise_for_status = MagicMock()
    mock_client._client.put.return_value = mock_response

    result = mock_client.files.upload_file(
        local_path=Path(test_file),
        remote_path=Path("test/uploaded_file.txt"),
    )

    assert isinstance(result, dict)
    assert result["eTag"] == "etag-456"
    mock_client._client.put.assert_called_once()
