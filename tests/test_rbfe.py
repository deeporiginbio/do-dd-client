"""Unit tests for :mod:`deeporigin.drug_discovery.rbfe`."""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.rbfe import RBFE, RBFEParams, _rbfe_results_dataframe
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS


def test_rbfe_sysprep_build_params() -> None:
    """System-prep-only steps build pairs[] and prep flags."""
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
    assert params["steps"] == ["system-prep"]
    assert params["protein"]["file_path"] == "testing/brd.pdb"
    assert len(params["pairs"]) == 1
    assert params["pairs"][0]["ligand1"]["id"] == "lig-1"
    assert params["pairs"][0]["ligand2"]["id"] == "lig-2"
    assert params["padding"] == pytest.approx(1.5)
    assert "binding" not in params


def test_rbfe_rbfe_steps_require_prepared_systems() -> None:
    """RBFE-only steps reject empty prepared_systems."""
    with pytest.raises(ValueError, match="prepared_systems"):
        RBFE(prepared_systems=[])


def test_rbfe_rbfe_steps_build_params() -> None:
    """RBFE-only steps serialize prepared_systems and FEP blocks."""
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
    assert params["steps"] == ["rbfe"]
    assert len(params["prepared_systems"]) == 1
    assert params["prepared_systems"][0]["ligand2_id"] == "lig-2"
    assert params["binding"]["test_run"] == 1
    assert params["solvation"]["test_run"] == 1


def test_rbfe_infers_combined_steps_from_protein_and_pairs() -> None:
    """protein + pairs without prep_only selects system-prep + RBFE steps."""
    protein = Protein(name="p", id="prot-1", remote_path="testing/brd.pdb")
    ligand1 = Ligand.from_smiles("CCO", id="lig-1", remote_path="testing/lig1.sdf")
    ligand2 = Ligand.from_smiles("CCN", id="lig-2", remote_path="testing/lig2.sdf")
    rbfe = RBFE(protein=protein, pairs=[(ligand1, ligand2)])
    assert rbfe.steps == ["system-prep", "rbfe"]
    assert "binding" in rbfe._build_params()


def test_rbfe_ensure_synced_inputs_ensures_remote_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """start() ensures remote_path after lazy sync (metadata-only rehydration)."""
    protein = Protein(name="p", id="prot-1", remote_path=None)
    ligand1 = Ligand.from_smiles("CCO", id="lig-1", remote_path=None)
    ligand2 = Ligand.from_smiles("CCN", id="lig-2", remote_path=None)
    client = MagicMock(spec=DeepOriginClient)
    executions = MagicMock()
    client.executions = executions
    rbfe = RBFE(
        protein=protein,
        pairs=[(ligand1, ligand2)],
        prep_only=True,
        client=client,
    )
    executions.create.return_value = {
        "executionId": "exec-123",
        "status": "Created",
        "tool": {"key": "deeporigin.rbfe", "version": "0.1.0"},
    }
    protein.ensure_remote_path = MagicMock(
        side_effect=lambda **_: setattr(protein, "remote_path", "testing/brd.pdb")
    )
    ligand1.ensure_remote_path = MagicMock(
        side_effect=lambda **_: setattr(ligand1, "remote_path", "testing/lig1.sdf")
    )
    ligand2.ensure_remote_path = MagicMock(
        side_effect=lambda **_: setattr(ligand2, "remote_path", "testing/lig2.sdf")
    )
    monkeypatch.setattr(protein, "sync", MagicMock())
    monkeypatch.setattr(ligand1, "sync", MagicMock())
    monkeypatch.setattr(ligand2, "sync", MagicMock())

    rbfe.start()

    protein.ensure_remote_path.assert_called_once()
    ligand1.ensure_remote_path.assert_called_once()
    ligand2.ensure_remote_path.assert_called_once()
    call_kwargs = executions.create.call_args.kwargs
    assert call_kwargs["data"]["inputs"]["protein"]["file_path"] == "testing/brd.pdb"


