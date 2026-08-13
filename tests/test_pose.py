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
from deeporigin.drug_discovery.structures.pose import (
    _optional_bool,
    _optional_float,
    _pose_row_from_registration_execution,
)
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from tests.conftest import check_tool_exists


def test_pose_coercion_helpers() -> None:
    """Optional bool/float helpers accept common platform string forms."""
    assert _optional_float("1.5") == 1.5
    assert _optional_float(None) is None
    assert _optional_float("bad") is None
    assert _optional_bool("true") is True
    assert _optional_bool("0") is False
    assert _optional_bool("maybe") is None


def test_pose_from_json_rejects_missing_ligand_id() -> None:
    """from_json requires a non-empty ligand_id."""
    with pytest.raises(ValueError, match="ligand_id"):
        Pose.from_json([{"id": "P1", "remote_path": "entities/poses/x.sdf"}])


def test_pose_from_json_remote_path_only_row() -> None:
    """Remote-only rows hydrate SMILES without loading an SDF."""
    pose = Pose.from_json(
        [
            {
                "ligand_id": "L1",
                "smiles": "CCO",
                "id": "P1",
                "remote_path": "entities/poses/p1.sdf",
            }
        ]
    )[0]
    assert pose.smiles == "CCO"
    assert pose.remote_path == "entities/poses/p1.sdf"
    assert pose.mol is None


def test_pose_from_json_coerces_metadata_fields() -> None:
    """Numeric and boolean platform fields are coerced on hydration."""
    pose = Pose.from_json(
        [
            {
                "ligand_id": "L1",
                "id": "P1",
                "smiles": "CCO",
                "remote_path": "entities/poses/p1.sdf",
                "pose_score": "-8.5",
                "binding_energy": "1",
                "best_pose": "true",
                "custom_field": "x",
            }
        ]
    )[0]
    assert pose.pose_score == -8.5
    assert pose.binding_energy == 1.0
    assert pose.best_pose is True
    assert pose.props == {"custom_field": "x"}


def test_pose_to_hash_prefers_platform_id() -> None:
    """to_hash uses pose id, remote stem, local stem, ligand_id, or SMILES hash."""
    assert Pose(ligand_id="L", id="PID").to_hash() == "PID"
    remote_pose = Pose(ligand_id="L", remote_path="entities/poses/abc.sdf")
    assert remote_pose.to_hash() == "abc"
    local_pose = Pose(ligand_id="L", local_path="/tmp/my-pose.sdf")
    assert local_pose.to_hash() == "my-pose"
    ligand_only = Pose(ligand_id="LIG-123")
    assert ligand_only.to_hash() == "LIG-123"
    distinct = [
        Pose(ligand_id="LIG-A", local_path="/tmp/a.sdf").to_hash(),
        Pose(ligand_id="LIG-B", local_path="/tmp/b.sdf").to_hash(),
    ]
    assert len(set(distinct)) == 2


def test_pose_set_getitem_slice_returns_pose_set() -> None:
    """Slicing a PoseSet returns another PoseSet."""
    pose_set = PoseSet.from_json(
        [
            {
                "ligand_id": "L",
                "id": "P1",
                "smiles": "C",
                "remote_path": "entities/poses/p1.sdf",
            },
            {
                "ligand_id": "L",
                "id": "P2",
                "smiles": "CC",
                "remote_path": "entities/poses/p2.sdf",
            },
        ]
    )
    subset = pose_set[0:1]
    assert isinstance(subset, PoseSet)
    assert len(subset) == 1
    assert subset.poses[0].id == "P1"


def test_pose_set_to_ligand_set_legacy_bridge() -> None:
    """PoseSet.to_ligand_set preserves pose ids in ligand properties."""
    pose_set = PoseSet.from_json(
        [
            {
                "ligand_id": "L",
                "id": "P1",
                "smiles": "CCO",
                "remote_path": "entities/poses/p1.sdf",
            }
        ]
    )
    ligand_set = pose_set.to_ligand_set()
    assert len(ligand_set) == 1
    assert ligand_set.ligands[0].properties.get("pose_result_id") == "P1"


def test_pose_row_from_registration_execution_extracts_job_outputs() -> None:
    """ImportTool registration payloads expose the first pose row."""
    assert _pose_row_from_registration_execution({}) is None
    row = _pose_row_from_registration_execution(
        {"jobOutputs": {"poses": [{"id": "P1", "ligand_id": "L1"}]}}
    )
    assert row == {"id": "P1", "ligand_id": "L1"}


def test_pose_mol_returns_none_for_missing_local_path() -> None:
    """mol returns None when local_path is missing or unreadable."""
    assert Pose(ligand_id="L", local_path="/no/such/pose.sdf").mol is None


def test_pose_mol_returns_none_for_empty_sdf(tmp_path: Path) -> None:
    """mol returns None when the SDF file has no valid molecules."""
    empty_sdf = tmp_path / "empty.sdf"
    empty_sdf.write_text("")
    assert Pose(ligand_id="L", local_path=str(empty_sdf)).mol is None


