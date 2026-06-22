"""Unit tests for :mod:`deeporigin.drug_discovery.rbfe`."""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.rbfe import (
    RBFE,
    RBFEParams,
    _ligand_from_pair_input,
    _rbfe_results_dataframe,
)
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS


def test_ligand_from_pair_input_uses_remote_file_without_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """File-only pair refs rehydrate via Ligand.from_remote_file."""
    client = MagicMock(spec=DeepOriginClient)
    expected = Ligand.from_smiles("CCO", remote_path="testing/lig1.sdf")
    from_remote = MagicMock(return_value=expected)
    monkeypatch.setattr(Ligand, "from_remote_file", from_remote)

    ligand = _ligand_from_pair_input({"file_path": "testing/lig1.sdf"}, client=client)

    from_remote.assert_called_once_with("testing/lig1.sdf", client=client, lazy=True)
    assert ligand is expected


def test_rbfe_ligands_build_params() -> None:
    """Konnektor steps build ligands[], network_type, and prep flags."""
    protein = Protein(name="p", id="prot-1", remote_path="testing/brd.pdb")
    ligand1 = Ligand.from_smiles("CCO", id="lig-1", remote_path="testing/lig1.sdf")
    ligand2 = Ligand.from_smiles("CCN", id="lig-2", remote_path="testing/lig2.sdf")
    ligand3 = Ligand.from_smiles("CCC", id="lig-3", remote_path="testing/lig3.sdf")
    rbfe = RBFE(
        protein=protein,
        ligands=[ligand1, ligand2, ligand3],
        network_type="star",
        retain_waters=False,
        padding=1.5,
    )
    params = rbfe._build_params()
    assert params["steps"] == ["konnektor", "system-prep", "rbfe"]
    assert params["protein"]["file_path"] == "testing/brd.pdb"
    assert len(params["ligands"]) == 3
    assert params["ligands"][0]["id"] == "lig-1"
    assert params["ligands"][0]["file_path"] == "testing/lig1.sdf"
    assert params["network_type"] == "star"
    assert "pairs" not in params
    assert params["padding"] == pytest.approx(1.5)
    assert "binding" in params


def test_rbfe_ligands_cycle_closure_build_params() -> None:
    """Anchor inputs append cycle-closure and serialize fep_abfe."""
    protein = Protein(name="p", id="prot-1", remote_path="testing/brd.pdb")
    ligand1 = Ligand.from_smiles("CCO", id="lig-1", remote_path="testing/lig1.sdf")
    ligand2 = Ligand.from_smiles("CCN", id="lig-2", remote_path="testing/lig2.sdf")
    ligand3 = Ligand.from_smiles("CCC", id="lig-3", remote_path="testing/lig3.sdf")
    rbfe = RBFE(
        protein=protein,
        ligands=[ligand1, ligand2, ligand3],
        fep_abfe=[{"ligand_id": "lig-1", "dG": -10.0}],
    )
    params = rbfe._build_params()
    assert params["steps"] == [
        "konnektor",
        "system-prep",
        "rbfe",
        "cycle-closure",
    ]
    assert params["fep_abfe"] == [{"ligand_id": "lig-1", "dG": -10.0}]


def test_rbfe_cycle_closure_requires_anchor() -> None:
    """cycle-closure without anchors is rejected at construction."""
    protein = Protein(name="p", id="prot-1", remote_path="testing/brd.pdb")
    ligand1 = Ligand.from_smiles("CCO", id="lig-1", remote_path="testing/lig1.sdf")
    ligand2 = Ligand.from_smiles("CCN", id="lig-2", remote_path="testing/lig2.sdf")
    rbfe = RBFE(protein=protein, ligands=[ligand1, ligand2])
    rbfe.steps = ["konnektor", "system-prep", "rbfe", "cycle-closure"]
    with pytest.raises(ValueError, match="exp_abfe or fep_abfe is required"):
        rbfe._validate_step_inputs()


def test_rbfe_rbfe_steps_require_prepared_systems() -> None:
    """RBFE-only steps reject when no input mode is provided."""
    with pytest.raises(
        ValueError, match="Exactly one of ligands, pairs, or prepared_systems"
    ):
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
    assert call_kwargs["data"]["inputs"]["steps"] == ["system-prep", "rbfe"]


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
    assert rbfe.prepared_systems[0].system_pdb_path == ""
    assert rbfe.params.binding_steps == 1000
    assert rbfe.params.temperature == pytest.approx(310.0)
    assert "steps=" in repr(rbfe)


def test_rbfe_from_dto_populates_prepared_system_paths() -> None:
    """from_dto restores system and solute PDB paths from prepared_systems[]."""
    fake_dto = {
        "executionId": "exec-rbfe-2",
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
                    "system_pdb_file_path": "remote/system.pdb",
                    "solute_pdb_file_path": "remote/solute.pdb",
                    "protein_id": "prot-1",
                    "ligand1_id": "lig-1",
                    "ligand2_id": "lig-2",
                },
                "ignored-non-dict",
            ],
            "binding": {"steps": 100, "test_run": 0},
            "solvation": {"steps": 50, "test_run": 0},
        },
    }
    rbfe = RBFE.from_dto(fake_dto, client=MagicMock(spec=DeepOriginClient))
    assert len(rbfe.prepared_systems) == 1
    ps = rbfe.prepared_systems[0]
    assert ps.system_pdb_path == "remote/system.pdb"
    assert ps.solute_pdb_path == "remote/solute.pdb"


