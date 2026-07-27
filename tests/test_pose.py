"""Tests for Pose and PoseSet (DDOS-6736)."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeporigin.drug_discovery import (
    BRD_DATA_DIR,
    Docking,
    Ligand,
    LigandSet,
    Pose,
    PoseSet,
)
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from tests.conftest import check_tool_exists


def test_pose_from_json_local_sdf(tmp_path: Path) -> None:
    """PoseSet.from_json builds Pose objects with distinct pose and ligand ids."""
    sdf_path = BRD_DATA_DIR / "brd-2.sdf"
    ligand = Ligand.from_sdf(sdf_path)
    ligand.sync()

    row = {
        "id": "POSE-RESULT-1",
        "ligand_id": ligand.id or "LIG-1",
        "file_path": str(sdf_path),
        "pose_score": -8.5,
        "best_pose": True,
        "origin": "docking",
    }
    pose_set = PoseSet.from_json([row])
    assert len(pose_set) == 1
    pose = pose_set.poses[0]
    assert isinstance(pose, Pose)
    assert pose.id == "POSE-RESULT-1"
    assert pose.ligand_id == row["ligand_id"]
    assert pose.pose_score == -8.5
    assert pose.origin == "docking"
    assert pose.mol is not None


def test_pose_to_ligand_legacy_shape() -> None:
    """Pose.to_ligand preserves pose id in properties for legacy callers."""
    pose = Pose(
        id="POSE-ABC",
        ligand_id="LIG-XYZ",
        smiles="CCO",
        remote_path="entities/poses/test.sdf",
    )
    lig = pose.to_ligand()
    assert lig.id == "LIG-XYZ"
    assert lig.properties.get("id") == "POSE-ABC"
    assert lig.properties.get("pose_result_id") == "POSE-ABC"


def test_pose_set_from_result_after_docking_local(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """PoseSet.from_result loads scored poses for a docking execution."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["docking"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["docking"]["tool_version"],
    )

    docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
        client=client,
    )
    docking.run()
    assert docking.id is not None

    pose_set = PoseSet.from_result(execution_id=docking.id, client=client)
    assert len(pose_set) >= 1
    for pose in pose_set:
        assert isinstance(pose, Pose)
        assert pose.id is not None
        assert pose.ligand_id is not None
        assert pose.id != pose.ligand_id


def test_ligand_get_poses_local(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """Ligand.get_poses returns child poses for a synced ligand."""
    docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
        client=client,
    )
    docking.run()

    child_poses = registered_ligand.get_poses(client=client)
    assert len(child_poses) >= 1
    assert all(pose.ligand_id == registered_ligand.id for pose in child_poses)


def test_pose_from_sdf_registers_local(client, registered_protein) -> None:
    """Pose.from_sdf registers an external SDF via ImportTool (mock)."""
    sdf_path = BRD_DATA_DIR / "brd-3.sdf"
    pose = Pose.from_sdf(
        sdf_path,
        protein_id=registered_protein.id,
        client=client,
    )
    assert pose.id is not None
    assert pose.ligand_id is not None
    assert pose.origin == "registered"
    assert pose.protein_id == registered_protein.id
    assert pose.local_path == str(sdf_path)

    found = registered_ligand_poses_for_id(client, pose.ligand_id)
    assert any(p.id == pose.id for p in found)


def registered_ligand_poses_for_id(client, ligand_id: str) -> PoseSet:
    """Helper: load poses for one ligand id."""

    return PoseSet.from_result(ligand_id=ligand_id, client=client, scored_only=False)


def test_load_scored_poses_still_returns_ligand_set(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """Legacy LigandSet.from_result remains unchanged in Phase 2."""
    docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
        client=client,
    )
    docking.run()
    legacy = LigandSet.from_result(execution_id=docking.id, client=client)
    assert len(legacy) >= 1
    assert isinstance(legacy.ligands[0], Ligand)


def test_ligand_get_poses_requires_id() -> None:
    """Ligand.get_poses raises when the ligand has no platform id."""
    ligand = Ligand.from_smiles("CCO")
    with pytest.raises(ValueError, match="platform ligand id"):
        ligand.get_poses()
