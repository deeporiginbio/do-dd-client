import os
from pathlib import Path

import numpy as np
import pytest

from deeporigin.drug_discovery.constants import SUPPORTED_ATOM_SYMBOLS
from deeporigin.drug_discovery.structures import Ligand
from deeporigin.exceptions import DeepOriginException

# Import shared test fixtures
from tests.utils_ligands import (
    bad_ligands,
    ligands,
    single_ligand_files,
    single_ligand_hashes,
)

base_path = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.mark.parametrize("ligand_file", single_ligand_files)
def test_ligand_hash_stable(ligand_file):
    """check that the ligand hash doesn't change if we perform various read-only operations"""

    ligand = Ligand.from_sdf(ligand_file)

    hash_before = ligand.to_hash()
    ligand.show()
    ligand.get_heavy_atom_count()
    ligand.get_conformer_id()
    ligand.get_coordinates(0)
    ligand.get_species()
    ligand.to_molblock()
    ligand.get_formula()
    _ = ligand.contains_boron
    _ = ligand.coordinates
    _ = ligand.atom_types
    ligand.to_base64()
    ligand.get_center()
    ligand.draw()
    ligand.__str__()
    hash_after = ligand.to_hash()

    assert hash_before == hash_after


def test_ligand_is_charged():
    """Test that the is_charged method returns the correct value"""
    ligand = Ligand.from_smiles("C[N+]1=CCCC1", name="Ethanol")
    assert ligand.is_charged(), "Expected this ligand to be charged"


@pytest.mark.parametrize(
    "smiles,name,expected_atoms,equivalent_smiles",
    [
        ("C", "Methane", 1, None),  # Methane
        ("CC", "Ethane", 2, None),  # Ethane
        ("CCO", "Ethanol", 3, None),  # Ethanol
        ("c1ccccc1", "Benzene", 6, ["C1=CC=CC=C1"]),  # Benzene (aromatic notation)
        ("C1=CC=CC=C1", "Benzene_alt", 6, ["c1ccccc1"]),  # Benzene (Kekule notation)
    ],
)
def test_ligand_from_smiles(smiles, name, expected_atoms, equivalent_smiles):
    """Test that we can create a Ligand from a SMILES string using the from_smiles classmethod"""
    from rdkit import Chem

    # Create a ligand using the from_smiles method
    ligand = Ligand.from_smiles(
        smiles=smiles,
        name=name,
        save_to_file=False,
    )

    # Verify the ligand has either the exact SMILES string or an equivalent one
    if equivalent_smiles:
        assert ligand.smiles in [smiles] + equivalent_smiles, (
            f"SMILES {ligand.smiles} not equivalent to {smiles} or any of {equivalent_smiles}"
        )
    else:
        assert ligand.smiles == smiles

    # Verify the name was set correctly
    assert ligand.name == name

    # Verify that the file field is None
    assert ligand.file_path is None

    # Verify that the molecule was properly initialized
    assert ligand.mol is not None
    assert ligand.mol.GetNumAtoms() == expected_atoms

    # Verify that the molecule represents the same chemical structure
    input_mol = Chem.MolFromSmiles(smiles)
    assert Chem.MolToSmiles(input_mol) == Chem.MolToSmiles(ligand.mol)


def test_ligand_from_smiles_invalid():
    """Test that invalid SMILES raises DeepOriginException"""
    with pytest.raises(DeepOriginException, match=r"Cannot create"):
        Ligand.from_smiles(smiles="InvalidSMILES")


