"""Tests for DeepOriginClient Tools API wrapper."""

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


def test_tools_list(mock_client):
    """Test listing all tools."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"tools": []}
    mock_response.raise_for_status = MagicMock()
    mock_client._client.get.return_value = mock_response

    result = mock_client.tools.list()

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
