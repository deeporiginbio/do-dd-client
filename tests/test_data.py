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


def test_create_ligand_lv1():
    """Test creating a ligand."""
    client = DeepOriginClient()
    response = client.data.create_ligand(
        project_id="\\x0011223344556677",
        canonical_smiles="CCOc1ccc2nc(S(=O)(=O)N3CCN(CC3)C)c(N)c2c1",
        inchi_key="BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
        inchi="InChI=1S/C20H24N4O4S/.../h1-4,6-9H,5,10-14H2,(H,22,23)",
        smiles="CCOc1ccc2nc(S(=O)(=O)N3CCN(CC3)C)c(N)c2c1",
        name="Compound-12345",
        formal_charge=0,
        hbond_donor_count=1,
        hbond_acceptor_count=6,
        rotatable_bond_count=5,
        tpsa=85.12,
        molecular_weight=447.5,
        variant_name_tag="",
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "canonical_id" in response, "Expected 'canonical_id' key in response"
    assert "version" in response, "Expected 'version' key in response"
    assert response["version"] == 1, "Expected version to be 1"
    assert "name" in response, "Expected 'name' key in response"
    assert response["name"] == "Compound-12345", "Expected name to match"
    assert "canonical_smiles" in response, "Expected 'canonical_smiles' key in response"
    assert (
        response["canonical_smiles"] == "CCOc1ccc2nc(S(=O)(=O)N3CCN(CC3)C)c(N)c2c1"
    ), "Expected canonical_smiles to match"


def test_list_projects_lv1():
    """Test listing projects."""
    client = DeepOriginClient()
    response = client.data.list_projects()

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"
    assert "count" in response, "Expected 'count' key in response"