@pytest.mark.xfail(reason="Depends on external data sources and can be unreliable")
@pytest.mark.parametrize(
    "identifier,expected_atoms",
    [
        ("ATP", 31),  # Adenosine triphosphate
        ("ADP", 27),  # Adenosine diphosphate
        ("Oxotremorine", 15),  # Muscarinic acetylcholine receptor agonist
        ("Serotonin", 13),  # 5-hydroxytryptamine (5-HT)
    ],
)
def test_ligand_from_identifier(identifier, expected_atoms):
    """Test that we can create a Ligand from common biochemical identifiers using the from_identifier classmethod"""

    # Create a ligand using the from_identifier method
    ligand = Ligand.from_identifier(identifier=identifier)

    # Verify the name was set correctly
    assert ligand.name == identifier

    # Verify that the file field is None
    assert ligand.file_path is None

    # Verify that the molecule was properly initialized
    assert ligand.mol is not None
    assert ligand.mol.GetNumAtoms() == expected_atoms

    # Verify that the molecule has valid 3D coordinates
    assert ligand.mol.GetNumConformers() > 0
    coords = ligand.mol.GetConformer().GetPositions()
    assert coords.shape[0] == expected_atoms


def test_ligand_from_identifier_invalid():
    """Test that invalid identifier raises appropriate exception"""
    invalid_id = "InvalidMolecule123"
    with pytest.raises(
        DeepOriginException,
        match=f"Error resolving SMILES string of {invalid_id}",
    ):
        Ligand.from_identifier(identifier=invalid_id)


def test_ligand_from_rdkit_mol():
    """Test that we can create a Ligand from an RDKit Mol object using the from_rdkit_mol classmethod"""
    from rdkit import Chem

    # Create test RDKit molecules
    mols = [
        Chem.MolFromSmiles("C"),  # Methane
        Chem.MolFromSmiles("CC"),  # Ethane
        Chem.MolFromSmiles("CCO"),  # Ethanol
        Chem.MolFromSmiles("c1ccccc1"),  # Benzene
    ]

    for mol in mols:
        # Create a ligand using the from_rdkit_mol method
        ligand = Ligand.from_rdkit_mol(mol, name="TestLigand")

        # Verify the ligand has the correct SMILES string
        assert ligand.smiles == Chem.MolToSmiles(mol)

        # Verify the name was set correctly
        assert ligand.name == "TestLigand"

        # Verify that the file field is None
        assert ligand.file_path is None

        # Verify that the molecule was properly initialized
        assert ligand.mol is not None
        assert ligand.mol.GetNumAtoms() == mol.GetNumAtoms()


def test_ligand_from_sdf():
    """Test that we can create a Ligand from an SDF file using the from_sdf classmethod"""
    # Use the brd-7.sdf file which contains exactly one ligand
    # Find the ligand entry for brd-7.sdf from the imported ligands variable
    brd7_ligand = next(ligand for ligand in ligands if "brd-7.sdf" in ligand["file"])
    sdf_file = brd7_ligand["file"]

    # Create a ligand using the from_sdf method
    ligand = Ligand.from_sdf(sdf_file)

    # Verify the ligand was created successfully
    assert isinstance(ligand, Ligand)
    assert ligand.mol is not None
    assert ligand.mol.GetNumAtoms() > 0

    # Verify that the file_path was set correctly
    assert ligand.file_path == sdf_file

    # Verify that the ligand has a name
    assert ligand.name is not None
    assert ligand.name != "Unknown_Ligand"

    # Verify that the ligand has SMILES
    assert ligand.smiles is not None

    # Verify that the ligand has properties (SDF files typically contain properties)
    assert isinstance(ligand.properties, dict)


def test_ligand_base64():
    brd7_ligand = next(ligand for ligand in ligands if "brd-7.sdf" in ligand["file"])
    sdf_file = brd7_ligand["file"]

    ligand = Ligand.from_sdf(sdf_file)

    b64 = ligand.to_base64()
    new_ligand = Ligand.from_base64(b64)

    assert new_ligand.smiles == ligand.smiles


@pytest.mark.parametrize(
    "sdf_file, hash_value",
    zip(
        single_ligand_files,
        single_ligand_hashes,
        strict=True,
    ),
)
def test_ligand_hash(sdf_file, hash_value):
    """Test the to_hash method that returns SHA256 hash of SDF content"""

    ligand = Ligand.from_sdf(sdf_file)

    # Get the hash
    assert ligand.to_hash() == hash_value, (
        f"Error in computing hash for {sdf_file}. Computed hash: {ligand.to_hash()}, Expected hash: {hash_value}"
    )


