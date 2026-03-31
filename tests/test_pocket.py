"""
Tests for the Pocket class.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, Pocket, Protein
from deeporigin.exceptions import MethodDeprecatedError

if TYPE_CHECKING:
    from deeporigin.platform import DeepOriginClient

_BRD_PDB = Path(os.path.join(BRD_DATA_DIR, "brd.pdb"))


def test_pocket_from_ligand_lv0():
    protein = Protein.from_pdb_id("1EBY")

    ligand = protein.extract_ligand()

    pocket = Pocket.from_ligand(ligand)

    assert pocket.local_path is not None, "Pocket local_path should not be None"


def test_pocket_get_center_lv0():
    """Test getting the center of a pocket."""
    protein = Protein.from_pdb_id("1EBY")
    ligand = protein.extract_ligand()
    pocket = Pocket.from_ligand(ligand)

    center = pocket.get_center()
    assert center is not None, "Center should be calculated"

    assert pocket.get_center().shape == (3,), "Pocket center shape is wrong"


def test_pocket_update_coordinates_lv0():
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


def test_from_json_empty_list_lv0():
    """Empty input returns an empty list without raising."""
    result = Pocket.from_json([])
    assert result == []


def test_from_json_single_entry_lv0():
    """A single valid entry creates one Pocket with the correct attributes."""
    data = [{"file_path": str(_BRD_PDB), "protein_id": "prot_1", "volume": 42.0}]

    pockets = Pocket.from_json(data)

    assert len(pockets) == 1
    pocket = pockets[0]
    assert pocket.name == "brd"
    assert pocket.local_path == str(_BRD_PDB)
    assert pocket.protein_id == "prot_1"
    assert pocket.color == "red"
    assert pocket.volume == pytest.approx(42.0)
    assert pocket.id is None


def test_from_json_id_is_set_lv0():
    """When an 'id' key is present it should populate the Pocket.id attribute."""
    data = [{"id": "pocket-abc-123", "file_path": str(_BRD_PDB)}]

    pocket = Pocket.from_json(data)[0]

    assert pocket.id == "pocket-abc-123"
    assert "id" not in (pocket.props or {})


def test_from_json_protein_id_not_in_props_lv0():
    """protein_id must be mapped to its own attribute and excluded from props."""
    data = [{"file_path": str(_BRD_PDB), "protein_id": "prot_abc"}]

    pocket = Pocket.from_json(data)[0]

    assert pocket.protein_id == "prot_abc"
    assert "protein_id" not in (pocket.props or {})


def test_from_json_extra_keys_go_to_props_lv0():
    """Known property keys become attributes; file_path/protein_id are excluded from props."""
    data = [
        {
            "file_path": str(_BRD_PDB),
            "protein_id": "p1",
            "volume": 100.0,
            "drugability_score": 0.8,
        }
    ]

    pocket = Pocket.from_json(data)[0]

    assert pocket.volume == pytest.approx(100.0)
    assert pocket.drugability_score == pytest.approx(0.8)
    assert "file_path" not in (pocket.props or {})


def test_from_json_no_protein_id_lv0():
    """Entries without protein_id should have protein_id set to None."""
    pocket = Pocket.from_json([{"file_path": str(_BRD_PDB)}])[0]

    assert pocket.protein_id is None


def test_from_json_missing_file_path_raises_lv0():
    """An entry missing the file_path key must raise ValueError with the index."""
    data = [{"protein_id": "p1", "volume": 10.0}]

    with pytest.raises(ValueError, match="index 0"):
        Pocket.from_json(data)


def test_from_json_null_file_path_raises_lv0():
    """A None file_path must raise ValueError with the index."""
    data = [{"file_path": None}]

    with pytest.raises(ValueError, match="index 0"):
        Pocket.from_json(data)


def test_from_json_empty_string_file_path_raises_lv0():
    """An empty-string file_path must raise ValueError with the index."""
    data = [{"file_path": ""}]

    with pytest.raises(ValueError, match="index 0"):
        Pocket.from_json(data)


def test_from_json_whitespace_file_path_raises_lv0():
    """A whitespace-only file_path must raise ValueError with the index."""
    data = [{"file_path": "   "}]

    with pytest.raises(ValueError, match="index 0"):
        Pocket.from_json(data)


def test_from_json_error_reports_correct_index_lv0():
    """ValueError for a bad entry mid-list must report the correct index."""
    data = [
        {"file_path": str(_BRD_PDB)},
        {"file_path": str(_BRD_PDB)},
        {"file_path": None},  # index 2 is bad
    ]

    with pytest.raises(ValueError, match="index 2"):
        Pocket.from_json(data)


def test_from_function_result_lv0():
    """from_function_result stores remote_path without downloading."""
    import json

    from deeporigin.functions.result import FunctionResult

    fixture = Path(__file__).parent / (
        "fixtures/function-runs/deeporigin.pocketfinder/run.json"
    )
    from tests.fixture_utils import patch_fixture_version

    response = patch_fixture_version(json.loads(fixture.read_text()))

    result = FunctionResult([response])

    class FakeClient:
        """Minimal client stub (no file ops needed -- lazy download)."""

    pockets = Pocket.from_function_result(
        result=result,
        client=FakeClient(),
    )

    assert len(pockets) == 1
    pocket = pockets[0]
    assert pocket.remote_path is not None
    assert pocket.local_path is None
    assert pocket.coordinates is None
    assert pocket.protein_id == "brd"
    assert pocket.volume == pytest.approx(300)
    assert pocket.center == pytest.approx([-13.521, -4.944, 15.457], abs=1e-3)
    assert pocket.box_size_x == pytest.approx(14)
    assert pocket.box_size_y == pytest.approx(14)
    assert pocket.box_size_z == pytest.approx(19)
    assert pocket.drugability_score == pytest.approx(0.94304204)


def test_from_residue_num_lv0():
    """Test creating a pocket from a residue number"""

    # Read in a protein
    pdb_path = os.path.join(BRD_DATA_DIR, "brd.pdb")
    protein = Protein.from_file(pdb_path)

    # Create custom pocket
    custom_pocket = Pocket.from_residue_number(protein, residue_number=77, cutoff=5)

    assert isinstance(
        custom_pocket.get_center(), np.ndarray
    ) and custom_pocket.get_center().shape == (3,)


def test_protein_find_pockets_deprecated_lv0():
    """Protein.find_pockets() is deprecated; it raises MethodDeprecatedError."""
    protein = Protein.from_file(_BRD_PDB)
    with pytest.raises(MethodDeprecatedError) as exc_info:
        protein.find_pockets(pocket_count=1)
    assert "PocketFinder" in str(exc_info.value)
    assert "deprecated" in str(exc_info.value).lower()


def test_from_id_lv2(
    client: "DeepOriginClient",
    registered_protein: Protein,
):
    """Test round-trip: Pocket.from_result -> Pocket.from_id (lazy download)"""

    pockets_from_result = Pocket.from_result(client=client)
    assert len(pockets_from_result) >= 1

    pocket = pockets_from_result[0]
    assert pocket.id is not None
    assert pocket.remote_path is not None
    assert pocket.local_path is None
    assert pocket.coordinates is None
    assert pocket.protein_id is not None
    assert pocket.center is not None
    assert len(pocket.center) == 3
    assert pocket.box_size_x is not None
    assert pocket.box_size_y is not None
    assert pocket.box_size_z is not None

    coords = pocket._ensure_coordinates()
    assert coords is not None
    assert pocket.local_path is not None
    assert Path(pocket.local_path).exists()

    fetched = Pocket.from_id(pocket.id, client=client)

    assert fetched.id == pocket.id
    assert fetched.remote_path is not None
    assert fetched.local_path is None
    assert fetched.protein_id == pocket.protein_id
    assert fetched.center is not None
    assert len(fetched.center) == 3
    assert fetched.box_size_x is not None
    assert fetched.box_size_y is not None
    assert fetched.box_size_z is not None