def test_rbfe_start_calls_executions_create(monkeypatch: pytest.MonkeyPatch) -> None:
    """start() submits deeporigin.rbfe with built params."""
    protein = Protein(name="p", id="prot-1", remote_path="testing/brd.pdb")
    ligand1 = Ligand.from_smiles("CCO", id="lig-1", remote_path="testing/lig1.sdf")
    ligand2 = Ligand.from_smiles("CCN", id="lig-2", remote_path="testing/lig2.sdf")
    client = MagicMock(spec=DeepOriginClient)
    executions = MagicMock()
    client.executions = executions
    rbfe = RBFE(
        protein=protein,
        pairs=[(ligand1, ligand2)],
        prep_only=True,
        client=client,
    )
    executions.create.return_value = {
        "executionId": "exec-123",
        "status": "Created",
        "tool": {"key": "deeporigin.rbfe", "version": "0.1.0"},
    }
    monkeypatch.setattr(protein, "sync", MagicMock())
    monkeypatch.setattr(ligand1, "sync", MagicMock())
    monkeypatch.setattr(ligand2, "sync", MagicMock())

    rbfe.start()

    executions.create.assert_called_once()
    call_kwargs = executions.create.call_args.kwargs
    assert call_kwargs["tool_key"] == "deeporigin.rbfe"
    assert call_kwargs["data"]["inputs"]["steps"] == ["system-prep"]


def test_rbfe_start_quote_sums_workflow_quotations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """start(quote=True) sums all successful quotation rows for prep+FEP workflows."""
    protein = Protein(name="p", id="prot-1", remote_path="testing/brd.pdb")
    ligand1 = Ligand.from_smiles("CCO", id="lig-1", remote_path="testing/lig1.sdf")
    ligand2 = Ligand.from_smiles("CCN", id="lig-2", remote_path="testing/lig2.sdf")
    client = MagicMock(spec=DeepOriginClient)
    executions = MagicMock()
    client.executions = executions
    rbfe = RBFE(
        protein=protein,
        pairs=[(ligand1, ligand2)],
        client=client,
    )
    executions.create.return_value = {
        "executionId": "exec-quoted",
        "status": "Quoted",
        "approveAmount": 0,
        "tool": {
            "key": TOOL_KEYS_AND_VERSIONS["rbfe"]["tool_key"],
            "version": TOOL_KEYS_AND_VERSIONS["rbfe"]["tool_version"],
        },
        "quotationResult": {
            "successfulQuotations": [
                {"itemCode": "DO_SYSTEM_PREP", "priceTotal": 0},
                {"itemCode": "DO_RBFE", "priceTotal": 1.02792},
            ],
        },
    }
    monkeypatch.setattr(protein, "sync", MagicMock())
    monkeypatch.setattr(ligand1, "sync", MagicMock())
    monkeypatch.setattr(ligand2, "sync", MagicMock())

    rbfe.start(quote=True)

    assert rbfe.status == "Quoted"
    assert rbfe.estimate == pytest.approx(1.02792)


def test_rbfe_from_dto_rehydrates_rbfe_only_steps() -> None:
    """from_dto restores steps, prepared_systems, and FEP params."""
    fake_dto = {
        "executionId": "exec-rbfe-1",
        "status": "Running",
        "tool": {
            "key": TOOL_KEYS_AND_VERSIONS["rbfe"]["tool_key"],
            "version": "0.1.0",
        },
        "userInputs": {
            "steps": ["rbfe"],
            "prepared_systems": [
                {
                    "binding_xml_file_path": "remote/b.xml",
                    "solvation_xml_ligand_file_path": "remote/s.xml",
                    "protein_id": "prot-1",
                    "ligand1_id": "lig-1",
                    "ligand2_id": "lig-2",
                }
            ],
            "binding": {
                "annihilate": True,
                "emeq_md_options": {"T": 310.0, "cutoff": 1.0, "dt": 0.002},
                "n_windows": 12,
                "npt_reduce_restraints_ns": 1.0,
                "nvt_heating_ns": 0.5,
                "prod_md_options": {"T": 310.0, "cutoff": 1.0, "dt": 0.002},
                "repeats": 1,
                "replex_period_ps": 2.0,
                "steps": 1000,
                "test_run": 0,
            },
            "solvation": {
                "annihilate": True,
                "emeq_md_options": {"T": 310.0, "cutoff": 1.0, "dt": 0.002},
                "n_windows": 8,
                "npt_reduce_restraints_ns": 0.1,
                "nvt_heating_ns": 0.05,
                "prod_md_options": {"T": 310.0, "cutoff": 1.0, "dt": 0.002},
                "repeats": 1,
                "replex_period_ps": 2.0,
                "steps": 500,
                "test_run": 0,
            },
        },
    }
    rbfe = RBFE.from_dto(fake_dto, client=MagicMock(spec=DeepOriginClient))
    assert rbfe.id == "exec-rbfe-1"
    assert rbfe.steps == ["rbfe"]
    assert len(rbfe.prepared_systems) == 1
    assert rbfe.prepared_systems[0].ligand2_id == "lig-2"
    assert rbfe.params.binding_steps == 1000
    assert rbfe.params.temperature == pytest.approx(310.0)
    assert "steps=" in repr(rbfe)


