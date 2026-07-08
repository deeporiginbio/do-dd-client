"""Tests for :class:`deeporigin.drug_discovery.constrained_docking.ConstrainedDocking`."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, ConstrainedDocking, Docking, Ligand
from deeporigin.drug_discovery.constrained_docking import _reference_pose_tool_input_row
from deeporigin.drug_discovery.docking_common import load_docking_poses_from_execution
from deeporigin.drug_discovery.structures.ligand import (
    LigandSet,
    _is_scored_docking_pose_data,
)
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from tests.conftest import check_tool_exists


def _make_reference_pair() -> tuple[Ligand, Ligand]:
    """Return reference ligand and pose from bundled BRD SDF data."""
    reference_ligand = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")
    reference_pose = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")
    return reference_ligand, reference_pose


def test_reference_pose_tool_input_row_uses_pose_result_id() -> None:
    """reference.pose.id must be the pose result id, not the ligands-table id."""
    pose = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")
    pose.id = "ligand-abc"
    pose.remote_path = "testing/reference-pose.sdf"
    pose.properties["pose_result_id"] = "pose-xyz"

    row = _reference_pose_tool_input_row(pose)

    assert row == {
        "file_path": "testing/reference-pose.sdf",
        "id": "pose-xyz",
    }
    assert row["id"] != pose.id


def test_reference_pose_tool_input_row_ignores_sdf_id_property() -> None:
    """SDF-derived id properties must not be forwarded as reference.pose.id."""
    pose = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")
    pose.id = "ligand-abc"
    pose.remote_path = "testing/reference-pose-static.sdf"
    pose.properties["id"] = "ligand-abc"

    row = _reference_pose_tool_input_row(pose)

    assert row == {"file_path": "testing/reference-pose-static.sdf"}
    assert "id" not in row


def test_reference_pose_tool_input_row_omits_id_for_static_sdf() -> None:
    """Static reference pose SDFs without a pose result id send file_path only."""
    pose = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")
    pose.remote_path = "testing/reference-pose-static.sdf"

    row = _reference_pose_tool_input_row(pose)

    assert row == {"file_path": "testing/reference-pose-static.sdf"}
    assert "id" not in row


def test_ensure_platform_inputs_skips_sync_for_platform_pose(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """Platform poses with remote_path already set must not run ligand sync."""
    reference_ligand, reference_pose = _make_reference_pair()
    reference_ligand.remote_path = "testing/brd-2.sdf"
    reference_ligand.id = "brd-2"
    reference_pose.remote_path = "testing/docked-pose.sdf"
    reference_pose.id = "brd-2"
    reference_pose.properties["pose_result_id"] = "pose-from-docking"

    cd = ConstrainedDocking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        reference_ligand=reference_ligand,
        reference_pose=reference_pose,
        ligand=registered_ligand,
        client=client,
    )

    with (
        patch.object(cd.protein, "sync") as protein_sync,
        patch.object(cd.reference_ligand, "sync") as ref_ligand_sync,
        patch.object(cd.reference_pose, "sync") as ref_pose_sync,
        patch.object(cd.ligands, "sync") as ligands_sync,
    ):
        cd._ensure_platform_inputs()

    protein_sync.assert_called_once()
    ref_ligand_sync.assert_called_once()
    ref_pose_sync.assert_not_called()
    ligands_sync.assert_called_once()
    assert reference_pose.remote_path == "testing/docked-pose.sdf"


def test_constrained_docking_requires_ligand_or_ligands(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """Constructor requires exactly one of ligand or ligands."""
    reference_ligand, reference_pose = _make_reference_pair()
    with pytest.raises(ValueError, match="Exactly one of ligand or ligands"):
        ConstrainedDocking(
            protein=registered_protein,
            pocket=unregistered_pocket,
            reference_ligand=reference_ligand,
            reference_pose=reference_pose,
            client=client,
        )


def test_constrained_docking_rejects_both_mcs_overrides(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """Constructor rejects mcs_smarts and mcs_smiles together."""
    reference_ligand, reference_pose = _make_reference_pair()
    with pytest.raises(ValueError, match="mutually exclusive"):
        ConstrainedDocking(
            protein=registered_protein,
            pocket=unregistered_pocket,
            reference_ligand=reference_ligand,
            reference_pose=reference_pose,
            ligand=registered_ligand,
            mcs_smarts="C(=O)",
            mcs_smiles="C=O",
            client=client,
        )


def test_constrained_docking_rejects_reference_pose_without_3d(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """Constructor rejects reference_pose without 3D coordinates."""
    reference_ligand, _reference_pose = _make_reference_pair()
    flat_pose = Ligand.from_smiles("CCO")
    assert flat_pose.mol is not None
    flat_pose.mol.RemoveAllConformers()
    with pytest.raises(ValueError, match="reference_pose must have a 3D structure"):
        ConstrainedDocking(
            protein=registered_protein,
            pocket=unregistered_pocket,
            reference_ligand=reference_ligand,
            reference_pose=flat_pose,
            ligand=registered_ligand,
            client=client,
        )


def test_constrained_docking_rejects_invalid_effort(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """Constructor rejects effort outside 1–5."""
    reference_ligand, reference_pose = _make_reference_pair()
    with pytest.raises(DeepOriginException, match="effort must be between"):
        ConstrainedDocking(
            protein=registered_protein,
            pocket=unregistered_pocket,
            reference_ligand=reference_ligand,
            reference_pose=reference_pose,
            ligand=registered_ligand,
            effort=0,
            client=client,
        )


def test_build_tool_inputs_includes_reference_and_sync(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """Payload includes reference block, sync, and ligand file_path."""
    reference_ligand, reference_pose = _make_reference_pair()
    cd = ConstrainedDocking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        reference_ligand=reference_ligand,
        reference_pose=reference_pose,
        ligand=registered_ligand,
        mcs_smarts="C(=O)",
        client=client,
    )
    cd._ensure_platform_inputs()
    params, _metadata = cd._build_tool_inputs()

    assert "reference" in params
    assert params["reference"]["ligand"]["file_path"] == reference_ligand.remote_path
    assert params["reference"]["ligand"]["smiles"] == reference_ligand.smiles
    assert params["reference"]["pose"]["file_path"] == reference_pose.remote_path
    assert params["constraint_energy"] == 5.0
    assert params["mcs_smarts"] == "C(=O)"
    assert "constraints" not in params
    assert len(params["ligands"]) == 1
    assert params["ligands"][0]["file_path"] == registered_ligand.remote_path

    payload = cd._build_create_payload(sync=True)
    assert payload["inputs"]["sync"] is True
    assert payload["batchSize"] == 8


def test_build_create_payload_async_sets_sync_false(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """Async payload sets sync=false."""
    reference_ligand, reference_pose = _make_reference_pair()
    query_a = Ligand.from_sdf(BRD_DATA_DIR / "brd-3.sdf")
    query_b = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")
    cd = ConstrainedDocking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        reference_ligand=reference_ligand,
        reference_pose=reference_pose,
        ligands=LigandSet(ligands=[query_a, query_b]),
        client=client,
    )
    cd._ensure_platform_inputs()
    payload = cd._build_create_payload(sync=False)
    assert payload["inputs"]["sync"] is False
    assert len(payload["inputs"]["ligands"]) == 2


def test_start_rejects_single_ligand(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """start() requires at least two test ligands."""
    reference_ligand, reference_pose = _make_reference_pair()
    cd = ConstrainedDocking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        reference_ligand=reference_ligand,
        reference_pose=reference_pose,
        ligand=registered_ligand,
        client=client,
    )
    with pytest.raises(ValueError, match="single test ligand must use run"):
        cd.start()


def test_constrained_docking_from_dto_maps_fields(client) -> None:
    """from_dto rehydrates protein, pocket, reference, ligands, and effort."""
    fixture_path = (
        Path(__file__).parent
        / "fixtures/executions/constrained-docking-test-execution.json"
    )
    dto = json.loads(fixture_path.read_text())

    cd = ConstrainedDocking.from_dto(dto, client=client)

    assert cd.id == dto["executionId"]
    assert cd.status == dto["status"]
    assert cd.effort == 1
    assert cd.constraint_energy == 5.0
    assert cd.ligand.id == "brd-3"
    assert cd.protein.id == "brd"
    assert cd.reference_ligand.id == "brd-2"
    assert cd.reference_pose.remote_path == "testing/brd-2-pose.sdf"


def test_get_reference_pose_from_fixture_dto(client) -> None:
    """get_reference_pose loads reference_pose from jobOutputs."""
    fixture_path = (
        Path(__file__).parent
        / "fixtures/executions/constrained-docking-test-execution.json"
    )
    dto = json.loads(fixture_path.read_text())
    cd = ConstrainedDocking.from_dto(dto, client=client)

    ref = cd.get_reference_pose(dto)
    assert ref.remote_path == "testing/brd-2-pose.sdf"


def test_get_reference_pose_falls_back_to_user_inputs_smiles(client) -> None:
    """get_reference_pose resolves SMILES from userInputs when jobOutputs omit it."""
    from deeporigin.drug_discovery.docking_common import _enrich_reference_pose_row

    fixture_path = (
        Path(__file__).parent
        / "fixtures/executions/constrained-docking-test-execution.json"
    )
    dto = json.loads(fixture_path.read_text())
    raw = dict(dto["jobOutputs"]["reference_pose"])
    raw.pop("smiles", None)

    enriched = _enrich_reference_pose_row(raw, dto=dto)

    assert enriched["smiles"] == dto["userInputs"]["reference"]["ligand"]["smiles"]

    cd = ConstrainedDocking.from_dto(dto, client=client)
    ref = cd.get_reference_pose(dto)
    assert ref.remote_path == "testing/brd-2-pose.sdf"


def test_constrained_docking_from_dto_raises_on_tool_key_mismatch(client) -> None:
    """from_dto fails fast when DTO tool key does not match."""
    fixture_path = (
        Path(__file__).parent
        / "fixtures/executions/constrained-docking-test-execution.json"
    )
    dto = json.loads(fixture_path.read_text())
    dto["tool"]["key"] = "deeporigin.foo-fake-tool"

    with pytest.raises(ValueError, match="tool key mismatch"):
        ConstrainedDocking.from_dto(dto, client=client)


@pytest.mark.expects_results
def test_constrained_docking_run_quote_true(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """run(quote=True) returns None and populates estimate."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["constrained_docking"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["constrained_docking"]["tool_version"],
    ), "Constrained docking tool not registered on platform."

    reference_ligand, reference_pose = _make_reference_pair()
    reference_ligand.sync(
        client=client,
        remote_path="testing/constrained-docking/brd-2.sdf",
    )
    reference_pose.sync(
        client=client,
        remote_path="testing/constrained-docking/brd-2-pose.sdf",
    )

    cd = ConstrainedDocking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        reference_ligand=reference_ligand,
        reference_pose=reference_pose,
        ligand=registered_ligand,
        client=client,
    )
    result = cd.run(quote=True)

    assert result is None
    assert cd.estimate is not None
    assert cd.status == "Quoted"