def test_rbfe_ensure_synced_inputs_skips_sync_when_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """start() skips sync when id and remote_path are already set."""
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
        "executionId": "exec-123",
        "status": "Created",
        "tool": {"key": "deeporigin.rbfe", "version": "0.1.0"},
    }
    protein_sync = MagicMock()
    ligand1_sync = MagicMock()
    ligand2_sync = MagicMock()
    monkeypatch.setattr(protein, "sync", protein_sync)
    monkeypatch.setattr(ligand1, "sync", ligand1_sync)
    monkeypatch.setattr(ligand2, "sync", ligand2_sync)
    monkeypatch.setattr(
        protein,
        "ensure_remote_path",
        MagicMock(side_effect=lambda **_: None),
    )
    monkeypatch.setattr(
        ligand1,
        "ensure_remote_path",
        MagicMock(side_effect=lambda **_: None),
    )
    monkeypatch.setattr(
        ligand2,
        "ensure_remote_path",
        MagicMock(side_effect=lambda **_: None),
    )

    rbfe.start()

    protein_sync.assert_not_called()
    ligand1_sync.assert_not_called()
    ligand2_sync.assert_not_called()


def test_rbfe_from_dto_rejects_legacy_system_prep_only_steps() -> None:
    """from_dto rejects legacy steps=['system-prep'] executions."""
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

    with pytest.raises(ValueError, match="Legacy steps=\\['system-prep'\\]"):
        RBFE.from_dto(fake_dto, client=client)


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


def _sample_prepared_system(
    *, ligand1_id: str = "l1", ligand2_id: str = "l2"
) -> PreparedSystem:
    """Return a minimal PreparedSystem for RBFE get_prepared_system tests."""
    return PreparedSystem(
        binding_xml_path="b.xml",
        solvation_xml_path="s.xml",
        system_pdb_path="p.pdb",
        ligand1_id=ligand1_id,
        ligand2_id=ligand2_id,
    )


def test_rbfe_get_prepared_system_returns_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_prepared_system syncs and returns the first matching PreparedSystem."""
    rbfe = RBFE(
        prepared_systems=[_sample_prepared_system()],
        client=MagicMock(spec=DeepOriginClient),
    )
    rbfe._id = "exec-top"
    first = _sample_prepared_system(ligand1_id="first-l1", ligand2_id="first-l2")
    second = _sample_prepared_system(ligand1_id="second-l1", ligand2_id="second-l2")
    from_result = MagicMock(return_value=[first, second])
    monkeypatch.setattr(PreparedSystem, "from_result", from_result)
    monkeypatch.setattr(rbfe, "sync", MagicMock())

    out = rbfe.get_prepared_system()

    assert out is first
    rbfe.sync.assert_called_once()
    from_result.assert_called_once_with(
        compute_job_id="exec-top",
        ligand1_id=None,
        ligand2_id=None,
        client=rbfe.client,
    )


def test_rbfe_get_prepared_system_passes_ligand_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_prepared_system forwards ligand1_id and ligand2_id to from_result."""
    rbfe = RBFE(
        prepared_systems=[_sample_prepared_system()],
        client=MagicMock(spec=DeepOriginClient),
    )
    rbfe._id = "exec-top"
    system = _sample_prepared_system()
    from_result = MagicMock(return_value=[system])
    monkeypatch.setattr(PreparedSystem, "from_result", from_result)
    monkeypatch.setattr(rbfe, "sync", MagicMock())

    out = rbfe.get_prepared_system(ligand1_id="lig-a", ligand2_id="lig-b")

    assert out is system
    from_result.assert_called_once_with(
        compute_job_id="exec-top",
        ligand1_id="lig-a",
        ligand2_id="lig-b",
        client=rbfe.client,
    )


def test_rbfe_get_prepared_system_raises_without_id() -> None:
    """get_prepared_system requires a platform execution id."""
    rbfe = RBFE(prepared_systems=[_sample_prepared_system()])
    with pytest.raises(ValueError, match="no execution has been started"):
        rbfe.get_prepared_system()


def test_rbfe_get_prepared_system_raises_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_prepared_system raises DeepOriginException when no rows match."""
    rbfe = RBFE(
        prepared_systems=[_sample_prepared_system()],
        client=MagicMock(spec=DeepOriginClient),
    )
    rbfe._id = "exec-top"
    monkeypatch.setattr(rbfe, "sync", MagicMock())

    monkeypatch.setattr(PreparedSystem, "from_result", MagicMock(return_value=[]))
    with pytest.raises(DeepOriginException, match="No system-prep results found"):
        rbfe.get_prepared_system()

    monkeypatch.setattr(
        PreparedSystem,
        "from_result",
        MagicMock(side_effect=ValueError("no rows")),
    )
    with pytest.raises(DeepOriginException, match="No system-prep results found"):
        rbfe.get_prepared_system()


def test_rbfe_repr_shows_id_and_status_when_set() -> None:
    """__repr__ includes platform execution id and status when available."""
    protein = Protein(name="p", id="prot-1", remote_path="testing/brd.pdb")
    ligand1 = Ligand.from_smiles("CCO", id="lig-1", remote_path="testing/lig1.sdf")
    ligand2 = Ligand.from_smiles("CCN", id="lig-2", remote_path="testing/lig2.sdf")
    rbfe = RBFE(protein=protein, pairs=[(ligand1, ligand2)])
    assert "id=" not in repr(rbfe)
    assert "status=" not in repr(rbfe)

    rbfe._id = "exec-abc"
    text = repr(rbfe)
    assert "  id='exec-abc'," in text
    assert "status=" not in text

    rbfe.status = "Running"
    text = repr(rbfe)
    assert "  status='Running'," in text