def test_rbfe_from_dto_rehydrates_system_prep_steps() -> None:
    """from_dto restores protein, pairs, and prep flags for system-prep-only runs."""
    fake_dto = {
        "executionId": "exec-prep-1",
        "status": "Succeeded",
        "tool": {
            "key": TOOL_KEYS_AND_VERSIONS["rbfe"]["tool_key"],
            "version": "0.1.0",
        },
        "userInputs": {
            "steps": ["system-prep"],
            "protein": {"id": "prot-1", "file_path": "testing/brd.pdb"},
            "pairs": [
                {
                    "ligand1": {"id": "lig-1", "file_path": "testing/l1.sdf"},
                    "ligand2": {"id": "lig-2", "file_path": "testing/l2.sdf"},
                }
            ],
            "add_H_atoms": True,
            "retain_waters": False,
            "padding": 1.25,
        },
    }
    client = MagicMock(spec=DeepOriginClient)
    client.entities = MagicMock()
    client.entities.get_ligand.side_effect = [
        {"id": "lig-1", "smiles": "CCO", "mol_file": "testing/l1.sdf"},
        {"id": "lig-2", "smiles": "CCN", "mol_file": "testing/l2.sdf"},
    ]
    client.entities.get_protein.return_value = {
        "id": "prot-1",
        "file_path": "testing/brd.pdb",
        "name": "BRD",
    }

    rbfe = RBFE.from_dto(fake_dto, client=client)

    assert rbfe.steps == ["system-prep"]
    assert rbfe.prep_only is True
    assert rbfe.protein is not None
    assert rbfe.protein.id == "prot-1"
    assert len(rbfe.pairs) == 1
    assert rbfe.pairs[0][0].id == "lig-1"
    assert rbfe.add_h_atoms is True
    assert rbfe.retain_waters is False
    assert rbfe.padding == pytest.approx(1.25)


def test_rbfe_results_dataframe_columns() -> None:
    """Summary table exposes protein_id, ligand ids, and formatted ddG."""
    rbfe_tool_key = TOOL_KEYS_AND_VERSIONS["rbfe"]["tool_key"]
    response = {
        "data": [
            {
                "id": "0AE2XHX028S2Y",
                "tool_key": rbfe_tool_key,
                "compute_job_id": "a5484958-059f-4b1b-ba2c-664adf23e8e8",
                "data": {
                    "total": -3875.483,
                    "unit": "kcal/mol",
                    "protein_id": "08BSPN9SNYVEA",
                    "ligand1_id": "08DK80B7DYTXH",
                    "ligand2_id": "08DKACBCXYTXX",
                    "binding_analysis": [{"repeat": 1}],
                },
            },
            {
                "id": "OTHER",
                "tool_key": rbfe_tool_key,
                "compute_job_id": "job-2",
                "data": {
                    "total": 1.5,
                    "unit": "kJ/mol",
                    "protein_id": "prot-b",
                    "ligand1_id": "lig-a",
                    "ligand2_id": "lig-b",
                },
            },
        ]
    }
    df = _rbfe_results_dataframe(response, tool_key=rbfe_tool_key)
    assert df is not None
    assert list(df.columns) == ["protein_id", "ligand1_id", "ligand2_id", "ddG"]
    assert len(df) == 2
    assert df.iloc[0]["protein_id"] == "08BSPN9SNYVEA"
    assert df.iloc[0]["ddG"] == "-3875.483 kcal/mol"
    assert df.iloc[1]["ddG"] == "1.5 kJ/mol"


