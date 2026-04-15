"""Tests for the Docking execution class."""

import json
from pathlib import Path
import time

import pandas as pd
import pytest

from conftest import check_function_exists, check_tool_exists
from deeporigin.drug_discovery.docking import (
    Docking,
    _docking_default_name,
    _ligand_tool_input_row,
    _pose_rows_from_result_explorer,
)
from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.platform.constants import (
    DOCKING_FUNCTION_KEY,
    DOCKING_FUNCTION_VERSION,
    DOCKING_TOOL_KEY,
    DOCKING_TOOL_VERSION,
    TERMINAL_STATES,
)
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


def test_docking_build_tool_inputs_does_not_sync(
    monkeypatch,
    client,
    registered_protein,
    registered_pocket,
    registered_ligand,
) -> None:
    """_build_tool_inputs only serializes state; it does not call sync."""

    def _fail(*_args, **_kwargs) -> None:
        raise AssertionError("sync must not be called from _build_tool_inputs")

    docking = Docking(
        protein=registered_protein,
        pocket=registered_pocket,
        ligand=registered_ligand,
        client=client,
    )
    monkeypatch.setattr(docking.protein, "sync", _fail)
    monkeypatch.setattr(docking.ligands, "sync", _fail)

    params, metadata = docking._build_tool_inputs()

    assert params["effort"] == docking.effort
    assert params["protein"]["id"] == registered_protein.id
    assert params["ligands"][0]["smiles"] == registered_ligand.smiles
    assert "protein_hash" in metadata


def test_docking_default_name_helper():
    """_docking_default_name matches single-, multi-, and empty-ligand rules."""
    from deeporigin.drug_discovery import BRD_DATA_DIR
    from deeporigin.drug_discovery.structures.protein import Protein

    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    assert _docking_default_name(protein=protein, ligands=LigandSet()) == (
        f"Docking {protein.name} to 0 ligands."
    )

    a = Ligand.from_smiles("CC", name="")
    b = Ligand.from_smiles("CCC", name="")
    assert _docking_default_name(
        protein=protein,
        ligands=LigandSet(ligands=[a, b]),
    ) == (f"Docking {protein.name} to 2 ligands.")

    assert _docking_default_name(
        protein=protein,
        ligands=LigandSet(ligands=[a]),
    ) == (f"Docking {protein.name} to {a.smiles}")

    named = Ligand.from_smiles("CC", name="  my-inhibitor  ")
    assert _docking_default_name(
        protein=protein,
        ligands=LigandSet(ligands=[named]),
    ) == (f"Docking {protein.name} to my-inhibitor")


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
    if not check_tool_exists(client, DOCKING_TOOL_KEY, DOCKING_TOOL_VERSION):
        pytest.skip("Docking tool does not exist")

    docking = Docking(
        protein=registered_protein,
        pocket=registered_pocket,
        ligand=registered_ligand,
    )
    docking.quote()

    assert docking.estimate is not None, "Estimate should be set"
    assert docking.cost is None, "Cost should be None"


def test_docking_quote_raises_when_quotation_result_missing(
    monkeypatch,
    client,
    registered_protein,
    registered_pocket,
    registered_ligand,
) -> None:
    """Quote flow raises RuntimeError when quotationResult is absent."""
    docking = Docking(
        protein=registered_protein,
        pocket=registered_pocket,
        ligand=registered_ligand,
        client=client,
    )

    def _fake_create(*_a: object, **_k: object) -> dict:
        return {"executionId": "exec-1", "status": "Quoted"}

    monkeypatch.setattr(client.executions, "create", _fake_create)

    with pytest.raises(RuntimeError, match="Quote failed: quotationResult is missing"):
        docking.quote()


def test_docking_quote_raises_when_successful_quotations_missing(
    monkeypatch,
    client,
    registered_protein,
    registered_pocket,
    registered_ligand,
) -> None:
    """Quote flow raises RuntimeError when successfulQuotations is absent."""
    docking = Docking(
        protein=registered_protein,
        pocket=registered_pocket,
        ligand=registered_ligand,
        client=client,
    )

    def _fake_create(*_a: object, **_k: object) -> dict:
        return {
            "executionId": "exec-1",
            "status": "Quoted",
            "quotationResult": {},
        }

    monkeypatch.setattr(client.executions, "create", _fake_create)

    with pytest.raises(
        RuntimeError, match="Quote failed: successfulQuotations is missing"
    ):
        docking.quote()


