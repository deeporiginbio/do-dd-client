"""Tests for the Data Platform API wrappers (entities, results, projects)."""

import os

import pytest

from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient


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
    response = client.entities.search_ligands()

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
    file_path = "entities/proteins/db4aa32e2e8ffa976a60004a8361b86427a2e5653a6623bb60b7913445902549.pdb"
    try:
        response = client.entities.create_protein(file_path=file_path)
    except DeepOriginException as e:
        if "409" in str(e):
            return
        raise

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    data = response["data"]
    assert "id" in data, "Expected 'id' key in data"
    assert "file_path" in data, "Expected 'file_path' key in data"
    assert data["file_path"] == file_path, "Expected file_path to match"


def test_list_projects_lv1():
    """Test listing projects."""
    client = DeepOriginClient()
    response = client.projects.list()

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


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
    ligands = LigandSet.from_smiles(["CCO", "CCCO"])
    ligands.sync(client=client)

    ids = [lig.id for lig in ligands]
    assert all(i is not None for i in ids), (
        "Expected all ligands to have ids after sync"
    )

    data = client.entities.get_ligands(ids=ids)

    assert isinstance(data, list), "Expected a list response"
    assert len(data) == 2, f"Expected 2 ligands, got {len(data)}"
    returned_ids = {record["id"] for record in data}
    assert returned_ids == set(ids), "Expected both IDs in response"


def test_batch_create_ligands_lv1():
    """Test batch creating ligands via LigandSet.sync()."""
    client = DeepOriginClient()
    ligands = LigandSet.from_smiles(["CCO", "CCCO"])
    ligands.sync(client=client)

    for lig in ligands:
        assert lig.id is not None, f"Expected id after sync for {lig.smiles}"
        assert lig.canonical_smiles is not None, (
            f"Expected canonical_smiles for {lig.smiles}"
        )


def test_get_protein_lv1():
    """Test getting a protein by ID."""
    client = DeepOriginClient()
    file_path = "entities/proteins/db4aa32e2e8ffa976a60004a8361b86427a2e5653a6623bb60b7913445902549.pdb"

    results = client.entities.search_proteins(file_path=file_path)
    if not results["data"]:
        response = client.entities.create_protein(file_path=file_path)
        protein_id = response["data"]["id"]
    else:
        protein_id = results["data"][0]["id"]

    response = client.entities.get_protein(id=protein_id)

    assert isinstance(response, dict), "Expected a dictionary response"
    assert response["id"] == protein_id, "Expected id to match"
    assert response["file_path"] == file_path, "Expected file_path to match"
    assert response["subtable_name"] == "proteins", "Expected subtable_name to match"


def _get_result_explorer_ids() -> tuple[str, str, str | None]:
    """Return (tool_id, protein_id, tool_version) for result-explorer tests.

    For local env, returns hardcoded values matching the fixture data.
    For remote envs, uses the same known protein but leaves tool_version
    as None so the test doesn't assert on a specific version.

    Returns:
        Tuple of (tool_id, protein_id, tool_version).
    """
    tool_id = "deeporigin.bulk-docking"
    protein_id = "08BSPN61NYVE3"
    if os.environ.get("DO_ENV") == "local":
        return tool_id, protein_id, "0.6.6"
    return tool_id, protein_id, None


def test_get_results_for_lv1():
    """Test searching result-explorer records filtered by tool and protein."""
    client = DeepOriginClient()
    tool_id, protein_id, _ = _get_result_explorer_ids()

    response = client.results.get_for(
        tool_id=tool_id,
        protein_id=protein_id,
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"
    assert len(response["data"]) > 0, "Expected at least one result"

    for record in response["data"]:
        for field in ("id", "tool_id", "tool_version", "data", "execution_id"):
            assert field in record, f"Expected '{field}' key in record"


def test_get_results_for_with_tool_version_lv1():
    """Test get_results_for with an explicit tool_version filter."""
    client = DeepOriginClient()
    tool_id, protein_id, tool_version = _get_result_explorer_ids()

    response = client.results.get_for(
        tool_id=tool_id,
        protein_id=protein_id,
        tool_version=tool_version,
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"

    if tool_version is not None:
        for record in response["data"]:
            assert record.get("tool_version") == tool_version, (
                "Expected all records to match the requested tool_version"
            )
