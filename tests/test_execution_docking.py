"""Tests for the Docking execution class."""

import os
from pathlib import Path

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, Protein
from deeporigin.drug_discovery.docking import Docking
from deeporigin.drug_discovery.structures.pocket import Pocket

_BRD_PDB = Path(os.path.join(BRD_DATA_DIR, "brd.pdb"))


@pytest.fixture
def protein():
    """BRD protein with an ID set (required by Docking constructor)."""
    p = Protein.from_file(str(_BRD_PDB))
    p.id = "protein-test-id"
    return p


@pytest.fixture
def pocket():
    """Minimal Pocket with an ID set (required by Docking constructor)."""
    p = Pocket(id="pocket-test-id")
    return p


@pytest.fixture
def docking(protein, pocket):
    """Docking instance built from minimal fixtures."""
    return Docking(
        protein=protein,
        pocket=pocket,
        smiles_list=["CCO"],
    )


def test_docking_quote_cannot_be_called_twice_lv0(docking):
    """quote() raises ValueError if called after a quotation already exists."""
    # Simulate a completed quote by setting state directly
    docking._id = "exec-quoted-456"
    docking.status = "Quoted"

    with pytest.raises(ValueError, match="quotation already exists"):
        docking.quote()
