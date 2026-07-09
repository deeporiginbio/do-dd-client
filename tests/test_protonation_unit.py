"""Unit tests for Protonation constructor and payload helpers."""

from __future__ import annotations

import pytest

from deeporigin.drug_discovery.protonation import Protonation, _execution_outputs_dict
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet


def test_execution_outputs_dict_from_dict() -> None:
    """_execution_outputs_dict returns a dict jobOutputs payload unchanged."""
    payload = {"pH": 7.4, "protonation_states": {"smiles_list": ["CCO"]}}
    assert _execution_outputs_dict({"jobOutputs": payload}) == payload


def test_execution_outputs_dict_from_list() -> None:
    """_execution_outputs_dict unwraps a one-element jobOutputs list."""
    payload = {"pH": 7.0}
    assert _execution_outputs_dict({"jobOutputs": [payload]}) == payload


def test_execution_outputs_dict_empty() -> None:
    """_execution_outputs_dict returns {} when jobOutputs is missing."""
    assert _execution_outputs_dict({}) == {}


def test_protonation_requires_exactly_one_input() -> None:
    """Protonation rejects zero or multiple input sources."""
    with pytest.raises(ValueError, match="Exactly one"):
        Protonation()

    with pytest.raises(ValueError, match="Exactly one"):
        Protonation(smiles="CCO", ligand=Ligand.from_smiles("CCO"))


def test_protonation_rejects_multi_ligand_set() -> None:
    """Protonation accepts only a single-ligand LigandSet."""
    ligands = LigandSet(
        ligands=[Ligand.from_smiles("CCO"), Ligand.from_smiles("c1ccccc1")]
    )

    with pytest.raises(ValueError, match="single ligand"):
        Protonation(ligands=ligands)


def test_protonation_rejects_empty_smiles() -> None:
    """Protonation requires a non-empty SMILES on the input ligand."""
    ligand = Ligand.from_smiles("CCO")
    ligand.smiles = ""

    with pytest.raises(ValueError, match="non-empty SMILES"):
        Protonation(ligand=ligand)


def test_protonation_make_inputs_includes_id() -> None:
    """_make_inputs includes ligand id when present."""
    ligand = Ligand.from_smiles("CCO", id="lig-1")
    job = Protonation(ligand=ligand, ph=6.5, filter_percentage=0.5)

    inputs = job._make_inputs()

    assert inputs == {
        "ligand": {"smiles": "CCO", "id": "lig-1"},
        "pH": 6.5,
        "filter_percentage": 0.5,
    }


def test_protonation_make_payload_sync_flag() -> None:
    """_make_payload includes sync=True and approveAmount when provided."""
    job = Protonation(smiles="CCO")

    payload = job._make_payload(approve_amount=0, sync=True)

    assert payload["sync"] is True
    assert payload["approveAmount"] == 0
    assert payload["inputs"]["ligand"]["smiles"] == "CCO"
