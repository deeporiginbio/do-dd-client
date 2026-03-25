"""tests for abfe"""

from unittest.mock import MagicMock

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, Complex, Ligand, Protein
from deeporigin.drug_discovery.abfe import ABFE, ABFEParams
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.exceptions import DeepOriginException


def test_abfe_charged_ligand_lv0():
    """test that abfe raises an error if a charged ligand is provided"""

    ligand = Ligand.from_smiles("C[N+]1=CCCC1")
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    sim = Complex(protein=protein, ligands=ligand)

    with pytest.raises(
        DeepOriginException,
        match="ABFE does not currently support charged ligands",
    ):
        sim.abfe.run()


def test_abfe_prepared_system_lv0():
    """test that abfe raises an error if a prepared system is not provided"""
    ligand = Ligand.from_smiles("CCO")
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    sim = Complex(protein=protein, ligands=ligand)
    with pytest.raises(DeepOriginException, match="is not prepared"):
        sim.abfe.run()


def test_check_dt_defaults_valid_lv0():
    """default parameters should have in-range dt everywhere"""

    ligand = Ligand.from_smiles("CCO")
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    sim = Complex(protein=protein, ligands=ligand)

    # Should not raise
    sim.abfe.check_dt()


def test_check_dt_raises_on_out_of_range_lv0():
    """setting any nested dt out of range should raise an error"""

    ligand = Ligand.from_smiles("CCO")
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    sim = Complex(protein=protein, ligands=ligand)

    # Deliberately set an out-of-range dt deep inside the params
    sim.abfe._params["end_to_end"]["binding"]["prod_md_options"]["dt"] = 0.01

    with pytest.raises(
        DeepOriginException,
        match=r"Found invalid dt values; must be numeric and within range \[0.001, 0.004\]",
    ):
        sim.abfe.check_dt()


def test_abfe_quote_cannot_be_called_twice_lv0():
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


def test_abfe_from_id_rehydrates_prepared_system_lv0():
    """from_id should rehydrate prepared_system and params from the DTO."""
    fake_dto = {
        "executionId": "exec-123",
        "status": "Succeeded",
        "tool": {"key": "abfe-e2e", "version": "0.1.0"},
        "quotationResult": {
            "successfulQuotations": [{"priceTotal": 42.0}],
        },
        "userInputs": {
            "prepared_system": {
                "binding_xml_file_path": "remote/binding.xml",
                "solvation_xml_ligand1_file_path": "remote/solvation.xml",
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
        "metadata": {
            "protein_id": "prot-abc",
            "ligand_id": "lig-xyz",
        },
    }

    mock_client = MagicMock()
    mock_client.executions.get.return_value = fake_dto

    abfe = ABFE.from_id("exec-123", client=mock_client)

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
    assert params.dt == 0.002
    assert params.temperature == 300.0
    assert params.cutoff == 1.0
    assert params.repeats == 2
    assert params.binding_n_windows == 24
    assert params.solvation_n_windows == 16
    assert params.binding_steps == 100000
    assert params.solvation_steps == 50000

    assert "prot-abc" in repr(abfe)
    assert "lig-xyz" in repr(abfe)


def test_abfe_from_id_repr_without_prepared_system_lv0():
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


def test_abfe_duplicate_lv0():
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