@pytest.mark.parametrize("ligand", bad_ligands)
def test_ligand_errors(ligand):
    with pytest.raises(DeepOriginException):  # noqa: B017
        Ligand(
            file_path=ligand["file"],
            smiles=ligand["smiles_string"],
        )


@pytest.mark.parametrize("ligand", ligands)
def test_ligand(ligand):
    """Test that we can create Ligand instances from various sources"""
    n_ligands = ligand["n_ligands"]

    if n_ligands >= 1:
        return

    result = Ligand.from_sdf(ligand["file"])

    assert isinstance(result, Ligand)
    assert result.mol is not None
    assert result.mol.GetNumAtoms() > 0
    assert (
        result.file_path == ligand["file"]
    )  # Single ligand case should have file_path


def test_ligand_from_sdf_multiple_raises():
    """Test that Ligand.from_sdf raises DeepOriginException for multi-molecule SDF files."""
    with pytest.raises(
        DeepOriginException,
        match="must contain exactly one molecule, but found 8",
    ):
        Ligand.from_sdf(os.path.join(base_path, "ligands-brd-all.sdf"))


def test_ligand_mol_from_file():
    """Test the mol_from_file class method"""
    # Test with a valid SDF file
    brd7_ligand = next(ligand for ligand in ligands if "brd-7.sdf" in ligand["file"])
    sdf_file = brd7_ligand["file"]

    mol = Ligand.mol_from_file(file_type="sdf", file_path=sdf_file)
    assert mol is not None
    assert mol.GetNumAtoms() > 0


@pytest.mark.parametrize("file_type", ["mol", "mol2", "pdb", "xyz", "sdf"])
def test_ligand_mol_from_file_formats(file_type):
    """Test mol_from_file with different file formats"""
    # Skip unsupported formats for now (would need test files)
    if file_type in ["mol2", "pdb", "xyz"]:
        pytest.skip(f"Test file for {file_type} format not available")

    # Test with SDF format
    if file_type == "sdf":
        brd7_ligand = next(
            ligand for ligand in ligands if "brd-7.sdf" in ligand["file"]
        )
        sdf_file = brd7_ligand["file"]

        mol = Ligand.mol_from_file(file_type=file_type, file_path=sdf_file)
        assert mol is not None


# Test instance methods
def test_ligand_process_mol():
    """Test the process_mol method for salt removal and kekulization"""

    # Create a simple molecule
    ligand = Ligand.from_smiles("CCO", name="Ethanol")

    # The process_mol method is called in __post_init__, so the molecule should already be processed
    assert ligand.mol is not None
    assert ligand.mol.GetNumAtoms() == 3


def test_ligand_prepare_basic():
    """Prepare should salt-strip, kekulize, and validate atom types"""

    ligand = Ligand.from_smiles("CCO", name="Ethanol")
    # Ensure prepare runs and sets properties
    prepared = ligand.prepare()

    assert prepared is ligand
    assert ligand.mol is not None
    # All atoms supported
    assert all(a in SUPPORTED_ATOM_SYMBOLS for a in ligand.atom_types)
    # Prepared prop
    assert ligand.get_property("prepared"), "Ligand should be prepared"


def test_ligand_prepare_remove_hydrogens():
    """Test prepare with remove_hydrogens parameter"""

    ligand = Ligand.from_smiles("CCO", name="Ethanol")
    ligand.add_hydrogens()  # Add hydrogens first

    # Test with remove_hydrogens=True
    ligand.prepare(remove_hydrogens=True)
    assert "H" not in ligand.smiles  # Should not contain explicit hydrogens

    # Test with remove_hydrogens=False (default)
    ligand2 = Ligand.from_smiles("CCO", name="Ethanol")
    ligand2.add_hydrogens()
    ligand2.prepare(remove_hydrogens=False)
    assert "H" in ligand2.smiles  # Should contain explicit hydrogens

    # Test default behavior (should preserve hydrogens)
    ligand3 = Ligand.from_smiles("CCO", name="Ethanol")
    ligand3.add_hydrogens()
    ligand3.prepare()  # Default should be remove_hydrogens=False
    assert "H" in ligand3.smiles  # Should contain explicit hydrogens


