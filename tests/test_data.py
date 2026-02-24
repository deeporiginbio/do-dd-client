"""Tests for the Data Platform API wrapper."""

import uuid

import pytest

from deeporigin.platform.client import DeepOriginClient


def test_data_platform_health_lv1():
    """Test the data platform health endpoint."""
    client = DeepOriginClient()
    response = client.data.health()

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "status" in response, "Expected 'status' key in response"
    assert response["status"] == "ok", "Expected status to be 'ok'"


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


def test_search_ligands_molecular_weight_lv1():
    """Test searching ligands with molecular weight filters."""
    client = DeepOriginClient()
    response = client.data.search_ligands(
        min_molecular_weight=250,
        max_molecular_weight=550,
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_ligands_smiles_list_lv1():
    """Test searching ligands by a list of SMILES strings."""
    client = DeepOriginClient()

    # First, search for a few existing ligands to get known canonical SMILES
    existing = client.data.search_ligands(limit=3)
    assert len(existing["data"]) >= 2, "Need at least 2 existing ligands for this test"

    known_smiles = [lig["canonical_smiles"] for lig in existing["data"][:2]]

    response = client.data.search_ligands(smiles_list=known_smiles)

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"
    assert len(response["data"]) >= 2, "Expected at least 2 results"

    returned_smiles = {lig["canonical_smiles"] for lig in response["data"]}
    for s in known_smiles:
        assert s in returned_smiles, f"Expected {s} in results"


def test_search_ligands_smiles_list_mutually_exclusive():
    """Test that smiles_list cannot be used with smiles or canonical_smiles."""
    client = DeepOriginClient()

    with pytest.raises(ValueError, match="mutually exclusive"):
        client.data.search_ligands(smiles_list=["C"], smiles="C")

    with pytest.raises(ValueError, match="mutually exclusive"):
        client.data.search_ligands(smiles_list=["C"], canonical_smiles="C")


def test_search_proteins_lv1():
    """Test searching proteins using convenience method."""
    client = DeepOriginClient()
    response = client.data.search_proteins()

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_proteins_molecular_weight_lv1():
    """Test searching proteins with molecular weight filters."""
    client = DeepOriginClient()
    response = client.data.search_proteins(
        min_molecular_weight=250,
        max_molecular_weight=550,
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_proteins_sequence_lv1():
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
    unique_tag = str(uuid.uuid4())
    response = client.data.create_ligand(
        smiles=smiles,
        name="Compound-12345",
        formal_charge=0,
        hbond_donor_count=1,
        hbond_acceptor_count=6,
        rotatable_bond_count=5,
        tpsa=85.12,
        molecular_weight=447.5,
        variant_name_tag=unique_tag,
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
    smiles = "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12"
    created = client.data.create_ligand(
        smiles=smiles,
        name="GetLigandTest",
        molecular_weight=447.5,
        variant_name_tag=str(uuid.uuid4()),
    )
    ligand_id = created["data"]["id"]

    response = client.data.get_ligand(id=ligand_id)

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "id" in response, "Expected 'id' key in response"
    assert response["id"] == ligand_id, "Expected id to match"
    assert "smiles" in response, "Expected 'smiles' key in response"
    assert "name" in response, "Expected 'name' key in response"
    assert response["name"] == "GetLigandTest", "Expected name to match"
    assert "molecular_weight" in response, "Expected 'molecular_weight' key in response"


def test_get_ligands_lv1():
    """Test getting multiple ligands by IDs."""
    client = DeepOriginClient()
    tag = str(uuid.uuid4())

    id1 = client.data.create_ligand(
        smiles="CCO", name="get-ligands-1", variant_name_tag=tag
    )["data"]["id"]
    id2 = client.data.create_ligand(
        smiles="CCCO", name="get-ligands-2", variant_name_tag=tag
    )["data"]["id"]

    data = client.data.get_ligands(ids=[id1, id2])

    assert isinstance(data, list), "Expected a list response"
    assert len(data) == 2, f"Expected 2 ligands, got {len(data)}"
    returned_ids = {record["id"] for record in data}
    assert returned_ids == {id1, id2}, "Expected both IDs in response"


def test_batch_create_ligands_lv1():
    """Test batch creating ligands."""
    client = DeepOriginClient()
    tag = str(uuid.uuid4())
    rows = [
        {
            "smiles": "CCO",
            "name": f"batch-ethanol-{tag}",
            "formal_charge": 0,
            "variant_name_tag": tag,
        },
        {
            "smiles": "CCCO",
            "name": f"batch-propanol-{tag}",
            "formal_charge": 0,
            "variant_name_tag": tag,
        },
    ]
    response = client.data.batch_create_ligands(rows=rows)

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    data = response["data"]
    assert isinstance(data, list), "Expected 'data' to be a list"
    assert len(data) == 2, f"Expected 2 created ligands, got {len(data)}"
    for record in data:
        assert "id" in record, "Expected 'id' in each created record"
        assert "canonical_smiles" in record, "Expected 'canonical_smiles' in record"


def test_get_protein_lv1():
    """Test getting a protein by ID."""
    client = DeepOriginClient()
    file_path = "entities/proteins/db4aa32e2e8ffa976a60004a8361b86427a2e5653a6623bb60b7913445902549.pdb"
    created = client.data.create_protein(file_path=file_path)
    protein_id = created["data"]["id"]

    response = client.data.get_protein(id=protein_id)

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "id" in response, "Expected 'id' key in response"
    assert response["id"] == protein_id, "Expected id to match"
    assert "file_path" in response, "Expected 'file_path' key in response"
    assert response["file_path"] == file_path, "Expected file_path to match"
    assert "subtable_name" in response, "Expected 'subtable_name' key in response"
    assert response["subtable_name"] == "proteins", "Expected subtable_name to match"