def test_pose_sync_lazy_skips_when_remote_path_set() -> None:
    """sync(lazy=True) is a no-op when remote_path is already populated."""
    pose = Pose(ligand_id="L", remote_path="entities/poses/x.sdf")
    pose.sync(lazy=True)


def test_pose_to_file_writes_sdf(tmp_path: Path) -> None:
    """to_file exports a loaded pose structure to disk."""
    sdf_path = BRD_DATA_DIR / "brd-2.sdf"
    pose = PoseSet.from_json(
        [{"ligand_id": "L1", "id": "P1", "file_path": str(sdf_path)}]
    ).poses[0]
    out_path = tmp_path / "exported.sdf"
    written = pose.to_file(out_path)
    assert written == str(out_path)
    assert out_path.exists()


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
        project_id="PROJ-1",
        compute_job_id="JOB-1",
        props={"effort": 1, "constrained": True},
    )
    lig = pose.to_ligand()
    assert lig.id == "LIG-XYZ"
    assert lig.properties.get("id") == "POSE-ABC"
    assert lig.properties.get("pose_result_id") == "POSE-ABC"
    assert lig.project_id == "PROJ-1"
    assert lig.properties.get("compute_job_id") == "JOB-1"
    assert lig.properties.get("effort") == 1
    assert lig.properties.get("constrained") is True


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


def test_pose_from_id_round_trip_local(client, registered_protein) -> None:
    """Pose.from_id reloads a registered pose by platform id."""
    sdf_path = BRD_DATA_DIR / "brd-3.sdf"
    registered = Pose.from_sdf(
        sdf_path,
        protein_id=registered_protein.id,
        client=client,
    )
    fetched = Pose.from_id(registered.id, client=client)
    assert fetched.id == registered.id
    assert fetched.ligand_id == registered.ligand_id


def registered_ligand_poses_for_id(client, ligand_id: str) -> PoseSet:
    """Helper: load poses for one ligand id."""

    return PoseSet.from_result(ligand_id=ligand_id, client=client, scored_only=False)


def test_docking_get_results_returns_pose_set(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """Docking.get_results returns PoseSet with distinct pose and ligand ids."""
    docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
        client=client,
    )
    docking.run()
    pose_set = PoseSet.from_result(execution_id=docking.id, client=client)
    assert len(pose_set) >= 1
    assert isinstance(pose_set[0], Pose)
    assert pose_set[0].id is not None
    assert pose_set[0].ligand_id is not None
    assert pose_set[0].id != pose_set[0].ligand_id


def test_pose_set_filter_top_poses() -> None:
    """PoseSet.filter_top_poses keeps one pose per SMILES by score or energy."""
    from deeporigin.exceptions import DeepOriginException

    poses = PoseSet(
        poses=[
            Pose(
                ligand_id="L1",
                id="P1",
                smiles="CCO",
                remote_path="a.sdf",
                pose_score=0.3,
                binding_energy=-5.0,
            ),
            Pose(
                ligand_id="L1",
                id="P2",
                smiles="CCO",
                remote_path="b.sdf",
                pose_score=0.9,
                binding_energy=-7.0,
            ),
            Pose(
                ligand_id="L2",
                id="P3",
                smiles="CCN",
                remote_path="c.sdf",
                pose_score=0.5,
                binding_energy=-6.0,
            ),
        ]
    )
    by_score = poses.filter_top_poses(by_pose_score=True)
    assert len(by_score) == 2
    assert {p.id for p in by_score} == {"P2", "P3"}

    by_energy = poses.filter_top_poses(by_pose_score=False)
    assert len(by_energy) == 2
    assert {p.id for p in by_energy} == {"P2", "P3"}

    assert len(PoseSet(poses=[]).filter_top_poses()) == 0

    missing = PoseSet(
        poses=[
            Pose(ligand_id="L", id="A", smiles="C", remote_path="a.sdf"),
            Pose(ligand_id="L", id="B", smiles="C", remote_path="b.sdf"),
        ]
    )
    with pytest.raises(DeepOriginException, match="missing pose_score"):
        missing.filter_top_poses(by_pose_score=True)


def test_pose_set_filter_top_poses_from_docked_sdf() -> None:
    """filter_top_poses collapses multi-pose SDF fixtures to one pose per molecule."""
    ligands = LigandSet.from_sdf("tests/fixtures/docked-poses.sdf")
    assert len(ligands) == 16
    poses = PoseSet(
        poses=[
            Pose(
                ligand_id=f"L{i}",
                id=f"P{i}",
                smiles=str(
                    lig.properties.get("SMILES")
                    or lig.properties.get("initial_smiles")
                    or lig.smiles
                ),
                local_path=lig.local_path,
                pose_score=_optional_float(
                    lig.properties.get("pose_score") or lig.properties.get("POSE SCORE")
                ),
                binding_energy=_optional_float(
                    lig.properties.get("Binding Energy")
                    or lig.properties.get("binding_energy")
                ),
                _mol=lig.mol,
            )
            for i, lig in enumerate(ligands)
        ]
    )
    filtered = poses.filter_top_poses(by_pose_score=False)
    assert len(filtered) == 1


