"""tests for abfe"""

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, Complex, Ligand, Protein
from deeporigin.exceptions import DeepOriginException


def test_abfe_charged_ligand():
    """test that abfe raises an error if a charged ligand is provided"""

    ligand = Ligand.from_smiles("C[N+]1=CCCC1")
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    sim = Complex(protein=protein, ligands=ligand)

    with pytest.raises(
        DeepOriginException,
        match="ABFE does not currently support charged ligands",
    ):
        sim.abfe.run()


def test_abfe_prepared_system():
    """test that abfe raises an error if a prepared system is not provided"""
    ligand = Ligand.from_smiles("CCO")
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    sim = Complex(protein=protein, ligands=ligand)
    with pytest.raises(DeepOriginException, match="is not prepared"):
        sim.abfe.run()


def test_check_dt_defaults_valid():
    """default parameters should have in-range dt everywhere"""

    ligand = Ligand.from_smiles("CCO")
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    sim = Complex(protein=protein, ligands=ligand)

    # Should not raise
    sim.abfe.check_dt()


def test_check_dt_raises_on_out_of_range():
    """setting any nested dt out of range should raise an error"""

    ligand = Ligand.from_smiles("CCO")
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    sim = Complex(protein=protein, ligands=ligand)

    # Deliberately set an out-of-range dt deep inside the params
    sim.abfe._params.end_to_end["binding"]["prod_md_options"]["dt"] = 0.01

    with pytest.raises(
        DeepOriginException,
        match=r"Found invalid dt values; must be numeric and within range \[0.001, 0.004\]",
    ):
        sim.abfe.check_dt()
