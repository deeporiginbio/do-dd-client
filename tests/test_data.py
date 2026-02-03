"""Tests for the Data Platform API wrapper."""

import pytest

from deeporigin.platform.client import DeepOriginClient


def test_data_platform_health_lv1():
    """Test the data platform health endpoint."""
    client = DeepOriginClient()
    response = client.data.health()

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "status" in response, "Expected 'status' key in response"
    assert response["status"] == "ok", "Expected status to be 'ok'"


def test_search_ligands_with_results_lv1():
    """Test searching ligands with results."""
    client = DeepOriginClient()
    response = client.data.search_ligands_with_results(
        limit=10,
        experiments=[{"toolId": "test-tool"}],
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_entity_lv1():
    """Test searching an entity."""
    client = DeepOriginClient()
    response = client.data.search("ligands")

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_entity_invalid_entity():
    """Test searching with an invalid entity raises ValueError."""
    client = DeepOriginClient()
    with pytest.raises(ValueError, match="Invalid entity 'invalid_table'"):
        client.data.search("invalid_table")


def test_search_ligands_lv1():
    """Test searching ligands using convenience method."""
    client = DeepOriginClient()
    response = client.data.search_ligands()

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_ligands_molecular_weight():
    """Test searching ligands with molecular weight filters."""
    client = DeepOriginClient()
    response = client.data.search_ligands(
        min_molecular_weight=250, max_molecular_weight=550
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_proteins_lv1():
    """Test searching proteins using convenience method."""
    client = DeepOriginClient()
    response = client.data.search_proteins()

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_proteins_molecular_weight():
    """Test searching proteins with molecular weight filters."""
    client = DeepOriginClient()
    response = client.data.search_proteins(
        min_molecular_weight=250, max_molecular_weight=550
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_proteins_sequence():
    """Test searching proteins with sequence filter."""
    client = DeepOriginClient()
    response = client.data.search_proteins(
        sequence="MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHSLAKWKRQTLGQHDFSAGEGLYTHMKALRPDEDRLSPLHSVYVDQWDWERVMGDGERQFSTLKSTVEAIWAGIKATEAAVSEEFGLAPFLPDQIHFVHSQELLSRYPDLDAKGRERAIAKDLGAVFLVGIGGKLSDGHRHDVRAPDYDDWSTPSELGHAGLNGDILVWNPVLEDAFELSSMGIRVDADTLKHQLALTGDEDRLELEWHQALLRGEMPQTIGGGIGQSRLTMLLLQLPHIGQVQAGVWPAAVRESVPSLL"
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_list_models_lv1():
    """Test listing models."""
    client = DeepOriginClient()
    response = client.data.list_models()

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "models" in response, "Expected 'models' key in response"
    assert isinstance(response["models"], list), "Expected 'models' to be a list"
    assert len(response["models"]) > 0, "Expected at least one model"
    # Verify structure of first model
    model = response["models"][0]
    assert "tableName" in model, "Expected 'tableName' key in model"
    assert "visibility" in model, "Expected 'visibility' key in model"
    assert model["visibility"] == "public", "Expected visibility to be 'public'"