@pytest.mark.expects_results
def test_constrained_docking_run_with_reference_workflow(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """Dock a reference ligand, then constrained-dock a similar test ligand."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["docking"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["docking"]["tool_version"],
    )
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["constrained_docking"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["constrained_docking"]["tool_version"],
    )

    ref_docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
        client=client,
    )
    ref_poses = ref_docking.run()
    assert ref_poses is not None and len(ref_poses) >= 1
    reference_pose = ref_poses.ligands[0]
    pose_result_id = reference_pose.properties.get("pose_result_id")
    if pose_result_id is None:
        pose_result_id = reference_pose.properties.get("id")
    assert pose_result_id is not None

    query_ligand = Ligand.from_sdf(BRD_DATA_DIR / "brd-3.sdf")
    query_ligand.sync(
        client=client,
        remote_path="testing/constrained-docking/brd-3.sdf",
    )

    cd = ConstrainedDocking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        reference_ligand=registered_ligand,
        reference_pose=reference_pose,
        ligand=query_ligand,
        client=client,
    )
    cd._ensure_platform_inputs()
    params, _metadata = cd._build_tool_inputs()
    assert params["reference"]["pose"]["file_path"] == reference_pose.remote_path
    assert params["reference"]["pose"]["id"] == str(pose_result_id)
    if reference_pose.id is not None:
        assert params["reference"]["pose"]["id"] != reference_pose.id

    poses = cd.run()

    assert isinstance(poses, LigandSet)
    assert len(poses) >= 1


def test_is_scored_docking_pose_data_excludes_reference_pose() -> None:
    """Reference pose rows in the Pose table lack scoring metadata."""
    assert (
        _is_scored_docking_pose_data(
            {
                "file_path": "tool-runs/job/reference_pose.sdf",
                "ligand_id": "ref-ligand",
                "protein_id": "protein-1",
            }
        )
        is False
    )
    assert (
        _is_scored_docking_pose_data(
            {
                "best_pose": False,
                "file_path": "tool-runs/job/pose.sdf",
                "ligand_id": "query-ligand",
                "ligand_smiles": "CCO",
                "pose_score": 0.75,
                "protein_id": "protein-1",
            }
        )
        is True
    )


def test_from_result_skips_reference_pose_rows(client) -> None:
    """from_result ignores constrained-docking reference_pose rows in Pose results."""
    execution_id = "exec-with-reference-pose"
    client.results.get_poses = lambda **kwargs: {
        "data": [
            {
                "id": "ref-row",
                "compute_job_id": execution_id,
                "data": {
                    "file_path": "tool-runs/job/reference_pose.sdf",
                    "ligand_id": "ref-ligand",
                    "protein_id": "protein-1",
                },
            },
            {
                "id": "pose-row",
                "compute_job_id": execution_id,
                "data": {
                    "best_pose": True,
                    "file_path": "tool-runs/job/pose.sdf",
                    "ligand_id": "query-ligand",
                    "ligand_smiles": "CCO",
                    "pose_score": 0.75,
                    "protein_id": "protein-1",
                },
            },
        ],
        "meta": {},
    }

    poses = LigandSet.from_result(execution_id=execution_id, client=client)

    assert len(poses) == 1
    assert poses.ligands[0].id == "query-ligand"
    assert poses.ligands[0].remote_path == "tool-runs/job/pose.sdf"


def test_load_docking_poses_from_execution_ignores_reference_pose(client) -> None:
    """get_results path loads scored poses even when reference_pose is present."""
    execution_id = "exec-mixed-pose-results"
    client.results.get_poses = lambda **kwargs: {
        "data": [
            {
                "id": "ref-row",
                "compute_job_id": execution_id,
                "data": {
                    "file_path": "tool-runs/job/reference_pose.sdf",
                    "ligand_id": "ref-ligand",
                    "protein_id": "protein-1",
                },
            },
            {
                "id": "pose-row",
                "compute_job_id": execution_id,
                "data": {
                    "best_pose": True,
                    "file_path": "tool-runs/job/pose.sdf",
                    "ligand_id": "query-ligand",
                    "ligand_smiles": "CCO",
                    "pose_score": 0.75,
                    "protein_id": "protein-1",
                },
            },
        ],
        "meta": {},
    }

    poses = load_docking_poses_from_execution(
        execution_id,
        client=client,
        all_poses=True,
    )

    assert len(poses) == 1
    assert poses.ligands[0].properties.get("pose_score") == 0.75


def test_load_docking_poses_from_execution_raises_when_empty(client) -> None:
    """Empty result-explorer and jobOutputs responses raise DeepOriginException."""
    execution_id = "exec-no-poses"
    client.results.get_poses = lambda **kwargs: {"data": [], "meta": {}}
    client.executions.get = lambda _eid: {"jobOutputs": {"poses": []}}

    with pytest.raises(DeepOriginException, match="Could not load docking poses"):
        load_docking_poses_from_execution(execution_id, client=client)

    with pytest.raises(DeepOriginException, match=execution_id):
        load_docking_poses_from_execution(execution_id, client=client)
