"""This module tests functions working with the data platform."""

import pytest

from conftest import check_function_exists
from deeporigin.drug_discovery import (
    Ligand,
    LigandSet,
    Pocket,
    Protein,
)
from deeporigin.functions.result import FunctionResult
from deeporigin.platform import DeepOriginClient
from deeporigin.platform.constants import (
    DOCKING_FUNCTION_KEY,
    DOCKING_FUNCTION_VERSION,
)


def test_docking_with_data_platform_lv2(
    client: DeepOriginClient,
    registered_protein: Protein,
    registered_ligand: Ligand,
    registered_pocket: Pocket,
):
    """Test docking function integration with data platform."""
    if not check_function_exists(
        client, DOCKING_FUNCTION_KEY, DOCKING_FUNCTION_VERSION
    ):
        pytest.skip("Docking function does not exist")

    result = registered_protein.dock(
        ligand=registered_ligand,
        pocket=registered_pocket,
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
    assert len(poses_from_result) >= 16, "Expected at least one pose from result"
    for pose in poses_from_result:
        assert isinstance(pose, Ligand), "Expected Ligand object"
        assert pose.mol is not None, "Pose should have a loaded RDKit mol"
        assert pose.smiles is not None, "Pose should have SMILES"
