"""Tests for the Docking execution class."""

import time

import pytest

from conftest import check_function_exists, check_tool_exists
from deeporigin.drug_discovery.docking import Docking
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import (
    DOCKING_FUNCTION_KEY,
    DOCKING_FUNCTION_VERSION,
    DOCKING_TOOL_KEY,
    DOCKING_TOOL_VERSION,
    TERMINAL_STATES,
)


def test_docking_from_id_rehydrates_without_downloading_structure_files(monkeypatch):
    """from_id sets remote_path from userInputs and does not call files.download.

    Uses the local mock server (``--env local``): execution and entity rows come
    from ``tests/fixtures/executions/exec-dock-1.json`` and related fixtures.
    """

    def _fail_download(*_args, **_kwargs):
        raise AssertionError(
            "files.download must not be called when rehydrating Docking.from_id"
        )

    client = DeepOriginClient()
    monkeypatch.setattr(client.files, "download", _fail_download)

    exec_id = "exec-dock-1"
    protein_id = "prot-1"
    lig_id = "lig-1"
    remote_protein_path = "entities/proteins/abc.pdb"
    remote_mol_path = "entities/ligands/lig.sdf"
    expected_ligand_smiles = "C1C2C3CC2C13"

    docking = Docking.from_id(exec_id, client=client)

    assert docking.name == "dock-from-id-test"
    assert docking.protein.id == protein_id
    assert docking.protein.remote_path == remote_protein_path
    assert docking.protein.structure is None
    assert len(docking.ligands) == 1
    lig = list(docking.ligands)[0]
    assert lig.id == lig_id
    assert lig.remote_path == remote_mol_path
    assert lig.smiles == expected_ligand_smiles


def test_docking_accepts_single_ligand(
    registered_protein, registered_pocket, registered_ligand
):
    """Docking accepts a single ligand and converts it to LigandSet."""
    docking = Docking(
        protein=registered_protein,
        pocket=registered_pocket,
        ligand=registered_ligand,
    )
    assert isinstance(docking.ligands, LigandSet)
    assert len(docking.ligands) == 1
    assert list(docking.ligands)[0].smiles == registered_ligand.smiles


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
    registered_protein,
    registered_pocket,
    registered_ligand,
):
    """Docking quote() raises ValueError if called after a quotation already exists."""
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

    poses = docking.get_results()
    assert poses is not None, "get_results() should return poses after Succeeded"
    assert len(poses) >= 1, "Expected at least one pose"
    for pose in poses:
        assert isinstance(pose, Ligand), "Each pose should be a Ligand"
        assert pose.mol is not None, "Pose should have a loaded RDKit mol"
        assert pose.smiles is not None, "Pose should have SMILES"
