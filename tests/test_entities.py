"""Tests for the Entities API wrapper."""

from unittest.mock import MagicMock

import httpx

from deeporigin.platform import DeepOriginClient


def test_delete_entity():
    """Test that delete sends a DELETE request to the correct URL."""
    client = DeepOriginClient()

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.json.return_value = {"deleted": 1}
    mock_response.raise_for_status = MagicMock()

    original_delete = client._client.delete
    client._client.delete = MagicMock(return_value=mock_response)

    try:
        result = client.entities.delete(entity="proteins", entity_id="08BSPN61NYVE3")

        assert result == {"deleted": 1}
        client._client.delete.assert_called_once()
        call_args = client._client.delete.call_args
        assert "/data-platform/deeporigin/proteins/08BSPN61NYVE3" in call_args[0][0]
    finally:
        client._client.delete = original_delete


def test_delete_entity_ligand():
    """Test that delete works for ligand entities."""
    client = DeepOriginClient()

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.json.return_value = {"deleted": 1}
    mock_response.raise_for_status = MagicMock()

    original_delete = client._client.delete
    client._client.delete = MagicMock(return_value=mock_response)

    try:
        result = client.entities.delete(entity="ligands", entity_id="ABC123")

        assert result == {"deleted": 1}
        call_args = client._client.delete.call_args
        assert "/data-platform/deeporigin/ligands/ABC123" in call_args[0][0]
    finally:
        client._client.delete = original_delete