def test_rbfe_results_dataframe_filters_non_rbfe_tool_key() -> None:
    """System-prep and other tool results are excluded from the summary table."""
    rbfe_tool_key = TOOL_KEYS_AND_VERSIONS["rbfe"]["tool_key"]
    sysprep_tool_key = TOOL_KEYS_AND_VERSIONS["sysprep"]["tool_key"]
    response = {
        "data": [
            {
                "id": "0AF2ZRB828ZWF",
                "tool_key": sysprep_tool_key,
                "compute_job_id": "871dd154-3f25-432f-a618-9ecc96f82e58",
                "data": {
                    "protein_id": "08BSPN9SNYVEA",
                    "ligand1_id": "08DKACBCXYTXX",
                    "ligand2_id": "08CEYMV4DYV39",
                },
            },
            {
                "id": "0AE2XHX028S2Y",
                "tool_key": rbfe_tool_key,
                "compute_job_id": "a5484958-059f-4b1b-ba2c-664adf23e8e8",
                "data": {
                    "total": -3875.483,
                    "unit": "kcal/mol",
                    "protein_id": "08BSPN9SNYVEA",
                    "ligand1_id": "08DK80B7DYTXH",
                    "ligand2_id": "08DKACBCXYTXX",
                },
            },
        ]
    }
    df = _rbfe_results_dataframe(response, tool_key=rbfe_tool_key)
    assert df is not None
    assert len(df) == 1
    assert df.iloc[0]["protein_id"] == "08BSPN9SNYVEA"
    assert df.iloc[0]["ddG"] == "-3875.483 kcal/mol"


def test_rbfe_get_results_returns_dataframe(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_results syncs and returns the summary DataFrame."""
    rbfe = RBFE(
        prepared_systems=[
            PreparedSystem(
                binding_xml_path="b.xml",
                solvation_xml_path="s.xml",
                system_pdb_path="p.pdb",
            )
        ],
        client=MagicMock(spec=DeepOriginClient),
    )
    rbfe._id = "exec-top"
    platform_response = {
        "data": [
            {
                "tool_key": TOOL_KEYS_AND_VERSIONS["rbfe"]["tool_key"],
                "compute_job_id": "sub-job",
                "data": {
                    "total": -1.0,
                    "unit": "kcal/mol",
                    "protein_id": "prot-1",
                    "ligand1_id": "l1",
                    "ligand2_id": "l2",
                },
            }
        ]
    }
    monkeypatch.setattr(rbfe, "sync", MagicMock())
    monkeypatch.setattr(
        Execution,
        "get_results",
        lambda self, **kwargs: platform_response,
    )
    out = rbfe.get_results()
    assert isinstance(out, pd.DataFrame)
    assert out.iloc[0]["ddG"] == "-1.0 kcal/mol"
    rbfe.sync.assert_called_once()


def test_rbfe_repr_shows_id_and_status_when_set() -> None:
    """__repr__ includes platform execution id and status when available."""
    protein = Protein(name="p", id="prot-1", remote_path="testing/brd.pdb")
    ligand1 = Ligand.from_smiles("CCO", id="lig-1", remote_path="testing/lig1.sdf")
    ligand2 = Ligand.from_smiles("CCN", id="lig-2", remote_path="testing/lig2.sdf")
    rbfe = RBFE(protein=protein, pairs=[(ligand1, ligand2)], prep_only=True)
    assert "id=" not in repr(rbfe)
    assert "status=" not in repr(rbfe)

    rbfe._id = "exec-abc"
    text = repr(rbfe)
    assert "  id='exec-abc'," in text
    assert "status=" not in text

    rbfe.status = "Running"
    text = repr(rbfe)
    assert "  status='Running'," in text
