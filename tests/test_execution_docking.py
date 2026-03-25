"""Tests for the Docking execution class."""

import time

import pytest

from conftest import check_function_exists, check_tool_exists
from deeporigin.drug_discovery.docking import Docking, _docking_default_name
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.platform.constants import (
    DOCKING_FUNCTION_KEY,
    DOCKING_FUNCTION_VERSION,
    DOCKING_TOOL_KEY,
    DOCKING_TOOL_VERSION,
    TERMINAL_STATES,
)


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
    assert docking.name == (
        f"Docking {registered_protein.name} to {registered_ligand.name.strip()}"
    )


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
