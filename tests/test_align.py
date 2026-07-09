"""Tests for RDKit alignment helpers."""

from __future__ import annotations

import numpy as np
import pytest
from rdkit import Chem
from rdkit.Chem import AllChem

from deeporigin.drug_discovery.align import (
    compute_constraints,
    mcs,
    preprocess_mol,
    randomize_mol_pose,
    safe_substruct_match,
)


def _ethanol_3d() -> Chem.Mol:
    """Return ethanol with a 3D conformer."""
    mol = Chem.MolFromSmiles("CCO")
    mol = Chem.AddHs(mol)
    AllChem.EmbedMolecule(mol, AllChem.ETKDG())
    return mol


def test_randomize_mol_pose_changes_coordinates() -> None:
    """randomize_mol_pose returns a copy with different atom positions."""
    mol = _ethanol_3d()
    original = [
        list(mol.GetConformer().GetAtomPosition(i)) for i in range(mol.GetNumAtoms())
    ]

    randomized = randomize_mol_pose(mol, seed=7)
    updated = [
        list(randomized.GetConformer().GetAtomPosition(i))
        for i in range(randomized.GetNumAtoms())
    ]

    assert updated != original
    assert mol.GetNumAtoms() == randomized.GetNumAtoms()


def test_randomize_mol_pose_seed_reproducible() -> None:
    """randomize_mol_pose is reproducible for a fixed seed."""
    mol = _ethanol_3d()
    first = randomize_mol_pose(mol, seed=3)
    second = randomize_mol_pose(mol, seed=3)

    for idx in range(mol.GetNumAtoms()):
        p1 = first.GetConformer().GetAtomPosition(idx)
        p2 = second.GetConformer().GetAtomPosition(idx)
        assert np.isclose(p1.x, p2.x)
        assert np.isclose(p1.y, p2.y)
        assert np.isclose(p1.z, p2.z)


def test_preprocess_mol_removes_hydrogens() -> None:
    """preprocess_mol removes explicit hydrogens and sanitizes."""
    mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    processed = preprocess_mol(mol)

    assert processed.GetNumAtoms() < mol.GetNumAtoms()


def test_safe_substruct_match_success() -> None:
    """safe_substruct_match returns atom indices for a valid match."""
    mol = Chem.MolFromSmiles("c1ccccc1O")
    query = Chem.MolFromSmarts("c1ccccc1")
    match = safe_substruct_match(mol, query, "benzene")

    assert len(match) == query.GetNumAtoms()


def test_safe_substruct_match_failure() -> None:
    """safe_substruct_match raises when the query is not found."""
    mol = Chem.MolFromSmiles("CCO")
    query = Chem.MolFromSmarts("c1ccccc1")

    with pytest.raises(ValueError, match="MCS does not match"):
        safe_substruct_match(mol, query, "ethanol")


def test_mcs_finds_common_substructure() -> None:
    """mcs returns a SMARTS molecule shared by related structures."""
    mol_a = Chem.MolFromSmiles("c1ccccc1O")
    mol_b = Chem.MolFromSmiles("c1ccccc1C")
    mcs_mol = mcs([mol_a, mol_b])

    assert mcs_mol is not None
    assert mcs_mol.GetNumAtoms() > 0


def test_compute_constraints_builds_positions() -> None:
    """compute_constraints aligns mols and returns coordinate constraints."""
    reference = _ethanol_3d()
    mol = _ethanol_3d()
    mcs_mol = mcs([reference, mol])

    constraints = compute_constraints(
        mols=[mol],
        reference=reference,
        mcs_mol=mcs_mol,
        energy=2.5,
    )

    assert len(constraints) == 1
    assert constraints[0]
    assert constraints[0][0]["energy"] == 2.5
    assert len(constraints[0][0]["coordinates"]) == 3