def test_pose_to_ligand_from_smiles_and_local_sdf(tmp_path: Path) -> None:
    """to_ligand hydrates from SMILES or a local SDF and copies metadata."""
    from deeporigin.exceptions import DeepOriginException

    smiles_pose = Pose(
        ligand_id="L1",
        id="P1",
        smiles="CCO",
        remote_path="entities/poses/p1.sdf",
        pose_score=0.8,
        binding_energy=-6.5,
        best_pose=True,
        protein_id="prot",
        origin="docking",
        name="ethanol",
        props={"extra": 1},
    )
    lig = smiles_pose.to_ligand()
    assert lig.id == "L1"
    assert lig.properties["pose_result_id"] == "P1"
    assert lig.properties["pose_score"] == 0.8
    assert lig.properties["Binding Energy"] == -6.5
    assert lig.properties["extra"] == 1
    assert lig.remote_path == "entities/poses/p1.sdf"

    src = BRD_DATA_DIR / "brd-3.sdf"
    local = tmp_path / "pose.sdf"
    local.write_bytes(src.read_bytes())
    local_pose = Pose(
        ligand_id="L2",
        id="P2",
        local_path=str(local),
        remote_path="entities/poses/p2.sdf",
    )
    lig2 = local_pose.to_ligand()
    assert lig2.id == "L2"
    assert lig2.remote_path == "entities/poses/p2.sdf"
    assert lig2.mol is not None

    bare = Pose(ligand_id="L3", remote_path="entities/poses/missing.sdf")
    with pytest.raises(DeepOriginException, match="local SDF or SMILES"):
        bare.to_ligand()


def test_pose_set_download_and_dataframe(tmp_path: Path) -> None:
    """PoseSet download helpers assign local paths; to_dataframe covers empty sets."""
    from deeporigin.drug_discovery.structures.pose import _assign_downloaded_pose_path

    assert len(PoseSet(poses=[]).to_dataframe()) == 0

    src = BRD_DATA_DIR / "brd-3.sdf"
    local = tmp_path / "downloaded.sdf"
    local.write_bytes(src.read_bytes())
    pose = Pose(
        ligand_id="L1",
        id="P1",
        smiles="CCO",
        remote_path="entities/poses/p1.sdf",
        pose_score=1.0,
        binding_energy=-1.0,
    )
    _assign_downloaded_pose_path(
        pose,
        paths_by_remote={"entities/poses/p1.sdf": str(local)},
        skip_errors=False,
        sanitize=True,
        remove_hydrogens=False,
    )
    assert pose.local_path == str(local)
    assert pose.mol is not None

    pose_set = PoseSet(poses=[pose])
    df = pose_set.to_dataframe()
    assert len(df) == 1

    # download is a no-op when every pose already has local_path
    pose_set.download()
    assert pose.local_path == str(local)


def test_normalize_pose_ligands_accepts_pose_set() -> None:
    """Docking viz helpers accept Pose and PoseSet via to_ligand conversion."""
    from deeporigin.drug_discovery.docking_common import normalize_pose_ligands

    pose = Pose(
        ligand_id="L1",
        id="P1",
        smiles="CCO",
        remote_path="entities/poses/p1.sdf",
        name="n1",
    )
    assert len(normalize_pose_ligands(pose)) == 1
    assert len(normalize_pose_ligands(PoseSet(poses=[pose]))) == 1
    assert len(normalize_pose_ligands([pose])) == 1


def test_ligand_from_structure_input_remote_and_local(tmp_path: Path) -> None:
    """Constrained docking structure-input helper builds Ligands without ligand_id."""
    from deeporigin.drug_discovery.constrained_docking import (
        _ligand_from_structure_input,
    )

    remote = _ligand_from_structure_input(
        {"file_path": "testing/pose.sdf", "smiles": "CCO", "name": "ref"}
    )
    assert remote.remote_path == "testing/pose.sdf"
    assert remote.smiles == "CCO"

    src = BRD_DATA_DIR / "brd-2.sdf"
    local = tmp_path / "ref.sdf"
    local.write_bytes(src.read_bytes())
    local_lig = _ligand_from_structure_input({"file_path": str(local), "id": "ref-id"})
    assert local_lig.local_path == str(local) or Path(local_lig.to_sdf()).exists()
    assert local_lig.id == "ref-id"

    with pytest.raises(ValueError, match="smiles"):
        _ligand_from_structure_input({"file_path": "testing/pose.sdf"})


def test_ligand_get_poses_requires_id() -> None:
    """Ligand.get_poses raises when the ligand has no platform id."""
    ligand = Ligand.from_smiles("CCO")
    with pytest.raises(ValueError, match="platform ligand id"):
        ligand.get_poses()
