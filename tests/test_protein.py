import os

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, Protein
from deeporigin.exceptions import DeepOriginException


def test_from_file():
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")

    assert (
        str(protein.sequence[0])
        == "STNPPPPETSNPNKPKRQTNQLQYLLRVVLKTLWKHQFAWPFQQPVDAVKLNLPDYYKIIKTPMDMGTIKKRLENNYYWNAQECIQDFNTMFTNCYIYNKPGDDIVLMAEALEKLFLQKINELPTE"
    )


def test_from_name(pytestconfig):
    """Test creating a protein from a name.

    Note: This test is skipped when using --mock flag as it requires
    a real network connection to the RCSB search API.
    """
    use_mock = pytestconfig.getoption("--mock", default=False)
    if use_mock:
        pytest.skip("Skipping test_from_name with --mock (requires RCSB search API)")

    protein = Protein.from_name("conotoxin")
    assert protein.pdb_id == "1FU3"

    assert str(protein.sequence[0]) == "WCKQSGEMCNLLDQNCCDGYCIVLVCT"


def test_from_pdb_id():
    conotoxin = Protein.from_pdb_id("2JUQ")

    os.remove(conotoxin.file_path)

    _ = Protein.from_pdb_id("2JUQ")


def test_from_pdb_id_with_invalid_id():
    with pytest.raises(DeepOriginException, match=r".*Failed to create Protein.*"):
        Protein.from_pdb_id("foobar")


def test_find_missing_residues():
    protein = Protein.from_pdb_id("5QSP")
    missing = protein.find_missing_residues()
    # The expected output is based on the documentation example
    expected = {
        "A": [(511, 514), (547, 550), (679, 682), (841, 855)],
        "B": [(509, 516), (546, 551), (679, 684), (840, 854)],
    }
    assert missing == expected


def test_pdb_id():
    protein = Protein.from_pdb_id("1EBY")
    assert protein.pdb_id == "1EBY"


def test_extract_ligand():
    protein = Protein.from_pdb_id("1EBY")
    ligand = protein.extract_ligand()

    assert (
        ligand.smiles
        == "OC(N[C@H]1C2CCCCC2C[C@H]1O)[C@H](OCC1CCCCC1)[C@H](O)[C@@H](O)[C@@H](OCC1CCCCC1)[C@@H](O)N[C@H]1C2CCCCC2C[C@H]1O"
    )


def test_extract_ligand_mutates_protein():
    """Test that extract_ligand both extracts the ligand and removes it from the protein."""
    protein = Protein.from_pdb_id("1EBY")

    # Store initial state
    initial_structure_length = len(protein.structure)
    initial_block_content_length = (
        len(protein.block_content) if protein.block_content else 0
    )

    # Extract the ligand
    ligand = protein.extract_ligand()

    # Verify the ligand was extracted correctly
    expected_smiles = "OC(N[C@H]1C2CCCCC2C[C@H]1O)[C@H](OCC1CCCCC1)[C@H](O)[C@@H](O)[C@@H](OCC1CCCCC1)[C@@H](O)N[C@H]1C2CCCCC2C[C@H]1O"
    assert ligand.smiles == expected_smiles

    # Verify the protein structure was mutated (ligand removed)
    assert len(protein.structure) < initial_structure_length

    # Verify the block_content was updated
    if protein.block_content:
        assert len(protein.block_content) < initial_block_content_length

        # Verify that the protein structure no longer contains the ligand atoms
        # The structure should have fewer atoms after ligand removal
        assert len(protein.structure) < initial_structure_length


def test_extract_ligand_updates_master_record():
    """Test that extract_ligand properly updates the MASTER record in the PDB content."""
    protein = Protein.from_pdb_id("1EBY")

    # Find the initial MASTER record
    initial_master_line = None
    for line in protein.block_content.split("\n"):
        if line.startswith("MASTER"):
            initial_master_line = line
            break

    assert initial_master_line is not None, "MASTER record should exist in PDB"

    # Parse initial values
    parts = initial_master_line.split()
    initial_atom_count = int(parts[8])  # Field 9: total number of atoms
    initial_conect_count = int(parts[10])  # Field 11: total number of CONECT records

    # Extract the ligand
    ligand = protein.extract_ligand()

    # Find the updated MASTER record
    updated_master_line = None
    for line in protein.block_content.split("\n"):
        if line.startswith("MASTER"):
            updated_master_line = line
            break

    assert updated_master_line is not None, (
        "MASTER record should still exist after ligand extraction"
    )

    # Parse updated values
    parts = updated_master_line.split()
    updated_atom_count = int(parts[8])
    updated_conect_count = int(parts[10])

    # Verify that the MASTER record was updated
    assert updated_atom_count < initial_atom_count, (
        "Atom count should decrease after ligand removal"
    )
    assert updated_conect_count <= initial_conect_count, (
        "CONECT count should not increase after ligand removal"
    )

    # Verify the ligand was extracted correctly
    expected_smiles = "OC(N[C@H]1C2CCCCC2C[C@H]1O)[C@H](OCC1CCCCC1)[C@H](O)[C@@H](O)[C@@H](OCC1CCCCC1)[C@@H](O)N[C@H]1C2CCCCC2C[C@H]1O"
    assert ligand.smiles == expected_smiles


def test_protein_base64():
    """Test that we can convert a Protein to base64 and back"""
    # Create a protein using from_pdb_id
    protein = Protein.from_pdb_id("1EBY")

    # Convert to base64
    b64 = protein.to_base64()

    # Convert back from base64
    new_protein = Protein.from_base64(b64)

    # Verify the structures have the same number of atoms
    assert len(new_protein.structure) == len(protein.structure)

    # Verify the structures have the same coordinates (within numerical precision)
    import numpy as np

    np.testing.assert_array_almost_equal(
        new_protein.structure.coord,
        protein.structure.coord,
        decimal=3,
    )


def test_protein_hash():
    """Test that we can convert a Protein to SHA256 hash"""
    # Create a protein using from_pdb_id
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")

    assert (
        "db4aa32e2e8ffa976a60004a8361b86427a2e5653a6623bb60b7913445902549"
        == protein.to_hash()
    ), "Protein hash did not match"


def test_extract_ligand_remove_water():
    """check that we can remove waters after we extract the ligand"""

    protein = Protein.from_pdb_id("1EBY")
    _ = protein.extract_ligand()

    protein.remove_water()
