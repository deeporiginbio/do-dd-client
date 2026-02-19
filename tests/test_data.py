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
    smiles = "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12"
    response = client.data.create_ligand(
        smiles=smiles,
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
    assert "data" in response, "Expected 'data' key in response"
    data = response["data"]
    assert isinstance(data, dict), "Expected 'data' to be a dictionary"
    assert "id" in data, "Expected 'id' key in data"
    assert "version" in data, "Expected 'version' key in data"
    assert data["version"] == 1, "Expected version to be 1"
    assert "name" in data, "Expected 'name' key in data"
    assert data["name"] == "Compound-12345", "Expected name to match"
    assert "canonical_smiles" in data, "Expected 'canonical_smiles' key in data"
    assert "meta" in response, "Expected 'meta' key in response"
    assert response["meta"]["inserted"] == 1, "Expected inserted to be 1"


def test_create_protein_lv1():
    """Test creating a protein."""
    client = DeepOriginClient()
    response = client.data.create_protein(
        file_path="entities/proteins/db4aa32e2e8ffa976a60004a8361b86427a2e5653a6623bb60b7913445902549.pdb",
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], dict), "Expected 'data' to be a dictionary"
    assert "id" in response["data"], "Expected 'id' key in response data"
    assert "version" in response["data"], "Expected 'version' key in response data"
    assert response["data"]["version"] == 1, "Expected version to be 1"
    assert "file_path" in response["data"], "Expected 'file_path' key in response data"
    assert (
        response["data"]["file_path"]
        == "entities/proteins/db4aa32e2e8ffa976a60004a8361b86427a2e5653a6623bb60b7913445902549.pdb"
    ), "Expected file_path to match"
    assert "meta" in response, "Expected 'meta' key in response"
    assert "inserted" in response["meta"], "Expected 'inserted' key in meta"
    assert response["meta"]["inserted"] == 1, "Expected inserted to be 1"


def test_list_projects_lv1():
    """Test listing projects."""
    client = DeepOriginClient()
    response = client.data.list_projects()

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_get_ligand_lv1():
    """Test getting a ligand by ID."""
    client = DeepOriginClient()
    response = client.data.get_ligand(id="08B05B1GDYWJR")

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "id" in response, "Expected 'id' key in response"
    assert response["id"] == "08B05B1GDYWJR", "Expected id to match"
    assert "smiles" in response, "Expected 'smiles' key in response"
    assert "name" in response, "Expected 'name' key in response"
    assert response["name"] == "cmpd 4 (Crotyl)", "Expected name to match"
    assert "molecular_weight" in response, "Expected 'molecular_weight' key in response"
    assert abs(response["molecular_weight"] - 335.16337691200056) < 1e-10, (
        "Expected molecular_weight to match"
    )


def test_get_protein_lv1():
    """Test getting a protein by ID."""
    client = DeepOriginClient()
    response = client.data.get_protein(id="08AD337N5YV4Y")

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "id" in response, "Expected 'id' key in response"
    assert response["id"] == "08AD337N5YV4Y", "Expected id to match"
    assert "file_path" in response, "Expected 'file_path' key in response"
    assert (
        response["file_path"]
        == "entities/proteins/db4aa32e2e8ffa976a60004a8361b86427a2e5653a6623bb60b7913445902549.pdb"
    ), "Expected file_path to match"
    assert "subtable_name" in response, "Expected 'subtable_name' key in response"
    assert response["subtable_name"] == "proteins", "Expected subtable_name to match"
