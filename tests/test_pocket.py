"""
Tests for the Pocket class.
"""

import os

import numpy as np

from deeporigin.drug_discovery import BRD_DATA_DIR, Pocket, Protein


def test_pocket_from_ligand():
    protein = Protein.from_pdb_id("1EBY")

    ligand = protein.extract_ligand()

    pocket = Pocket.from_ligand(ligand)

    assert pocket.file_path is not None, "Pocket file path should not be None"


def test_pocket_get_center():
    """Test getting the center of a pocket."""
    protein = Protein.from_pdb_id("1EBY")
    ligand = protein.extract_ligand()
    pocket = Pocket.from_ligand(ligand)

    center = pocket.get_center()
    assert center is not None, "Center should be calculated"

    assert pocket.get_center().shape == (3,), "Pocket center shape is wrong"


def test_pocket_update_coordinates():
    """Test updating pocket coordinates."""
    protein = Protein.from_pdb_id("1EBY")
    ligand = protein.extract_ligand()
    pocket = Pocket.from_ligand(ligand)

    original_coords = pocket.coordinates.copy()
    new_coords = original_coords + 1.0  # Shift all coordinates by 1

    pocket.update_coordinates(new_coords)

    assert np.array_equal(pocket.coordinates, new_coords), (
        "Coordinates should be updated"
    )


def test_from_residue_num():
    """Test creating a pocket from a residue number"""

    # Read in a protein
    pdb_path = os.path.join(BRD_DATA_DIR, "brd.pdb")
    protein = Protein.from_file(pdb_path)

    # Create custom pocket
    custom_pocket = Pocket.from_residue_number(protein, residue_number=77, cutoff=5)

    assert isinstance(
        custom_pocket.get_center(), np.ndarray
    ) and custom_pocket.get_center().shape == (3,)
