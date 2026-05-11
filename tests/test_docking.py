"""Tests for :class:`deeporigin.drug_discovery.docking.Docking`."""

import json
from pathlib import Path
import time

import pytest

from deeporigin.drug_discovery.docking import (
    Docking,
    _docking_default_name,
    _ligand_tool_input_row,
)
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.constants import TERMINAL_STATES, TOOL_KEYS_AND_VERSIONS
from tests.conftest import check_tool_exists


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
    dto["tool"]["key"] = "deeporigin.foo-fake-tool"

    with pytest.raises(ValueError, match="tool key mismatch"):
        Docking.from_dto(dto, client=client)


def test_unregistered_pocket_payload_has_nonzero_box_sizes(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """Disk-loaded pocket (no platform id) must not produce zero docking box extents."""
    docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
        client=client,
    )
    params, _ = docking._build_tool_inputs()
    pocket_in = params["pocket"]
    assert float(pocket_in["box_size_x"]) > 0
    assert float(pocket_in["box_size_y"]) > 0
    assert float(pocket_in["box_size_z"]) > 0


def test_docking_accepts_single_ligand(
    registered_protein, unregistered_pocket, registered_ligand
):
    """Docking accepts a single ligand and converts it to LigandSet."""
    docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
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
    registered_protein, unregistered_pocket, registered_ligand
):
    """Optional ``name`` replaces the auto-generated execution label."""
    docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
        name="Custom docking label",
    )
    assert docking.name == "Custom docking label"


def test_docking_rejects_both_ligand_and_ligands(
    registered_protein, unregistered_pocket, registered_ligand
):
    """Docking raises ValueError when both ligand and ligands are provided."""
    ligands = LigandSet(ligands=[registered_ligand])
    with pytest.raises(ValueError, match="Exactly one of"):
        Docking(
            protein=registered_protein,
            pocket=unregistered_pocket,
            ligand=registered_ligand,
            ligands=ligands,
        )


def test_docking_quote_cannot_be_called_twice_lv0(
    registered_protein, unregistered_pocket, registered_ligand
):
    """quote() raises ValueError if called after a quotation already exists."""
    docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
    )
    docking._id = "exec-quoted-456"
    docking.status = "Quoted"

    with pytest.raises(ValueError, match="quotation already exists"):
        docking.quote()


def test_docking_quote_lv1(
    client,
    registered_protein,
    unregistered_pocket,
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
        pocket=unregistered_pocket,
        ligand=registered_ligand,
    )
    docking.quote()

    assert docking.estimate is not None, "Estimate should be set"
    assert docking.cost is None, "Cost should be None"


def test_docking_start_rejects_single_ligand(
    registered_protein, unregistered_pocket, registered_ligand
) -> None:
    """start() is only for multi-ligand async; single-ligand must use run()."""
    docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
    )
    with pytest.raises(ValueError, match="run\\("):
        docking.start()


def test_docking_run_rejects_multiple_ligands(
    registered_protein,
    unregistered_pocket,
    registered_ligand,
    client,
) -> None:
    """run() is only for a single ligand; multi-ligand jobs must use start()."""
    second = Ligand.from_smiles("CCO")
    two = LigandSet(ligands=[registered_ligand, second])
    docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligands=two,
        client=client,
    )
    with pytest.raises(ValueError, match="exactly one ligand"):
        docking.run()


def test_docking_run_rejects_effort_out_of_range(
    client,
    registered_protein,
    registered_ligand,
    unregistered_pocket,
) -> None:
    """:meth:`Docking.run` raises when ``effort`` is outside 1–5."""
    with pytest.raises(DeepOriginException):
        Docking(
            protein=registered_protein,
            pocket=unregistered_pocket,
            ligand=registered_ligand,
            client=client,
            effort=0,
        ).run()


def test_docking_run_lv2(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
):
    """Run docking synchronously via run() and assert poses returned."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["docking"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["docking"]["tool_version"],
    ), "Docking tool not registered on platform (expected key/version)."

    docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
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


def test_docking_start_sync_get_results_lv3(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
):
    """Start docking asynchronously via start() with 2+ ligands; sync; get results."""
    if client.env == "local":
        pytest.skip("start/sync/get_results docking flow not run against local mock")

    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["docking"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["docking"]["tool_version"],
    ), "Docking tool not registered on platform (expected key/version)."

    second = Ligand.from_smiles("CCO")
    second.sync(client=client, lazy=True)
    two_ligands = LigandSet(ligands=[registered_ligand, second])

    docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligands=two_ligands,
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

    poses = docking.get_results()
    assert poses is not None, "get_results() should return a LigandSet after Succeeded"
    assert isinstance(poses, LigandSet), "get_results() should return a LigandSet"
    assert len(poses) >= 1, "Expected at least one pose"
    for pose in poses:
        assert isinstance(pose, Ligand), "Each pose should be a Ligand"
        assert pose.smiles is not None, "Pose should have SMILES"

    df = poses.to_dataframe()
    assert df is not None, "to_dataframe() should return a DataFrame"
    assert len(df) >= 1, "Expected at least one result row"

    sdf_poses = docking.get_poses()
    assert sdf_poses is not None, "get_poses() should return poses after Succeeded"
    assert len(sdf_poses) >= 1, "Expected at least one pose"
    for pose in sdf_poses:
        assert isinstance(pose, Ligand), "Each pose should be a Ligand"
        assert pose.mol is not None, "Pose should have a loaded RDKit mol"
        assert pose.smiles is not None, "Pose should have SMILES"
