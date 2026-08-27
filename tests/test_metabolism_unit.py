"""Unit tests for Metabolism helpers (no platform client)."""

from __future__ import annotations

import pytest

from deeporigin.drug_discovery.metabolism import (
    Metabolism,
    _ensure_ligand_cap,
    _job_output_rows,
    _ligands_from_inputs,
    _normalize_ligands,
    _validate_metabolism_enzymes,
)
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.utils.constants import METABOLISM_ENZYMES, METABOLISM_LIGAND_CAP


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


def test_ensure_ligand_cap_rejects_over_250() -> None:
    """More than 250 ligands is a client-side ValueError."""
    ligands = [Ligand.from_smiles("CCO")] * (METABOLISM_LIGAND_CAP + 1)
    with pytest.raises(ValueError, match="at most 250"):
        _ensure_ligand_cap(ligands)
    _ensure_ligand_cap([Ligand.from_smiles("CCO")])


def test_validate_metabolism_enzymes_rejects_empty_unknown_and_duplicates() -> None:
    """Draft selections must be a non-empty unique subset of the nine CYP names."""
    allowed = frozenset(METABOLISM_ENZYMES)
    assert _validate_metabolism_enzymes(["CYP3A4"], allowed=allowed) == ["CYP3A4"]
    with pytest.raises(ValueError, match="non-empty"):
        _validate_metabolism_enzymes([], allowed=allowed)
    with pytest.raises(ValueError, match="duplicates"):
        _validate_metabolism_enzymes(["CYP3A4", "CYP3A4"], allowed=allowed)
    with pytest.raises(ValueError, match="Unknown"):
        _validate_metabolism_enzymes(["CYP3A5"], allowed=allowed)


def test_ensure_enzymes_for_run_preserves_frozen_tuple() -> None:
    """A re-run on an already-executed instance keeps ``enzymes`` a tuple.

    ``_ensure_enzymes_for_run`` must not leave a mutable list on
    ``self._enzymes`` if it runs again on an instance whose execution id is
    already set (``enzymes`` frozen to a tuple) — that would break the
    tuple/list invariant if ``_create_execution`` then raised before
    ``update_from_dto`` re-froze it.
    """
    job = Metabolism(ligands=Ligand.from_smiles("CCO"))
    job._enzymes = tuple(METABOLISM_ENZYMES)
    job._id = "existing-execution-id"

    job._ensure_enzymes_for_run()

    assert isinstance(job._enzymes, tuple)
    assert job._enzymes == METABOLISM_ENZYMES


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