def test_ligand_prepare_rejects_unsupported_atoms():
    """Ligands with unsupported atoms should be rejected by prepare()."""

    # Include boron (unsupported) in a simple fragment
    lig = Ligand.from_smiles("B")
    with pytest.raises(DeepOriginException, match="Unsupported atom types"):
        lig.prepare()


def test_ligand_conformer_management():
    """Test conformer-related methods"""
    ligand = Ligand.from_smiles("CCO", name="Ethanol")

    # Test get_conformer
    conformer = ligand.get_conformer(0)
    assert conformer is not None

    # Test get_conformer_id
    conformer_id = ligand.get_conformer_id()
    assert isinstance(conformer_id, int)

    # Test set_conformer_id
    ligand.set_conformer_id(5)
    assert ligand.get_conformer_id() == 5


def test_ligand_embed_and_hydrogens():
    """Test embedding and hydrogen addition methods"""
    ligand = Ligand.from_smiles("CCO", name="Ethanol")

    # Test add_hydrogens
    original_atom_count = ligand.mol.GetNumAtoms()
    ligand.add_hydrogens()
    assert ligand.mol.GetNumAtoms() > original_atom_count

    # Test embed
    ligand.embed(add_hydrogens=False, seed=42)
    assert ligand.mol.GetNumConformers() > 0

    # Test get_coordinates
    coords = ligand.get_coordinates(0)
    assert coords.shape[0] == ligand.mol.GetNumAtoms()
    assert coords.shape[1] == 3  # x, y, z coordinates


def test_ligand_property_management():
    """Test property setting and getting methods"""
    ligand = Ligand.from_smiles("CCO", name="Ethanol")

    # Test set_property
    ligand.set_property("test_prop", "test_value")
    assert ligand.properties["test_prop"] == "test_value"

    # Test get_property
    value = ligand.get_property("test_prop")
    assert value == "test_value"

    # Test get_property with non-existent property
    assert ligand.get_property("non_existent") is None


def test_ligand_file_writing():
    """Test file writing methods"""
    ligand = Ligand.from_smiles("CCO", name="Ethanol")

    # Test write_to_file with SDF format
    sdf_path = ligand.write_to_file(output_format="sdf")
    assert Path(sdf_path).exists()
    assert Path(sdf_path).suffix == ".sdf"

    # Test to_sdf method
    sdf_path2 = ligand.to_sdf()
    assert Path(sdf_path2).exists()

    # Test to_mol method
    mol_path = ligand.to_mol()
    assert Path(mol_path).exists()
    assert Path(mol_path).suffix == ".mol"

    # Test to_pdb method
    pdb_path = ligand.to_pdb()
    assert Path(pdb_path).exists()
    assert Path(pdb_path).suffix == ".pdb"

    # Clean up test files
    for path in [sdf_path, sdf_path2, mol_path, pdb_path]:
        if Path(path).exists():
            Path(path).unlink()


def test_ligand_visualization():
    """Test visualization methods"""
    ligand = Ligand.from_smiles("CCO", name="Ethanol")

    # Test draw method (returns RDKit drawing)
    drawing = ligand.draw()
    assert drawing is not None

    ligand.show()


def test_ligand_coordinate_updates():
    """Test coordinate update methods"""
    ligand = Ligand.from_smiles("CCO", name="Ethanol")

    # Ensure ligand has coordinates
    if ligand.mol.GetNumConformers() == 0:
        ligand.embed()

    # Get original coordinates
    original_coords = ligand.get_coordinates(0)

    # Create new coordinates (slightly modified)
    new_coords = original_coords + 0.1

    # Update coordinates
    ligand.update_coordinates(new_coords)

    # Verify coordinates were updated
    updated_coords = ligand.get_coordinates(0)
    assert not np.array_equal(original_coords, updated_coords)
    assert np.array_equal(new_coords, updated_coords)


