"""Tests for the Docking execution class."""

import json
from pathlib import Path
import time

import pytest

from conftest import check_function_exists, check_tool_exists
from deeporigin.drug_discovery.docking import (
    Docking,
    _docking_default_name,
    _ligand_tool_input_row,
    _pose_rows_from_result_explorer,
)
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.platform.constants import TERMINAL_STATES, TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import DOCKING_RESULTS_DATAFRAME_COLUMNS


def test_docking_from_dto_maps_async_execution_fields_from_fixture(
    client,
) -> None:
    """from_dto maps common async execution fields from fixture DTO."""
    fixture_path = (
        Path(__file__).parent / "fixtures/executions/docking-test-execution.json"
    )
    dto = json.loads(fixture_path.read_text())

    docking = Docking.from_dto(dto, client=client)

    assert docking.completed_at == dto["completedAt"]
    assert docking.id == dto["executionId"]
    assert docking.created_by == dto["createdBy"]
    assert docking.created_at == dto["createdAt"]
    assert docking.started_at == dto["startedAt"]
    assert docking.session == dto["session"]
    assert docking.status == dto["status"]
    assert docking.app == dto["app"]
    assert docking.approve_amount == dto["approveAmount"]
    assert docking.effort == Docking.effort


def test_docking_from_dto_initializes_notebook_watch_state(client) -> None:
    """from_dto skips __init__; notebook watch attrs must exist for stop_watching."""
    fixture_path = (
        Path(__file__).parent / "fixtures/executions/docking-test-execution.json"
    )
    dto = json.loads(fixture_path.read_text())

    docking = Docking.from_dto(dto, client=client)
    assert docking._watch_task is None
    assert docking._display_id is None
    assert docking._last_html is None
    docking.stop_watching()


def test_docking_from_dto_raises_on_tool_key_mismatch(client) -> None:
    """from_dto fails fast when DTO tool key does not match Docking.tool_key."""
    fixture_path = (
        Path(__file__).parent / "fixtures/executions/docking-test-execution.json"
    )
    dto = json.loads(fixture_path.read_text())
    dto["tool"]["key"] = "deeporigin.abfe-end-to-end"

    with pytest.raises(ValueError, match="tool key mismatch"):
        Docking.from_dto(dto, client=client)


def test_docking_accepts_single_ligand(
    registered_protein, registered_pocket, registered_ligand
):
    """Docking accepts a single ligand and converts it to LigandSet."""
    docking = Docking(
        protein=registered_protein,
        pocket=registered_pocket,
        ligand=registered_ligand,
        effort=5,
    )
    assert docking.effort == 5
    assert isinstance(docking.ligands, LigandSet)
    assert len(docking.ligands) == 1
    assert list(docking.ligands)[0].smiles == registered_ligand.smiles
    assert docking.name == (
        f"Docking {registered_protein.name} to {registered_ligand.name.strip()}"
    )


def test_ligand_tool_input_row_excludes_mol_file() -> None:
    """Bulk-docking userInputs include only schema-defined ligand fields."""
    ligand = Ligand.from_smiles("CCO")
    ligand.id = "lig-123"
    ligand.remote_path = "entities/ligands/lig-123.sdf"

    row = _ligand_tool_input_row(ligand)

    assert row == {"id": "lig-123", "smiles": "CCO"}
    assert "mol_file" not in row


def test_docking_default_name_helper():
    """_docking_default_name matches single-, multi-, and empty-ligand rules."""
    from deeporigin.drug_discovery import BRD_DATA_DIR
    from deeporigin.drug_discovery.structures.protein import Protein

    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    assert _docking_default_name(protein, LigandSet()) == (
        f"Docking {protein.name} to 0 ligands."
    )

    a = Ligand.from_smiles("CC", name="")
    b = Ligand.from_smiles("CCC", name="")
    assert _docking_default_name(protein, LigandSet(ligands=[a, b])) == (
        f"Docking {protein.name} to 2 ligands."
    )

    assert _docking_default_name(protein, LigandSet(ligands=[a])) == (
        f"Docking {protein.name} to {a.smiles}"
    )

    named = Ligand.from_smiles("CC", name="  my-inhibitor  ")
    assert _docking_default_name(protein, LigandSet(ligands=[named])) == (
        f"Docking {protein.name} to my-inhibitor"
    )


def test_docking_accepts_explicit_name_override(
    registered_protein, registered_pocket, registered_ligand
):
    """Optional ``name`` replaces the auto-generated execution label."""
    docking = Docking(
        protein=registered_protein,
        pocket=registered_pocket,
        ligand=registered_ligand,
        name="Custom docking label",
    )
    assert docking.name == "Custom docking label"


