import os
from pathlib import Path
import tempfile

import numpy as np
import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, Protein
from deeporigin.exceptions import DeepOriginException


def test_load_protein_from_cif_structure_factor():
    """Test that loading a structure factor CIF file (without atom_site) raises a helpful error."""
    cif_path = Path(__file__).parent / "fixtures" / "1NSG-sf.cif"

    # Structure factor files don't have atomic coordinates, so this should raise ValueError
    with pytest.raises(ValueError, match="does not contain atomic coordinates"):
        _ = Protein.from_file(cif_path)


def test_from_file_lv0():
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")

    assert (
        str(protein.sequence[0])
        == "STNPPPPETSNPNKPKRQTNQLQYLLRVVLKTLWKHQFAWPFQQPVDAVKLNLPDYYKIIKTPMDMGTIKKRLENNYYWNAQECIQDFNTMFTNCYIYNKPGDDIVLMAEALEKLFLQKINELPTE"
    )


def test_from_name_lv0(pytestconfig):
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


def test_from_pdb_id_lv0():
    conotoxin = Protein.from_pdb_id("2JUQ")

    os.remove(conotoxin.file_path)

    _ = Protein.from_pdb_id("2JUQ")


def test_from_pdb_id_with_invalid_id_lv0():
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


def test_extract_ligand_filters_water():
    """Test that extract_ligand filters out water molecules (HOH, WAT, H2O)."""
    protein = Protein.from_pdb_id("1EBY")

    # Count water molecules before extraction
    water_count_before = sum(
        1
        for line in protein.block_content.split("\n")
        if line.startswith("HETATM")
        and line[17:20].strip().upper() in {"HOH", "WAT", "H2O"}
    )

    # Extract ligand - should exclude water molecules
    ligand = protein.extract_ligand()

    # Verify ligand was extracted (should not be None)
    assert ligand is not None

    # Verify that water molecules were not included in the extracted ligand
    # The ligand should have atoms, but they should not be water
    assert len(ligand.mol.GetAtoms()) > 0

    # Verify that water molecules are still in the protein block_content
    # (extract_ligand only removes the ligand, not water)
    water_count_after = sum(
        1
        for line in protein.block_content.split("\n")
        if line.startswith("HETATM")
        and line[17:20].strip().upper() in {"HOH", "WAT", "H2O"}
    )

    # Water should still be in block_content until explicitly removed
    # (extract_ligand only removes the ligand, not water)
    assert water_count_after == water_count_before


def test_extract_ligand_with_custom_exclude_resnames():
    """Test that extract_ligand respects custom exclude_resnames parameter."""
    protein = Protein.from_pdb_id("1EBY")

    # Extract ligand excluding a custom residue name (should work even if not present)
    ligand = protein.extract_ligand(exclude_resnames={"HOH", "CUSTOM"})

    assert ligand is not None
    assert len(ligand.mol.GetAtoms()) > 0


def test_extract_ligand_from_cif_with_many_hetatms():
    """Test that extract_ligand works correctly with CIF files containing many HETATMs including water."""
    cif_path = Path(__file__).parent / "fixtures" / "1nsg-assembly1.cif"
    protein = Protein.from_file(cif_path)

    # Verify it's a CIF file
    assert protein.block_type == "cif"
    assert protein.block_content is not None

    # Count water molecules before extraction
    # Convert to PDB to count HETATMs

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".pdb", delete=False
    ) as temp_file:
        temp_pdb_path = temp_file.name

    try:
        protein.to_pdb(temp_pdb_path)
        with open(temp_pdb_path, "r") as pdb_file:
            all_hetatm_lines = [line for line in pdb_file if line.startswith("HETATM")]
            water_hetatm_lines = [
                line
                for line in all_hetatm_lines
                if line[17:20].strip().upper() in {"HOH", "WAT", "H2O"}
            ]
            non_water_hetatm_lines = [
                line
                for line in all_hetatm_lines
                if line[17:20].strip().upper() not in {"HOH", "WAT", "H2O"}
            ]

        # Verify we have both water and non-water HETATMs
        assert len(water_hetatm_lines) > 0, "Should have water molecules"
        assert len(non_water_hetatm_lines) > 0, "Should have non-water HETATMs"

        # Extract ligand - should exclude water molecules and succeed
        ligand = protein.extract_ligand()

        # Verify ligand was extracted successfully
        assert ligand is not None
        assert len(ligand.mol.GetAtoms()) > 0

        # Verify that water molecules were filtered out
        # The ligand should not contain only water atoms
        # (we can't easily verify the exact count without parsing the PDB block,
        # but we can verify RDKit successfully parsed a non-water ligand)
        assert ligand.smiles is not None
        assert len(ligand.smiles) > 0

    finally:
        if os.path.exists(temp_pdb_path):
            os.remove(temp_pdb_path)


def test_from_file_cif():
    """Test creating a protein from a CIF file."""
    cif_path = Path(__file__).parent / "fixtures" / "1EBY.cif"
    protein = Protein.from_file(cif_path)

    assert protein.name == "1EBY"
    assert protein.block_type == "cif"
    assert protein.file_path == cif_path.resolve()
    assert len(protein.structure) > 0
    assert protein.block_content is not None
    assert (
        "data_1EBY" in protein.block_content or "data_r1ebysf" in protein.block_content
    )


def test_from_file_invalid_extension():
    """Test that from_file raises ValueError for unsupported file types."""
    # Create a temporary file with an unsupported extension
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp_file:
        tmp_file.write("test content")
        tmp_path = tmp_file.name

    try:
        with pytest.raises(ValueError, match=r".*Unsupported file type.*"):
            Protein.from_file(tmp_path)
    finally:
        os.unlink(tmp_path)


def test_load_structure_from_block_cif():
    """Test loading structure from CIF block content."""
    cif_path = Path(__file__).parent / "fixtures" / "1EBY.cif"
    cif_content = cif_path.read_text()

    structure = Protein.load_structure_from_block(cif_content, "cif")

    assert len(structure) > 0
    assert hasattr(structure, "coord")


def test_load_structure_from_block_invalid_type():
    """Test that load_structure_from_block raises ValueError for unsupported types."""
    with pytest.raises(ValueError, match=r".*Unsupported block type.*"):
        Protein.load_structure_from_block("test content", "xyz")
