"""Unit tests for :mod:`deeporigin.drug_discovery.rbfe`."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from deeporigin.drug_discovery.rbfe import RBFE, RBFEParams
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.platform.client import DeepOriginClient


def test_rbfe_sysprep_build_params() -> None:
    """Sysprep mode builds pairs[] and prep flags."""
    protein = Protein(name="p", id="prot-1", remote_path="testing/brd.pdb")
    ligand1 = Ligand.from_smiles("CCO", id="lig-1", remote_path="testing/lig1.sdf")
    ligand2 = Ligand.from_smiles("CCN", id="lig-2", remote_path="testing/lig2.sdf")
    rbfe = RBFE(
        protein=protein,
        pairs=[(ligand1, ligand2)],
        prep_only=True,
        retain_waters=False,
        padding=1.5,
    )
    params = rbfe._build_params()
    assert params["mode"] == "sysprep"
    assert params["protein"]["file_path"] == "testing/brd.pdb"
    assert len(params["pairs"]) == 1
    assert params["pairs"][0]["ligand1"]["id"] == "lig-1"
    assert params["pairs"][0]["ligand2"]["id"] == "lig-2"
    assert params["padding"] == 1.5
    assert "binding" not in params


def test_rbfe_rbfe_mode_requires_prepared_systems() -> None:
    """Rbfe-only mode rejects empty prepared_systems."""
    with pytest.raises(ValueError, match="prepared_systems"):
        RBFE(prepared_systems=[])


def test_rbfe_rbfe_mode_build_params() -> None:
    """Rbfe mode serializes prepared_systems and FEP blocks."""
    ps = PreparedSystem(
        binding_xml_path="testing/a.xml",
        solvation_xml_path="testing/b.xml",
        system_pdb_path="testing/c.pdb",
        protein_id="prot-1",
        ligand1_id="lig-1",
        ligand2_id="lig-2",
    )
    rbfe = RBFE(
        prepared_systems=[ps],
        params=RBFEParams(test_run=1),
    )
    params = rbfe._build_params()
    assert params["mode"] == "rbfe"
    assert len(params["prepared_systems"]) == 1
    assert params["prepared_systems"][0]["ligand2_id"] == "lig-2"
    assert params["binding"]["test_run"] == 1
    assert params["solvation"]["test_run"] == 1


def test_rbfe_infers_full_mode_from_protein_and_pairs() -> None:
    """protein + pairs without prep_only selects full mode."""
    protein = Protein(name="p", id="prot-1", remote_path="testing/brd.pdb")
    ligand1 = Ligand.from_smiles("CCO", id="lig-1", remote_path="testing/lig1.sdf")
    ligand2 = Ligand.from_smiles("CCN", id="lig-2", remote_path="testing/lig2.sdf")
    rbfe = RBFE(protein=protein, pairs=[(ligand1, ligand2)])
    assert rbfe.mode == "full"
    assert "binding" in rbfe._build_params()


def test_rbfe_start_calls_executions_create(monkeypatch: pytest.MonkeyPatch) -> None:
    """start() submits deeporigin.rbfe with built params."""
    protein = Protein(name="p", id="prot-1", remote_path="testing/brd.pdb")
    ligand1 = Ligand.from_smiles("CCO", id="lig-1", remote_path="testing/lig1.sdf")
    ligand2 = Ligand.from_smiles("CCN", id="lig-2", remote_path="testing/lig2.sdf")
    client = MagicMock(spec=DeepOriginClient)
    client.executions = MagicMock()
    rbfe = RBFE(
        protein=protein,
        pairs=[(ligand1, ligand2)],
        prep_only=True,
        client=client,
    )
    rbfe.client.executions.create.return_value = {
        "executionId": "exec-123",
        "status": "Created",
        "tool": {"key": "deeporigin.rbfe", "version": "0.1.0"},
    }
    monkeypatch.setattr(protein, "sync", MagicMock())
    monkeypatch.setattr(ligand1, "sync", MagicMock())
    monkeypatch.setattr(ligand2, "sync", MagicMock())

    rbfe.start()

    rbfe.client.executions.create.assert_called_once()
    call_kwargs = rbfe.client.executions.create.call_args.kwargs
    assert call_kwargs["tool_key"] == "deeporigin.rbfe"
    assert call_kwargs["data"]["inputs"]["mode"] == "sysprep"
