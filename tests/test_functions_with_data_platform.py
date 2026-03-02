"""This module tests functions working with the data platform."""

from pathlib import Path

import pytest

from deeporigin.drug_discovery import (
    BRD_DATA_DIR,
    Ligand,
    LigandSet,
    Pocket,
    Protein,
)
from deeporigin.functions.result import FunctionResult
from deeporigin.platform import DeepOriginClient

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture()
def client() -> DeepOriginClient:
    """Return a DeepOriginClient instance."""
    return DeepOriginClient()


@pytest.fixture()
def registered_protein(client: DeepOriginClient) -> Protein:
    """Register a fresh protein and delete it after the test."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.remove_water()
    protein.register(client=client)
    yield protein
    client.entities.delete(entity="proteins", entity_id=protein.id)


@pytest.fixture()
def registered_ligand(client: DeepOriginClient) -> Ligand:
    """Sync a ligand for use in tests.

    Ligands have a unique constraint on SMILES, so register would fail
    if the ligand already exists. Stale results are not a concern because
    docking results are keyed by the protein+ligand pair, and the protein
    is always freshly registered.
    """
    ligand = Ligand.from_smiles(
        "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12"
    )
    ligand.sync(client=client)
    return ligand


def test_pocketfinder_with_data_platform_lv2(
    client: DeepOriginClient,
    registered_protein: Protein,
):
    """Test pocket finder integration with data platform."""
    result = registered_protein.find_pockets(
        pocket_count=1, use_cache=False, client=client
    )

    assert isinstance(result, FunctionResult), (
        "Expected protein.find_pockets() to return a FunctionResult"
    )

    assert len(result.pockets) == 1, "Expected 1 pocket"

    pocket = result.pockets[0]

    assert isinstance(pocket, Pocket), "Expected Pocket object"
    assert pocket.protein_id == registered_protein.id, (
        "Pocket protein_id should match protein.id"
    )

    pockets_from_result = Pocket.from_result(
        protein_id=registered_protein.id, client=client
    )

    assert len(pockets_from_result) > 0, "Expected at least one pocket from result"
    for p in pockets_from_result:
        assert isinstance(p, Pocket), "Expected Pocket object"
        assert p.protein_id == registered_protein.id, (
            "Pocket protein_id should match protein.id"
        )
        assert p.coordinates is not None, "Expected coordinates to be loaded"
        assert p.volume is not None, "Expected volume on pocket"
        assert p.drugability_score is not None, "Expected drugability_score on pocket"


def test_docking_with_data_platform_lv2(
    client: DeepOriginClient,
    registered_protein: Protein,
    registered_ligand: Ligand,
):
    """Test docking function integration with data platform."""
    pocket = Pocket.from_pdb_file(
        FIXTURES_DIR
        / "files"
        / "tool-runs"
        / "86ea3aea-accd-474d-9e0b-89a3f47ab61b"
        / "pocket_1.pdb",
    )

    result = registered_protein.dock(
        ligand=registered_ligand,
        pocket=pocket,
        use_cache=False,
        client=client,
    )

    assert isinstance(result, FunctionResult), (
        "Expected protein.dock() to return a FunctionResult"
    )
    assert isinstance(result.poses, LigandSet), (
        "Expected result.poses to be a LigandSet"
    )

    poses = result.function_outputs[0]["poses"]

    for pose in poses:
        assert pose["protein_id"] == registered_protein.id, (
            "Pose protein_id should match protein.id"
        )
        assert pose["ligand_id"] == registered_ligand.id, (
            "Pose ligand_id should match ligand.id"
        )
        assert pose["file_path"] is not None, "Pose file_path should not be None"

    poses_from_result = LigandSet.from_docking_result(
        protein_id=registered_protein.id,
        client=client,
    )
    assert len(poses_from_result) > 0, "Expected at least one pose from result"
    for p in poses_from_result:
        assert isinstance(p, Ligand), "Expected Ligand object"
        assert p.mol is not None, "Pose should have a loaded RDKit mol"
        assert p.smiles is not None, "Pose should have SMILES"