def test_docking_quote_raises_when_no_successful_quotations(
    monkeypatch,
    client,
    registered_protein,
    registered_pocket,
    registered_ligand,
) -> None:
    """Quote flow raises RuntimeError when successfulQuotations is empty."""
    docking = Docking(
        protein=registered_protein,
        pocket=registered_pocket,
        ligand=registered_ligand,
        client=client,
    )

    def _fake_create(*_a: object, **_k: object) -> dict:
        return {
            "executionId": "exec-1",
            "status": "Quoted",
            "quotationResult": {"successfulQuotations": []},
        }

    monkeypatch.setattr(client.executions, "create", _fake_create)

    with pytest.raises(RuntimeError, match="Quote failed: no successful quotations"):
        docking.quote()


def test_docking_quote_raises_when_price_total_missing(
    monkeypatch,
    client,
    registered_protein,
    registered_pocket,
    registered_ligand,
) -> None:
    """Quote flow raises RuntimeError when priceTotal is absent."""
    docking = Docking(
        protein=registered_protein,
        pocket=registered_pocket,
        ligand=registered_ligand,
        client=client,
    )

    def _fake_create(*_a: object, **_k: object) -> dict:
        return {
            "executionId": "exec-1",
            "status": "Quoted",
            "quotationResult": {"successfulQuotations": [{}]},
        }

    monkeypatch.setattr(client.executions, "create", _fake_create)

    with pytest.raises(RuntimeError, match="Quote failed: priceTotal is missing"):
        docking.quote()


def test_docking_run_lv2(
    client,
    registered_protein,
    registered_pocket,
    registered_ligand,
):
    """Run docking synchronously via run() and assert poses returned."""
    if not check_function_exists(
        client, DOCKING_FUNCTION_KEY, DOCKING_FUNCTION_VERSION
    ):
        pytest.skip("Docking function does not exist")

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


def test_docking_get_results_dataframe_from_api_rows_lv1(
    monkeypatch,
    client,
    registered_protein,
    registered_pocket,
    registered_ligand,
) -> None:
    """get_results maps pose API rows to a DataFrame with expected columns."""
    docking = Docking(
        protein=registered_protein,
        pocket=registered_pocket,
        ligand=registered_ligand,
        client=client,
    )
    docking._id = "0acc1213-4aa1-48e7-ada9-fbd6331f01d9"

    pose_rows = [
        {
            "id": "0921B27C5YXZ7",
            "tool_key": "deeporigin.bulk-docking",
            "data": {
                "file_path": "tool-runs/uuid/pose.sdf",
                "ligand_id": "08DK80B7DYTXH",
                "pocket_id": "08HXY85NDYYXG",
                "pose_score": 0.9767475,
                "protein_id": "08CEVZZPNYV31",
                "binding_energy": -8.131386,
                "best_pose": True,
            },
            "compute_job_id": "0acc1213-4aa1-48e7-ada9-fbd6331f01d9",
        }
    ]
    monkeypatch.setattr(
        Execution,
        "get_results",
        lambda self: {"data": pose_rows},
    )

    df = docking.get_results()
    assert df is not None
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == list(DOCKING_RESULTS_DATAFRAME_COLUMNS)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["ID"] == "0921B27C5YXZ7"
    assert row["protein ID"] == "08CEVZZPNYV31"
    assert row["ligand ID"] == "08DK80B7DYTXH"
    assert row["pocket ID"] == "08HXY85NDYYXG"
    assert row["binding energy"] == pytest.approx(-8.131386)
    assert row["pose_score"] == pytest.approx(0.9767475)
    assert row["best_pose"]


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


def test_docking_get_results_empty_returns_none_lv1(
    monkeypatch,
    client,
    registered_protein,
    registered_pocket,
    registered_ligand,
) -> None:
    """get_results returns None when the API returns no pose rows."""
    docking = Docking(
        protein=registered_protein,
        pocket=registered_pocket,
        ligand=registered_ligand,
        client=client,
    )
    docking._id = "job-id"

    monkeypatch.setattr(Execution, "get_results", lambda self: {"data": []})

    assert docking.get_results() is None


def test_docking_start_sync_get_results_lv3(
    client,
    registered_protein,
    registered_pocket,
    registered_ligand,
):
    """Start docking asynchronously via start(), sync until done, then get_results()."""
    if client.env == "local":
        pytest.skip("start/sync/get_results docking flow not run against local mock")

    if not check_tool_exists(client, DOCKING_TOOL_KEY, DOCKING_TOOL_VERSION):
        pytest.skip("Docking tool does not exist")

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
