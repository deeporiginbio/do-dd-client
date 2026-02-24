"""this module tests functions working with the data platform."""

from pathlib import Path

from deeporigin.drug_discovery import (
    BRD_DATA_DIR,
    Ligand,
    LigandSet,
    Pocket,
    Protein,
)
from deeporigin.functions.result import FunctionResult
from deeporigin.platform import DeepOriginClient

# Fixtures directory for test files
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _prepare_protein(client: DeepOriginClient) -> Protein:
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.remove_water()
    protein.sync(client=client)
    return protein


def test_pocketfinder_with_data_platform_lv2():
    """Test pocket finder integration with data platform."""
    client = DeepOriginClient()

    protein = _prepare_protein(client)

    result = protein.find_pockets(pocket_count=1, use_cache=False, client=client)

    assert isinstance(result, FunctionResult), (
        "Expected protein.find_pockets() to return a FunctionResult"
    )

    assert len(result.pockets) == 1, "Expected 1 pocket"

    pocket = result.pockets[0]

    assert isinstance(pocket, Pocket), "Expected Pocket object"
    assert pocket.protein_id == protein.id, "Pocket protein_id should match protein.id"


def test_docking_with_data_platform_lv2():
    """Test docking function integration with data platform."""
    client = DeepOriginClient()
    protein = _prepare_protein(client)

    pocket = Pocket.from_pdb_file(
        FIXTURES_DIR
        / "files"
        / "tool-runs"
        / "86ea3aea-accd-474d-9e0b-89a3f47ab61b"
        / "pocket_1.pdb",
    )

    ligand = Ligand.from_smiles(
        "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12"
    )
    ligand.sync(client=client)

    result = protein.dock(
        ligand=ligand,
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
        assert pose["protein_id"] == protein.id, (
            "Pose protein_id should match protein.id"
        )

        assert pose["ligand_id"] == ligand.id, "Pose ligand_id should match ligand.id"
        assert pose["file_path"] is not None, "Pose file_path should not be None"
