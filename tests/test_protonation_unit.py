"""Unit tests for Protonation constructor and payload helpers."""

from __future__ import annotations

from unittest.mock import patch

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


def test_run_exposes_concentration_list() -> None:
    """run() sets protonation_concentration on each returned Ligand."""
    job = Protonation(smiles="CCO", ph=11.4)

    mock_response = {
        "jobOutputs": {
            "smiles": "CCO",
            "pH": 11.4,
            "filter_percentage": 1,
            "protonation_states": {
                "smiles_list": ["[O-]CC", "OCC"],
                "concentration_list": [79.69, 20.31],
            },
        },
    }
    with patch.object(job, "_create_execution", return_value=mock_response):
        result = job.run()

    assert len(result.ligands) == 2
    assert result.ligands[0].protonation_concentration == pytest.approx(79.69)
    assert result.ligands[1].protonation_concentration == pytest.approx(20.31)
    assert result.ligands[0].protonated_at_ph == 11.4
    assert result.ligands[1].protonated_at_ph == 11.4


def test_run_handles_missing_concentration_list() -> None:
    """run() gracefully handles responses without concentration_list."""
    job = Protonation(smiles="CCO", ph=7.4)

    mock_response = {
        "jobOutputs": {
            "smiles": "CCO",
            "pH": 7.4,
            "filter_percentage": 1,
            "protonation_states": {
                "smiles_list": ["OCC"],
            },
        },
    }
    with patch.object(job, "_create_execution", return_value=mock_response):
        result = job.run()

    assert len(result.ligands) == 1
    assert result.ligands[0].protonation_concentration is None
    assert result.ligands[0].protonated_at_ph == 7.4


def test_run_sets_concentration_on_merged_primary() -> None:
    """run() sets concentration when merging into the primary ligand (ligand= path)."""
    ligand = Ligand.from_smiles("CCO", name="ethanol")
    job = Protonation(ligand=ligand, ph=7.4)

    mock_response = {
        "jobOutputs": {
            "smiles": "CCO",
            "pH": 7.4,
            "filter_percentage": 1,
            "protonation_states": {
                "smiles_list": ["OCC"],
                "concentration_list": [99.93],
            },
        },
    }
    with patch.object(job, "_create_execution", return_value=mock_response):
        result = job.run()

    assert result.ligands[0] is ligand
    assert ligand.protonation_concentration == pytest.approx(99.93)