# Test properties
def test_ligand_coordinates_property():
    """Test the coordinates property"""
    ligand = Ligand.from_smiles("CCO", name="Ethanol")

    # Ensure ligand has coordinates
    if ligand.mol.GetNumConformers() == 0:
        ligand.embed()

    # Test the coordinates property
    coords = ligand.coordinates
    assert isinstance(coords, np.ndarray)
    assert coords.dtype == np.float32
    assert coords.shape[0] == ligand.mol.GetNumAtoms()
    assert coords.shape[1] == 3


def test_ligand_atom_types_property():
    """Test the atom_types property"""
    ligand = Ligand.from_smiles("CCO", name="Ethanol")

    # Test the atom_types property
    atom_types = ligand.atom_types
    assert isinstance(atom_types, list)
    assert len(atom_types) == ligand.mol.GetNumAtoms()
    assert "C" in atom_types
    assert "O" in atom_types


def test_ligand_contains_boron():
    """Test the contains_boron property"""
    # Test ligand without boron
    ligand_no_boron = Ligand.from_smiles("CCO", name="Ethanol")
    assert not ligand_no_boron.contains_boron
    assert ligand_no_boron.available_for_docking

    # Test ligand with boron (if we had one)
    # This would require a SMILES with boron atoms
    # For now, just test the property exists
    assert hasattr(ligand_no_boron, "contains_boron")


def test_ligand_coordinate_mismatch():
    """Test coordinate update with mismatched atom count"""
    ligand = Ligand.from_smiles("CCO", name="Ethanol")

    # Ensure ligand has coordinates
    if ligand.mol.GetNumConformers() == 0:
        ligand.embed()

    # Try to update with wrong number of coordinates
    wrong_coords = np.array([[0.0, 0.0, 0.0]])  # Only 1 atom, but ligand has 3

    with pytest.raises(
        DeepOriginException, match="Number of ligand atoms does not match"
    ):
        ligand.update_coordinates(wrong_coords)


def test_ligand_no_conformers():
    """Test handling of molecules without conformers"""
    ligand = Ligand.from_smiles("CCO", name="Ethanol")

    # Remove all conformers
    ligand.mol.RemoveAllConformers()

    # Test that get_coordinates raises an error
    with pytest.raises(ValueError, match="Bad Conformer Id"):
        ligand.get_coordinates(0)

    # Test that update_coordinates raises an error
    coords = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    with pytest.raises(
        DeepOriginException, match="Ligand molecule has no conformers to update"
    ):
        ligand.update_coordinates(coords)


def test_ligand_property_inheritance():
    """Test how properties are handled during initialization"""
    ligand = Ligand.from_smiles("CCO", name="Ethanol")

    # Check that initial_smiles property was set
    assert ligand.mol.HasProp("initial_smiles")

    # Check that name property was set (it's set in write_to_file, not __post_init__)
    # The name property is only set when writing to file, so we'll test that instead
    assert ligand.name == "Ethanol"


def test_ligand_file_path_handling():
    """Test file path resolution and directory creation"""
    ligand = Ligand.from_smiles("CCO", name="Ethanol")

    # Test that directory creation works
    directory = ligand._get_directory()
    assert Path(directory).exists()
    assert "ligands" in directory

    # Test that save_to_file works when enabled
    ligand.save_to_file = True
    # This would create a file in the directory, but we'll skip the actual file creation
    # to avoid cluttering the test environment


# Test utility functions
def test_ligands_to_dataframe():
    """Test the ligands_to_dataframe utility function"""
    from deeporigin.drug_discovery.structures.ligand import ligands_to_dataframe

    # Create test ligands
    ligands_list = [
        Ligand.from_smiles("CCO", name="Ethanol"),
        Ligand.from_smiles("CCCO", name="Propanol"),
    ]

    # Add some properties
    ligands_list[0].set_property("logP", 0.32)
    ligands_list[1].set_property("logP", 0.88)

    # Convert to dataframe
    df = ligands_to_dataframe(ligands_list)

    assert len(df) == 2
    assert "SMILES" in df.columns
    assert "logP" in df.columns
    assert df.iloc[0]["logP"] == pytest.approx(0.32)
    assert df.iloc[1]["logP"] == pytest.approx(0.88)
