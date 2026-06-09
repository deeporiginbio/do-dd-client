"""tests for abfe"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from deeporigin.drug_discovery.abfe import (
    ABFE,
    _abfe_default_name_from_entities,
    _ligand_display_label_from_entity,
    _protein_display_name_from_entity,
)
from deeporigin.drug_discovery.fep_common import ABFEParams
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS


def test_abfe_start_quote_populates_estimate_lv0(client: DeepOriginClient):
    """start(quote=True) should set estimate from quotationResult.priceTotal."""
    prepared_system = PreparedSystem(
        binding_xml_path="path/binding.xml",
        solvation_xml_path="path/solvation.xml",
        system_pdb_path="path/system.pdb",
    )
    abfe = ABFE(prepared_system=prepared_system, name="Test ABFE", client=client)
    quoted_dto = {
        "executionId": "exec-quoted",
        "status": "Quoted",
        "approveAmount": 0,
        "tool": {
            "key": TOOL_KEYS_AND_VERSIONS["abfe"]["tool_key"],
            "version": TOOL_KEYS_AND_VERSIONS["abfe"]["tool_version"],
        },
        "quotationResult": {
            "successfulQuotations": [{"priceTotal": 119.2128}],
        },
    }
    with patch.object(client.executions, "create", return_value=quoted_dto):
        abfe.start(quote=True)

    assert abfe.id == "exec-quoted"
    assert abfe.status == "Quoted"
    assert abfe.estimate == pytest.approx(119.2128)
    assert abfe.cost is None


def test_abfe_start_rejects_non_none_status_lv0(client: DeepOriginClient):
    """start() raises ValueError when the execution is already in a non-None state."""
    prepared_system = PreparedSystem(
        binding_xml_path="path/binding.xml",
        solvation_xml_path="path/solvation.xml",
        system_pdb_path="path/system.pdb",
    )
    abfe = ABFE(prepared_system=prepared_system)

    abfe._id = "exec-quoted-123"
    abfe.status = "Quoted"

    with pytest.raises(ValueError, match="'Quoted'"):
        abfe.start()


def test_abfe_combined_build_params() -> None:
    """protein + ligand selects system-prep + ABFE steps and prep flags."""
    protein = Protein(name="p", id="prot-1", remote_path="testing/brd.pdb")
    ligand = Ligand.from_smiles("CCO", id="lig-1", remote_path="testing/lig1.sdf")
    abfe = ABFE(
        protein=protein,
        ligand=ligand,
        retain_waters=False,
        padding=1.5,
        params=ABFEParams(test_run=1),
    )
    params = abfe._build_params()
    assert params["steps"] == ["system-prep", "abfe"]
    assert params["protein"]["file_path"] == "testing/brd.pdb"
    assert params["ligand1"]["id"] == "lig-1"
    assert params["ligand1"]["file_path"] == "testing/lig1.sdf"
    assert params["padding"] == pytest.approx(1.5)
    assert params["binding"]["test_run"] == 1


def test_abfe_abfe_only_build_params() -> None:
    """ABFE-only steps serialize prepared_system and FEP blocks."""
    ps = PreparedSystem(
        binding_xml_path="testing/a.xml",
        solvation_xml_path="testing/b.xml",
        system_pdb_path="testing/c.pdb",
        protein_id="prot-1",
        ligand1_id="lig-1",
    )
    abfe = ABFE(prepared_system=ps, params=ABFEParams(test_run=1))
    params = abfe._build_params()
    assert params["steps"] == ["abfe"]
    assert params["prepared_system"]["ligand1_id"] == "lig-1"
    assert params["binding"]["test_run"] == 1
    assert "protein" not in params


def test_abfe_mutually_exclusive_inputs() -> None:
    """Reject when neither or both input modes are provided."""
    ps = PreparedSystem(
        binding_xml_path="a.xml",
        solvation_xml_path="b.xml",
        system_pdb_path="c.pdb",
    )
    protein = Protein(name="p", id="prot-1", remote_path="testing/brd.pdb")
    ligand = Ligand.from_smiles("CCO", id="lig-1", remote_path="testing/lig1.sdf")

    with pytest.raises(ValueError, match="Exactly one of"):
        ABFE()

    with pytest.raises(ValueError, match="Exactly one of"):
        ABFE(prepared_system=ps, protein=protein, ligand=ligand)


def test_abfe_ligand_ligand1_mutual_exclusion() -> None:
    """ligand and ligand1 cannot both be provided."""
    protein = Protein(name="p", id="prot-1", remote_path="testing/brd.pdb")
    ligand = Ligand.from_smiles("CCO", id="lig-1", remote_path="testing/lig1.sdf")
    with pytest.raises(ValueError, match="only one of ligand or ligand1"):
        ABFE(protein=protein, ligand=ligand, ligand1=ligand)


def test_abfe_ensure_synced_inputs_ensures_remote_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """start() ensures remote_path after lazy sync."""
    protein = Protein(name="p", id="prot-1", remote_path=None)
    ligand = Ligand.from_smiles("CCO", id="lig-1", remote_path=None)
    client = MagicMock(spec=DeepOriginClient)
    executions = MagicMock()
    client.executions = executions
    abfe = ABFE(protein=protein, ligand=ligand, client=client)
    executions.create.return_value = {
        "executionId": "exec-123",
        "status": "Created",
        "tool": {"key": "deeporigin.abfe", "version": "0.1.0"},
    }
    protein.ensure_remote_path = MagicMock(
        side_effect=lambda **_: setattr(protein, "remote_path", "testing/brd.pdb")
    )
    ligand.ensure_remote_path = MagicMock(
        side_effect=lambda **_: setattr(ligand, "remote_path", "testing/lig1.sdf")
    )
    monkeypatch.setattr(protein, "sync", MagicMock())
    monkeypatch.setattr(ligand, "sync", MagicMock())

    abfe.start()

    protein.ensure_remote_path.assert_called_once()
    ligand.ensure_remote_path.assert_called_once()
    call_kwargs = executions.create.call_args.kwargs
    assert call_kwargs["data"]["inputs"]["protein"]["file_path"] == "testing/brd.pdb"


def test_abfe_from_dto_requires_steps() -> None:
    """from_dto rejects legacy payloads without steps."""
    fake_dto = {
        "executionId": "exec-legacy",
        "status": "Succeeded",
        "tool": {"key": "deeporigin.abfe", "version": "0.1.0"},
        "userInputs": {
            "prepared_system": {
                "binding_xml_file_path": "remote/b.xml",
                "solvation_xml_ligand_file_path": "remote/s.xml",
            },
        },
    }
    with pytest.raises(ValueError, match="Missing 'steps'"):
        ABFE.from_dto(fake_dto, client=MagicMock())


def test_abfe_from_dto_rejects_system_prep_only_steps() -> None:
    """from_dto rejects legacy steps=['system-prep'] executions."""
    fake_dto = {
        "executionId": "exec-prep",
        "status": "Succeeded",
        "tool": {"key": "deeporigin.abfe", "version": "0.1.0"},
        "userInputs": {
            "steps": ["system-prep"],
            "protein": {"id": "prot-1", "file_path": "testing/brd.pdb"},
            "ligand1": {"id": "lig-1", "file_path": "testing/lig1.sdf"},
        },
    }
    with pytest.raises(ValueError, match="Legacy steps=\\['system-prep'\\]"):
        ABFE.from_dto(fake_dto, client=MagicMock())


def test_abfe_from_dto_rehydrates_prepared_system_lv0(client: DeepOriginClient):
    """from_dto should rehydrate prepared_system and params from the DTO."""
    fake_dto = {
        "executionId": "exec-123",
        "status": "Succeeded",
        "tool": {
            "key": TOOL_KEYS_AND_VERSIONS["abfe"]["tool_key"],
            "version": "0.1.0",
        },
        "quotationResult": {
            "successfulQuotations": [{"priceTotal": 42.0}],
        },
        "userInputs": {
            "steps": ["abfe"],
            "prepared_system": {
                "binding_xml_file_path": "remote/binding.xml",
                "solvation_xml_ligand_file_path": "remote/solvation.xml",
                "protein_id": "prot-abc",
                "ligand1_id": "lig-xyz",
            },
            "binding": {
                "annihilate": True,
                "emeq_md_options": {"T": 300.0, "cutoff": 1.0, "dt": 0.002},
                "n_windows": 24,
                "npt_reduce_restraints_ns": 1.0,
                "nvt_heating_ns": 0.5,
                "prod_md_options": {"T": 300.0, "cutoff": 1.0, "dt": 0.002},
                "repeats": 2,
                "replex_period_ps": 5.0,
                "steps": 100000,
                "test_run": 1,
            },
            "solvation": {
                "annihilate": False,
                "emeq_md_options": {"T": 300.0, "cutoff": 1.0, "dt": 0.002},
                "n_windows": 16,
                "npt_reduce_restraints_ns": 0.1,
                "nvt_heating_ns": 0.05,
                "prod_md_options": {"T": 300.0, "cutoff": 1.0, "dt": 0.002},
                "repeats": 2,
                "replex_period_ps": 5.0,
                "steps": 50000,
                "test_run": 1,
            },
        },
    }

    mock_client = MagicMock()

    abfe = ABFE.from_dto(fake_dto, client=mock_client)

    assert abfe.id == "exec-123"
    assert abfe.status == "Completed"
    assert abfe.estimate == pytest.approx(42.0)
    assert abfe.steps == ["abfe"]

    ps = abfe.prepared_system
    assert isinstance(ps, PreparedSystem)
    assert ps.binding_xml_path == "remote/binding.xml"
    assert ps.solvation_xml_path == "remote/solvation.xml"
    assert ps.protein_id == "prot-abc"
    assert ps.ligand1_id == "lig-xyz"

    params = abfe.params
    assert isinstance(params, ABFEParams)
    assert params.dt == pytest.approx(0.002)
    assert params.temperature == pytest.approx(300.0)
    assert params.cutoff == pytest.approx(1.0)
    assert params.repeats == 2
    assert params.binding_n_windows == 24
    assert params.solvation_n_windows == 16
    assert params.binding_steps == 100000
    assert params.solvation_steps == 50000

    assert "abfe" in repr(abfe)


def test_abfe_from_id_repr_without_prepared_system_lv0(client: DeepOriginClient):
    """repr should not crash when prepared_system is missing."""
    ps = PreparedSystem(
        binding_xml_path="b.xml",
        solvation_xml_path="s.xml",
        system_pdb_path="p.pdb",
    )
    abfe = ABFE(prepared_system=ps)
    del abfe.prepared_system
    result = repr(abfe)
    assert "ABFE" in result


def test_abfe_duplicate_lv0(client: DeepOriginClient):
    """duplicate() produces a fresh instance with same config but no execution state."""
    ps = PreparedSystem(
        binding_xml_path="path/binding.xml",
        solvation_xml_path="path/solvation.xml",
        system_pdb_path="path/system.pdb",
        protein_id="prot-1",
        ligand1_id="lig-1",
    )
    params = ABFEParams(dt=0.002, binding_n_windows=24)
    original = ABFE(prepared_system=ps, params=params, tool_version="0.2.0")
    original._id = "exec-old"
    original.status = "Completed"
    original._estimate = 10.0
    original._cost = 9.5

    dup = original.duplicate()

    assert dup.id is None
    assert not hasattr(dup, "status") or getattr(dup, "status", None) is None
    assert dup.estimate is None
    assert dup.cost is None

    assert dup.prepared_system is ps
    assert dup.params is params
    assert dup.tool_version == "0.2.0"


def test_abfe_default_name_helper_resolves_entities_lv0(client: DeepOriginClient):
    """_abfe_default_name_from_entities loads entities and formats the label."""
    protein = Protein(name="fallback", id="prot-123", remote_path="testing/p.pdb")
    ligand = Ligand.from_smiles("CCO", id="lig-456", remote_path="testing/l.sdf")
    with (
        patch.object(
            client.entities,
            "get_protein",
            return_value={"protein_name": "Protein X", "pdb_id": "1abc"},
        ),
        patch.object(
            client.entities,
            "get_ligand",
            return_value={"name": "Ligand Y", "smiles": "CCO"},
        ),
    ):
        assert (
            _abfe_default_name_from_entities(
                protein=protein,
                ligand=ligand,
                client=client,
            )
            == "ABFE: Protein X with Ligand Y"
        )


def test_abfe_default_name_ligand_smiles_when_no_name_lv0(client: DeepOriginClient):
    """Ligand label uses canonical_smiles or smiles when name is absent."""
    protein = Protein(name="p", id="p1", remote_path="testing/p.pdb")
    ligand = Ligand.from_smiles("CCO", id="l1", remote_path="testing/l.sdf")
    with (
        patch.object(
            client.entities,
            "get_protein",
            return_value={"pdb_id": "1ABC"},
        ),
        patch.object(
            client.entities,
            "get_ligand",
            return_value={"canonical_smiles": "CCO"},
        ),
    ):
        assert (
            _abfe_default_name_from_entities(
                protein=protein,
                ligand=ligand,
                client=client,
            )
            == "ABFE: 1ABC with CCO"
        )


def test_abfe_default_name_unknown_ids_lv0(client: DeepOriginClient):
    """Missing IDs use fallback labels and do not call the entities API."""
    protein = Protein(name="MyProt", id=None, remote_path="testing/p.pdb")
    ligand = Ligand.from_smiles("CCO", id=None, remote_path="testing/l.sdf")
    get_protein = MagicMock()
    get_ligand = MagicMock()
    with (
        patch.object(client.entities, "get_protein", get_protein),
        patch.object(client.entities, "get_ligand", get_ligand),
    ):
        assert (
            _abfe_default_name_from_entities(
                protein=protein,
                ligand=ligand,
                client=client,
            )
            == "ABFE: MyProt with unknown ligand"
        )
    get_protein.assert_not_called()
    get_ligand.assert_not_called()


def test_abfe_default_name_api_error_falls_back_to_id_lv0(client: DeepOriginClient):
    """When get_protein fails, fall back to the protein entity ID string."""
    protein = Protein(name="p", id="prot-123", remote_path="testing/p.pdb")
    ligand = Ligand.from_smiles("CCO", id="lig-456", remote_path="testing/l.sdf")
    with (
        patch.object(
            client.entities, "get_protein", side_effect=OSError("unavailable")
        ),
        patch.object(client.entities, "get_ligand", return_value={"name": "Named"}),
    ):
        assert (
            _abfe_default_name_from_entities(
                protein=protein,
                ligand=ligand,
                client=client,
            )
            == "ABFE: prot-123 with Named"
        )


def test_entity_label_helpers_lv0():
    """Entity helpers match platform field precedence."""
    assert (
        _protein_display_name_from_entity(
            entity={"gene_symbol": "GENE", "pdb_id": "1x"},
            fallback_id="fid",
        )
        == "1x"
    )
    assert (
        _ligand_display_label_from_entity(
            entity={"name": "", "smiles": "N"},
            fallback_id="lid",
        )
        == "N"
    )


def test_abfe_prepared_system_does_not_auto_name(client: DeepOriginClient):
    """prepared_system-only mode leaves name unset unless provided."""
    prepared_system = PreparedSystem(
        binding_xml_path="path/binding.xml",
        solvation_xml_path="path/solvation.xml",
        system_pdb_path="path/system.pdb",
        protein_id="prot-1",
        ligand1_id="lig-1",
    )
    abfe = ABFE(prepared_system=prepared_system, client=client)
    assert abfe.name is None


def test_abfe_combined_auto_names(client: DeepOriginClient):
    """Combined mode auto-generates a name from protein and ligand entities."""
    protein = Protein(name="p", id="prot-1", remote_path="testing/brd.pdb")
    ligand = Ligand.from_smiles("CCO", id="lig-1", remote_path="testing/lig1.sdf")
    with (
        patch.object(
            client.entities,
            "get_protein",
            return_value={"protein_name": "MyProt"},
        ),
        patch.object(
            client.entities,
            "get_ligand",
            return_value={"name": "MyLig"},
        ),
    ):
        abfe = ABFE(protein=protein, ligand=ligand, client=client)
        assert abfe.name == "ABFE: MyProt with MyLig"


def test_abfe_accepts_explicit_name_override_lv0():
    """ABFE should respect an explicit name override."""
    prepared_system = PreparedSystem(
        binding_xml_path="path/binding.xml",
        solvation_xml_path="path/solvation.xml",
        system_pdb_path="path/system.pdb",
        protein_id="prot-1",
        ligand1_id="lig-1",
    )
    abfe = ABFE(prepared_system=prepared_system, name="Custom ABFE label")
    assert abfe.name == "Custom ABFE label"
