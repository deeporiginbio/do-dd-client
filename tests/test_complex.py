import os

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, Complex, Ligand, LigandSet, Protein
from deeporigin.exceptions import DeepOriginException
from tests.utils import client  # noqa: F401


def test_from_dir_2_pdb(client):  # noqa: F811
    """Test creating a Complex from a directory with 2 PDB files"""

    # Find the original PDB file in BRD_DATA_DIR
    pdb_files = [f for f in os.listdir(BRD_DATA_DIR) if f.endswith(".pdb")]

    original_pdb = pdb_files[0]
    original_pdb_path = os.path.join(BRD_DATA_DIR, original_pdb)
    copy_pdb_path = os.path.join(BRD_DATA_DIR, "copy_" + original_pdb)

    # Make a copy of the pdb file
    import shutil

    shutil.copyfile(original_pdb_path, copy_pdb_path)

    try:
        with pytest.raises(
            DeepOriginException,
            match="Expected exactly one PDB file in the directory, but found 2: ",
        ):
            Complex.from_dir(BRD_DATA_DIR, client=client)
    finally:
        # Clean up: delete the copy
        os.remove(copy_pdb_path)


def test_from_dir(client):  # noqa: F811
    """Test creating a Complex from the example data directory"""
    # Create Complex from directory
    complex_obj = Complex.from_dir(BRD_DATA_DIR, client=client)

    # Verify the complex was created correctly
    assert isinstance(complex_obj, Complex)
    assert isinstance(complex_obj.protein, Protein)

    # Verify we have the expected number of ligands
    # The example directory contains multiple SDF files with multiple molecules each
    assert len(complex_obj.ligands) > 0

    # Verify all ligands are valid
    for ligand in complex_obj.ligands:
        assert isinstance(ligand, Ligand)
        assert ligand.smiles is not None
        assert ligand.name is not None

    # Verify the protein is valid
    assert complex_obj.protein.name == "brd"


def test_construct_complex(client):  # noqa: F811
    """Test constructing a Complex by providing protein and ligands directly"""
    # Create protein from PDB file
    pdb_path = os.path.join(BRD_DATA_DIR, "brd.pdb")
    protein = Protein.from_file(pdb_path)

    # Create ligands from SDF files
    ligands = []
    sdf_files = ["brd-2.sdf", "brd-3.sdf"]  # Testing with a subset of ligands
    for sdf_file in sdf_files:
        sdf_path = os.path.join(BRD_DATA_DIR, sdf_file)
        result = Ligand.from_sdf(sdf_path)
        if isinstance(result, list):
            ligands.extend(result)
        else:
            ligands.append(result)

    # Create Complex
    complex_obj = Complex(protein=protein, ligands=ligands, client=client)

    # Verify the complex was created correctly
    assert isinstance(complex_obj, Complex)
    assert isinstance(complex_obj.protein, Protein)
    assert complex_obj.protein.name == "brd"
    assert len(complex_obj.ligands) > 0

    # Verify all ligands are valid
    for ligand in complex_obj.ligands:
        assert isinstance(ligand, Ligand)
        assert ligand.smiles is not None
        assert ligand.name is not None


def test_prepare_missing_residues(client):  # noqa: F811
    """Test preparing a Complex with missing residues"""
    # Create a Complex with a protein with missing residues
    protein = Protein.from_pdb_id("5QSP")
    protein.find_missing_residues()
    sim = Complex(
        protein=protein, ligands=LigandSet.from_dir(BRD_DATA_DIR), client=client
    )
    with pytest.raises(
        DeepOriginException,
        match="Protein has missing residues. Please use the loop modelling tool to fill in the missing residues.",
    ):
        sim.prepare()
