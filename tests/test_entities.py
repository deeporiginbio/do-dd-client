"""Tests for the Entities API wrapper."""

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform import DeepOriginClient

_BRD_PDB_LOCAL = BRD_DATA_DIR / "brd.pdb"
_BRD_PDB_REMOTE = "testing/brd.pdb"


def test_search_entity_lv1():
    """Test searching an entity."""
    client = DeepOriginClient()
    response = client.entities.search("ligands")

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_entity_invalid_entity():
    """Test searching with an invalid entity raises ValueError."""
    client = DeepOriginClient()
    with pytest.raises(ValueError, match="Invalid entity 'invalid_table'"):
        client.entities.search("invalid_table")


def test_search_ligands_lv1():
    """Test searching ligands using convenience method."""
    client = DeepOriginClient()
    response = client.entities.search_ligands(limit=10)

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_ligands_molecular_weight_lv1():
    """Test searching ligands with molecular weight filters."""
    client = DeepOriginClient()
    response = client.entities.search_ligands(
        min_molecular_weight=250,
        max_molecular_weight=550,
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_ligands_limit_caps_total_results():
    """Test that limit caps the total number of results returned."""
    client = DeepOriginClient()

    all_results = client.entities.search_ligands()
    total = len(all_results["data"])
    if total < 2:
        pytest.skip("Need at least 2 ligands to test limit capping")

    for cap in [1, 2]:
        response = client.entities.search_ligands(limit=cap)
        assert len(response["data"]) == cap, (
            f"Expected exactly {cap} results with limit={cap}, got {len(response['data'])}"
        )


def test_search_ligands_smiles_list_lv1():
    """Test searching ligands by a list of SMILES strings."""
    client = DeepOriginClient()

    existing = client.entities.search_ligands(limit=3)
    assert len(existing["data"]) >= 2, "Need at least 2 existing ligands for this test"

    known_smiles = [lig["canonical_smiles"] for lig in existing["data"][:2]]

    response = client.entities.search_ligands(smiles_list=known_smiles)

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
        client.entities.search_ligands(smiles_list=["C"], smiles="C")

    with pytest.raises(ValueError, match="mutually exclusive"):
        client.entities.search_ligands(smiles_list=["C"], canonical_smiles="C")


def test_search_ligands_empty_smiles_list():
    """Test that an empty smiles_list returns an empty result immediately."""
    client = DeepOriginClient()
    response = client.entities.search_ligands(smiles_list=[])

    assert response == {"data": [], "count": 0}


def test_search_proteins_lv1():
    """Test searching proteins using convenience method."""
    client = DeepOriginClient()
    response = client.entities.search_proteins()

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_proteins_molecular_weight_lv1():
    """Test searching proteins with molecular weight filters."""
    client = DeepOriginClient()
    response = client.entities.search_proteins(
        min_molecular_weight=250,
        max_molecular_weight=550,
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_proteins_sequence_lv1():
    """Test searching proteins with sequence filter."""
    client = DeepOriginClient()
    response = client.entities.search_proteins(
        sequence="MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHSLAKWKRQTLGQHDFSAGEGLYTHMKALRPDEDRLSPLHSVYVDQWDWERVMGDGERQFSTLKSTVEAIWAGIKATEAAVSEEFGLAPFLPDQIHFVHSQELLSRYPDLDAKGRERAIAKDLGAVFLVGIGGKLSDGHRHDVRAPDYDDWSTPSELGHAGLNGDILVWNPVLEDAFELSSMGIRVDADTLKHQLALTGDEDRLELEWHQALLRGEMPQTIGGGIGQSRLTMLLLQLPHIGQVQAGVWPAAVRESVPSLL"
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_list_models_lv1():
    """Test listing models."""
    client = DeepOriginClient()
    response = client.entities.list_models()

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "models" in response, "Expected 'models' key in response"
    assert isinstance(response["models"], list), "Expected 'models' to be a list"
    assert len(response["models"]) > 0, "Expected at least one model"
    model = response["models"][0]
    assert "tableName" in model, "Expected 'tableName' key in model"
    assert "visibility" in model, "Expected 'visibility' key in model"
    assert model["visibility"] == "public", "Expected visibility to be 'public'"


def test_create_ligand_lv1():
    """Test creating a ligand; 409 (already exists) is also a pass."""
    client = DeepOriginClient()
    smiles = "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12"
    try:
        response = client.entities.create_ligand(
            smiles=smiles,
            name="Compound-12345",
            formal_charge=0,
            hbond_donor_count=1,
            hbond_acceptor_count=6,
            rotatable_bond_count=5,
            tpsa=85.12,
            molecular_weight=447.5,
        )
    except DeepOriginException as e:
        if "409" in str(e):
            return
        raise

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    data = response["data"]
    assert "id" in data, "Expected 'id' key in data"
    assert "canonical_smiles" in data, "Expected 'canonical_smiles' key in data"


def test_create_protein_lv1():
    """Test creating a protein; 409 (already exists) is also a pass."""
    client = DeepOriginClient()
    client.files.upload_file(_BRD_PDB_LOCAL, _BRD_PDB_REMOTE)

    try:
        response = client.entities.create_protein(file_path=_BRD_PDB_REMOTE)
    except DeepOriginException as e:
        if "409" in str(e):
            return
        raise

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    data = response["data"]
    assert "id" in data, "Expected 'id' key in data"
    assert "file_path" in data, "Expected 'file_path' key in data"


def test_get_ligand_lv1():
    """Test getting a ligand by ID."""
    client = DeepOriginClient()
    smiles = "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12"
    lig = Ligand.from_smiles(smiles, name="GetLigandTest")
    lig.sync(client=client)
    assert lig.id is not None, "Expected ligand to have an id after sync"

    response = client.entities.get_ligand(id=lig.id)

    assert isinstance(response, dict), "Expected a dictionary response"
    assert response["id"] == lig.id, "Expected id to match"
    assert "smiles" in response, "Expected 'smiles' key in response"


def test_get_ligands_lv1():
    """Test getting multiple ligands by IDs."""
    client = DeepOriginClient()
    existing = client.entities.search_ligands()
    assert len(existing["data"]) >= 2, "Expected at least 2 existing ligands"
    ids = [record["id"] for record in existing["data"][:2]]

    data = client.entities.get_ligands(ids=ids)

    assert isinstance(data, list), "Expected a list response"
    assert len(data) == 2, f"Expected 2 ligands, got {len(data)}"
    returned_ids = {record["id"] for record in data}
    assert returned_ids == set(ids), "Expected both IDs in response"


def test_get_ligands_empty_ids():
    """Test that get_ligands returns immediately for empty input."""
    client = DeepOriginClient()
    data = client.entities.get_ligands(ids=[])
    assert data == []


def test_get_protein_lv1():
    """Test getting a protein by ID."""
    client = DeepOriginClient()
    client.files.upload_file(_BRD_PDB_LOCAL, _BRD_PDB_REMOTE)

    results = client.entities.search_proteins(file_path=_BRD_PDB_REMOTE)
    if not results["data"]:
        response = client.entities.create_protein(file_path=_BRD_PDB_REMOTE)
        protein_id = response["data"]["id"]
    else:
        protein_id = results["data"][0]["id"]

    response = client.entities.get_protein(id=protein_id)

    assert isinstance(response, dict), "Expected a dictionary response"
    assert response["id"] == protein_id, "Expected id to match"
    assert response["file_path"] == _BRD_PDB_REMOTE, "Expected file_path to match"
    assert response["subtable_name"] == "proteins", "Expected subtable_name to match"