def test_docking_rejects_both_ligand_and_ligands(
    registered_protein, registered_pocket, registered_ligand
):
    """Docking raises ValueError when both ligand and ligands are provided."""
    ligands = LigandSet(ligands=[registered_ligand])
    with pytest.raises(ValueError, match="Exactly one of"):
        Docking(
            protein=registered_protein,
            pocket=registered_pocket,
            ligand=registered_ligand,
            ligands=ligands,
        )


def test_docking_quote_cannot_be_called_twice_lv0(
    registered_protein, registered_pocket, registered_ligand
):
    """quote() raises ValueError if called after a quotation already exists."""
    docking = Docking(
        protein=registered_protein,
        pocket=registered_pocket,
        ligand=registered_ligand,
    )
    docking._id = "exec-quoted-456"
    docking.status = "Quoted"

    with pytest.raises(ValueError, match="quotation already exists"):
        docking.quote()


def test_docking_quote_lv1(
    client,
    registered_protein,
    registered_pocket,
    registered_ligand,
):
    """Docking quote() raises ValueError if called after a quotation already exists."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["docking"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["docking"]["tool_version"],
    ), "Docking tool not registered on platform (expected key/version)."

    docking = Docking(
        protein=registered_protein,
        pocket=registered_pocket,
        ligand=registered_ligand,
    )
    docking.quote()

    assert docking.estimate is not None, "Estimate should be set"
    assert docking.cost is None, "Cost should be None"


def test_docking_run_lv2(
    client,
    registered_protein,
    registered_pocket,
    registered_ligand,
):
    """Run docking synchronously via run() and assert poses returned."""
    assert check_function_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["docking"]["function_key"],
        TOOL_KEYS_AND_VERSIONS["docking"]["function_version"],
    ), "Docking function not registered on platform (expected key/version)."

    docking = Docking(
        protein=registered_protein,
        pocket=registered_pocket,
        ligand=registered_ligand,
        client=client,
    )
    poses = docking.run()

    assert isinstance(poses, LigandSet), "run() should return a LigandSet"
    assert len(poses) >= 1, "Expected at least one pose"
    for pose in poses:
        assert isinstance(pose, Ligand), "Each pose should be a Ligand"
        assert pose.mol is not None, "Pose should have a loaded RDKit mol"
        assert pose.smiles is not None, "Pose should have SMILES"


def test_pose_rows_from_result_explorer_keeps_pose_and_legacy_rows_lv1() -> None:
    """Mixed result-explorer rows are filtered to poses (and legacy rows without type)."""
    response = {
        "data": [
            {"id": "pocket-1", "result_type": "pocket", "data": {}},
            {"id": "pose-1", "result_type": "pose", "data": {"ligand_id": "L1"}},
            {"id": "legacy", "data": {"ligand_id": "L2"}},
        ]
    }
    rows = _pose_rows_from_result_explorer(response)
    assert [r["id"] for r in rows] == ["pose-1", "legacy"]


def test_docking_start_sync_get_results_lv3(
    client,
    registered_protein,
    registered_pocket,
    registered_ligand,
):
    """Start docking asynchronously via start(), sync until done, then get_results()."""
    if client.env == "local":
        pytest.skip("start/sync/get_results docking flow not run against local mock")

    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["docking"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["docking"]["tool_version"],
    ), "Docking tool not registered on platform (expected key/version)."

    docking = Docking(
        protein=registered_protein,
        pocket=registered_pocket,
        ligand=registered_ligand,
        client=client,
    )
    docking.start()

    # If backend returns Quoted (quote-then-confirm flow), confirm to run
    docking.sync()
    if docking.status == "Quoted":
        docking.start()
    elif docking.status in TERMINAL_STATES and docking.status != "Succeeded":
        pytest.fail(f"Docking reached terminal state {docking.status!r} before running")

    timeout_seconds = 600
    poll_interval = 10
    elapsed = 0
    while elapsed < timeout_seconds:
        docking.sync()
        if docking.status in TERMINAL_STATES:
            break
        time.sleep(poll_interval)
        elapsed += poll_interval
    else:
        pytest.fail(
            f"Docking did not reach a terminal state within {timeout_seconds}s; "
            f"last status={docking.status!r}"
        )

    assert docking.status == "Succeeded", (
        f"Expected status Succeeded, got {docking.status!r}"
    )

    df = docking.get_results()
    assert df is not None, "get_results() should return a DataFrame after Succeeded"
    assert list(df.columns) == list(DOCKING_RESULTS_DATAFRAME_COLUMNS)
    assert len(df) >= 1, "Expected at least one result row"

    poses = docking.get_poses()
    assert poses is not None, "get_poses() should return poses after Succeeded"
    assert len(poses) >= 1, "Expected at least one pose"
    for pose in poses:
        assert isinstance(pose, Ligand), "Each pose should be a Ligand"
        assert pose.mol is not None, "Pose should have a loaded RDKit mol"
        assert pose.smiles is not None, "Pose should have SMILES"
