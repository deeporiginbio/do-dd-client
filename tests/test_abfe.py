"""tests for abfe"""

from unittest.mock import MagicMock, patch

import pytest

from deeporigin.drug_discovery.abfe import (
    ABFE,
    ABFEParams,
    _abfe_default_name,
    _ligand_display_label_from_entity,
    _protein_display_name_from_entity,
)
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS


def test_abfe_quote_cannot_be_called_twice_lv0(client: DeepOriginClient):
    """quote() raises ValueError if called after a quotation already exists."""
    prepared_system = PreparedSystem(
        binding_xml_path="path/binding.xml",
        solvation_xml_path="path/solvation.xml",
        system_pdb_path="path/system.pdb",
    )
    abfe = ABFE(prepared_system=prepared_system)

    # Simulate a completed quote by setting state directly
    abfe._id = "exec-quoted-123"
    abfe.status = "Quoted"

    with pytest.raises(ValueError, match="quotation already exists"):
        abfe.quote()


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
        "metadata": {},
    }

    mock_client = MagicMock()

    abfe = ABFE.from_dto(fake_dto, client=mock_client)

    assert abfe.id == "exec-123"
    assert abfe.status == "Succeeded"

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

    assert "prot-abc" in repr(abfe)
    assert "lig-xyz" in repr(abfe)


def test_abfe_from_dto_legacy_metadata_ligand_id_lv0(client: DeepOriginClient):
    """from_dto falls back to metadata.ligand_id when prepared_system omits ligand1_id."""
    fake_dto = {
        "executionId": "exec-legacy",
        "status": "Succeeded",
        "tool": {
            "key": TOOL_KEYS_AND_VERSIONS["abfe"]["tool_key"],
            "version": "0.1.0",
        },
        "quotationResult": {"successfulQuotations": [{"priceTotal": 1.0}]},
        "userInputs": {
            "prepared_system": {
                "binding_xml_file_path": "remote/b.xml",
                "solvation_xml_ligand_file_path": "remote/s.xml",
            },
            "binding": {
                "annihilate": True,
                "emeq_md_options": {"T": 300.0, "cutoff": 1.0, "dt": 0.002},
                "n_windows": 8,
                "npt_reduce_restraints_ns": 1.0,
                "nvt_heating_ns": 0.5,
                "prod_md_options": {"T": 300.0, "cutoff": 1.0, "dt": 0.002},
                "repeats": 1,
                "replex_period_ps": 2.0,
                "steps": 100,
                "test_run": 1,
            },
            "solvation": {
                "annihilate": True,
                "emeq_md_options": {"T": 300.0, "cutoff": 1.0, "dt": 0.002},
                "n_windows": 8,
                "npt_reduce_restraints_ns": 0.1,
                "nvt_heating_ns": 0.05,
                "prod_md_options": {"T": 300.0, "cutoff": 1.0, "dt": 0.002},
                "repeats": 1,
                "replex_period_ps": 2.0,
                "steps": 50,
                "test_run": 1,
            },
        },
        "metadata": {"protein_id": "p-old", "ligand_id": "l-old"},
    }
    abfe = ABFE.from_dto(fake_dto, client=MagicMock())
    assert abfe.prepared_system.protein_id == "p-old"
    assert abfe.prepared_system.ligand1_id == "l-old"


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
    original.status = "Succeeded"
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
    """_abfe_default_name should load entities and format ABFE: protein with ligand."""
    get_protein = MagicMock(
        return_value={
            "protein_name": "Protein X",
            "pdb_id": "1abc",
        }
    )
    get_ligand = MagicMock(
        return_value={
            "name": "Ligand Y",
            "smiles": "CCO",
        }
    )
    prepared_system = PreparedSystem(
        binding_xml_path="path/binding.xml",
        solvation_xml_path="path/solvation.xml",
        system_pdb_path="path/system.pdb",
        protein_id="prot-123",
        ligand1_id="lig-456",
    )
    with (
        patch.object(client.entities, "get_protein", get_protein),
        patch.object(client.entities, "get_ligand", get_ligand),
    ):
        assert (
            _abfe_default_name(prepared_system=prepared_system, client=client)
            == "ABFE: Protein X with Ligand Y"
        )
    get_protein.assert_called_once_with(id="prot-123")
    get_ligand.assert_called_once_with(id="lig-456")


def test_abfe_default_name_ligand_smiles_when_no_name_lv0(client: DeepOriginClient):
    """Ligand label uses canonical_smiles or smiles when name is absent."""
    prepared_system = PreparedSystem(
        binding_xml_path="b.xml",
        solvation_xml_path="s.xml",
        system_pdb_path="p.pdb",
        protein_id="p1",
        ligand1_id="l1",
    )
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
            _abfe_default_name(prepared_system=prepared_system, client=client)
            == "ABFE: 1ABC with CCO"
        )


def test_abfe_default_name_unknown_ids_lv0(client: DeepOriginClient):
    """Missing IDs use unknown labels and do not call the entities API."""
    get_protein = MagicMock()
    get_ligand = MagicMock()
    no_ids = PreparedSystem(
        binding_xml_path="path/binding.xml",
        solvation_xml_path="path/solvation.xml",
        system_pdb_path="path/system.pdb",
        protein_id=None,
        ligand1_id=None,
    )
    with (
        patch.object(client.entities, "get_protein", get_protein),
        patch.object(client.entities, "get_ligand", get_ligand),
    ):
        assert (
            _abfe_default_name(prepared_system=no_ids, client=client)
            == "ABFE: unknown protein with unknown ligand"
        )
    get_protein.assert_not_called()
    get_ligand.assert_not_called()


def test_abfe_default_name_api_error_falls_back_to_id_lv0(client: DeepOriginClient):
    """When get_protein fails, fall back to the protein entity ID string."""
    get_protein = MagicMock(side_effect=OSError("unavailable"))
    get_ligand = MagicMock(return_value={"name": "Named"})
    ps = PreparedSystem(
        binding_xml_path="b.xml",
        solvation_xml_path="s.xml",
        system_pdb_path="p.pdb",
        protein_id="prot-123",
        ligand1_id="lig-456",
    )
    with (
        patch.object(client.entities, "get_protein", get_protein),
        patch.object(client.entities, "get_ligand", get_ligand),
    ):
        assert (
            _abfe_default_name(prepared_system=ps, client=client)
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


def test_abfe_sets_default_name_on_construction_lv0(client: DeepOriginClient):
    """ABFE should set a generated name when name is not provided."""
    prepared_system = PreparedSystem(
        binding_xml_path="path/binding.xml",
        solvation_xml_path="path/solvation.xml",
        system_pdb_path="path/system.pdb",
        protein_id="prot-1",
        ligand1_id="lig-1",
    )
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
        abfe = ABFE(prepared_system=prepared_system, client=client)
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
