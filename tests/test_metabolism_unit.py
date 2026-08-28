"""Unit tests for Metabolism helpers (no platform client)."""

from __future__ import annotations

import pytest

from deeporigin.drug_discovery.metabolism import (
    Metabolism,
    _job_output_rows,
    _ligands_from_inputs,
    _normalize_ligands,
)
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.utils.constants import METABOLISM_WORKFLOW_LIGAND_THRESHOLD


def test_normalize_ligands_accepts_ligand_list_and_set() -> None:
    """A Ligand, a list, or a LigandSet all become a list."""
    lig = Ligand.from_smiles("CCO")
    assert _normalize_ligands(lig) == [lig]
    assert _normalize_ligands([lig]) == [lig]
    assert _normalize_ligands(LigandSet(ligands=[lig])) == [lig]


def test_normalize_ligands_rejects_empty_list() -> None:
    """An empty list is not a valid Metabolism run."""
    with pytest.raises(ValueError, match="at least one ligand"):
        _normalize_ligands([])


def test_normalize_ligands_rejects_empty_ligandset() -> None:
    """An empty LigandSet is not a valid Metabolism run."""
    with pytest.raises(ValueError, match="at least one ligand"):
        _normalize_ligands(LigandSet(ligands=[]))


def test_metabolism_run_rejects_ge_threshold_ligands() -> None:
    """``run()`` rejects workflow-scale batches before create."""
    ligands = [Ligand.from_smiles("CCO")] * METABOLISM_WORKFLOW_LIGAND_THRESHOLD
    job = Metabolism(ligands=ligands)
    with pytest.raises(ValueError, match="start\\(\\) then wait\\(\\) or watch\\(\\)"):
        job.run()


def test_metabolism_construct_accepts_large_batch() -> None:
    """Constructor does not enforce a client-side ligand cap."""
    ligands = [Ligand.from_smiles("CCO")] * (METABOLISM_WORKFLOW_LIGAND_THRESHOLD + 50)
    job = Metabolism(ligands=ligands)
    assert len(job.ligands) == METABOLISM_WORKFLOW_LIGAND_THRESHOLD + 50


def test_metabolism_has_no_enzymes_attribute() -> None:
    """Enzyme selection is not part of the Metabolism API."""
    job = Metabolism(ligands=Ligand.from_smiles("CCO"))
    assert not hasattr(job, "enzymes")
    with pytest.raises(TypeError):
        Metabolism(  # ty:ignore[unexpected-keyword]
            ligands=Ligand.from_smiles("CCO"),
            enzymes=["CYP3A4"],
        )


def test_job_output_rows_reads_sites_and_molecules() -> None:
    """jobOutputs sites and molecules keys yield dict rows."""
    site = {"smiles": "CCO", "enzyme": "CYP3A4"}
    mol = {"smiles": "CCO", "confidence_tier": "high"}
    dto = {"jobOutputs": {"sites": [site], "molecules": [mol]}}
    assert _job_output_rows(dto, key="sites") == [site]
    assert _job_output_rows(dto, key="molecules") == [mol]


def test_job_output_rows_empty_when_missing() -> None:
    """Missing or malformed jobOutputs yields no rows."""
    assert _job_output_rows({}, key="sites") == []
    assert _job_output_rows({"jobOutputs": None}, key="sites") == []
    assert _job_output_rows({"jobOutputs": {"other": []}}, key="sites") == []


def test_ligands_from_inputs_builds_ligands() -> None:
    """Stored ligand SMILES and ids are restored; omitted id stays unset."""
    ligands = _ligands_from_inputs(
        {"ligands": [{"smiles": "CCO", "id": "lig-1"}, {"smiles": "CCN"}]}
    )
    assert [lig.smiles for lig in ligands] == ["CCO", "CCN"]
    assert ligands[0].id == "lig-1"
    assert ligands[1].id is None


def test_ligands_from_inputs_rejects_missing_rows() -> None:
    """Empty or malformed ligand rows fail rehydration."""
    with pytest.raises(ValueError, match="no ligands"):
        _ligands_from_inputs({})
    with pytest.raises(ValueError, match="not an object"):
        _ligands_from_inputs({"ligands": ["CCO"]})
    with pytest.raises(ValueError, match="no SMILES"):
        _ligands_from_inputs({"ligands": [{"id": "1"}]})
