"""Tests for Protein.has_ligand_clashes()."""

import copy

import numpy as np
import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, Ligand, Protein
from deeporigin.drug_discovery.utils.structure_qc import _any_ligand_protein_clashes
from deeporigin.exceptions import DeepOriginException


def _load_brd_protein() -> Protein:
    """Return the bundled BRD protein fixture."""
    return Protein.from_file(BRD_DATA_DIR / "brd.pdb")


def _load_brd_pose() -> Ligand:
    """Return the bundled BRD reference pose fixture."""
    return Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")


def test_has_ligand_clashes_good_pose() -> None:
    """A sensible reference pose should not report clashes at the default cutoff."""
    protein = _load_brd_protein()
    ligand = _load_brd_pose()

    assert protein.has_ligand_clashes(ligand) is False


def test_has_ligand_clashes_bad_pose() -> None:
    """Placing the ligand on a protein CA atom should report clashes."""
    protein = _load_brd_protein()
    ligand = _load_brd_pose()

    ca_mask = (protein.structure.atom_name == "CA") & (~protein.structure.hetero)
    ca_coord = protein.structure.coord[ca_mask][0]
    clashing_coords = np.tile(ca_coord, (len(ligand.coordinates), 1))
    ligand.update_coordinates(clashing_coords)

    assert protein.has_ligand_clashes(ligand) is True


def test_has_ligand_clashes_contact_distance() -> None:
    """Contact distance should flag binding contacts but not distant poses."""
    protein = _load_brd_protein()
    binding_pose = _load_brd_pose()
    distant_pose = copy.deepcopy(binding_pose)
    distant_pose.update_coordinates(binding_pose.coordinates + 100.0)

    assert protein.has_ligand_clashes(binding_pose, contact_distance=4.0) is True
    assert protein.has_ligand_clashes(distant_pose, contact_distance=4.0) is False


def test_has_ligand_clashes_accepts_sdf_path() -> None:
    """The method accepts an SDF path in addition to a Ligand object."""
    protein = _load_brd_protein()

    assert protein.has_ligand_clashes(BRD_DATA_DIR / "brd-2.sdf") is False


def test_has_ligand_clashes_no_3d_raises() -> None:
    """Ligands without 3D coordinates should raise DeepOriginException."""
    protein = _load_brd_protein()
    ligand = Ligand.from_smiles("CCO")

    with pytest.raises(DeepOriginException, match="3D coordinates"):
        protein.has_ligand_clashes(ligand)


def test_has_ligand_clashes_protein_atoms_only() -> None:
    """Default filtering excludes hetero atoms such as waters from clash checks."""
    protein = _load_brd_protein()
    ligand = _load_brd_pose()

    structure = protein.structure
    protein_mask = (~structure.hetero) & (structure.element != "H")
    protein_coords = structure.coord[protein_mask]
    water_mask = (structure.res_name == "HOH") & (structure.element == "O")
    water_coords = structure.coord[water_mask]
    min_protein_distances = np.linalg.norm(
        protein_coords[:, np.newaxis, :] - water_coords[np.newaxis, :, :],
        axis=2,
    ).min(axis=0)
    isolated_water = water_coords[np.argmax(min_protein_distances)]
    ligand.update_coordinates(np.tile(isolated_water, (len(ligand.coordinates), 1)))

    assert protein.has_ligand_clashes(ligand) is False
    assert (
        protein.has_ligand_clashes(
            ligand,
            protein_atoms_only=False,
            exclude_waters=False,
        )
        is True
    )


def test_any_ligand_protein_clashes_empty_inputs() -> None:
    """Empty coordinate sets should not be treated as clashes."""
    assert (
        _any_ligand_protein_clashes(
            np.empty((0, 3)),
            np.array([[0.0, 0.0, 0.0]]),
            contact_distance=2.5,
        )
        is False
    )
