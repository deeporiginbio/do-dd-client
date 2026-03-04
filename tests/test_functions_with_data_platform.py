"""This module tests functions working with the data platform."""

from pathlib import Path

import pytest

from conftest import check_function_exists
from deeporigin.drug_discovery import (
    BRD_DATA_DIR,
    Ligand,
    LigandSet,
    Pocket,
    Protein,
)
from deeporigin.functions.result import FunctionResult
from deeporigin.functions.sysprep import abfe
from deeporigin.platform import DeepOriginClient
from deeporigin.platform.constants import (
    DOCKING_FUNCTION_KEY,
    DOCKING_FUNCTION_VERSION,
    POCKET_FINDER_FUNCTION_KEY,
    POCKET_FINDER_FUNCTION_VERSION,
    SYSPREP_FUNCTION_KEY,
    SYSPREP_FUNCTION_VERSION,
)

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
    protein.sync(client=client)
    return protein


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
) -> None:
    """Test pocket finder function integration with data platform."""

    if not check_function_exists(
        client, POCKET_FINDER_FUNCTION_KEY, POCKET_FINDER_FUNCTION_VERSION
    ):
        pytest.skip("Pocket finder function does not exist")

    num_pockets = 1

    result = registered_protein.find_pockets(
        pocket_count=num_pockets,
        use_cache=False,
        client=client,
    )

    assert isinstance(result, FunctionResult), (
        "Expected protein.find_pockets() to return a FunctionResult"
    )

    assert len(result.pockets) == num_pockets, f"Expected {num_pockets} pockets"

    pocket = result.pockets[0]

    assert isinstance(pocket, Pocket), "Expected Pocket object"
    assert pocket.protein_id == registered_protein.id, (
        "Pocket protein_id should match protein.id"
    )

    pockets_from_result = Pocket.from_result(
        execution_id=result._responses[0]["id"],
        client=client,
    )

    assert len(pockets_from_result) == num_pockets, (
        f"Expected {num_pockets} pockets from result"
    )
    pocket_from_result = pockets_from_result[0]
    assert isinstance(pocket_from_result, Pocket), "Expected Pocket object"
    assert pocket_from_result.protein_id == registered_protein.id, (
        "Pocket protein_id should match protein.id"
    )
    assert pocket_from_result.coordinates is not None, (
        "Expected coordinates to be loaded"
    )
    assert pocket_from_result.volume is not None, "Expected volume on pocket"
    assert pocket_from_result.drugability_score is not None, (
        "Expected drugability_score on pocket"
    )


def test_docking_with_data_platform_lv2(
    client: DeepOriginClient,
    registered_protein: Protein,
    registered_ligand: Ligand,
):
    if not check_function_exists(
        client, DOCKING_FUNCTION_KEY, DOCKING_FUNCTION_VERSION
    ):
        pytest.skip("Docking function does not exist")

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

    execution_id = result._responses[0]["id"]

    assert execution_id is not None, "Expected execution_id to be not None"

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
        execution_id=execution_id,
        client=client,
    )
    assert len(poses_from_result) == 16, "Expected at least one pose from result"
    for pose in poses_from_result:
        assert isinstance(pose, Ligand), "Expected Ligand object"
        assert pose.mol is not None, "Pose should have a loaded RDKit mol"
        assert pose.smiles is not None, "Pose should have SMILES"


def test_sysprep_with_data_platform_lv2(
    client: DeepOriginClient,
    registered_protein: Protein,
    registered_ligand: Ligand,
):
    if not check_function_exists(
        client, SYSPREP_FUNCTION_KEY, SYSPREP_FUNCTION_VERSION
    ):
        pytest.skip("Sysprep function does not exist")

    # run function
    result = abfe(client=client, protein=registered_protein, ligand=registered_ligand)

    function_data = result._responses[0]["functionOutputs"]
    assert ["system"] in function_data, "Expected system in function data"
    function_data = function_data["system"]

    # query data platform for this result
    response = client.results.get(compute_job_id=result.responses[0]["id"])
    data = response["data"][0]["data"]

    # check that the two are the same
    assert data == function_data, "Expected data to match function data"
