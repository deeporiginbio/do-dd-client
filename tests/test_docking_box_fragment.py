"""Tests for pocket-finder ``box`` consumption in docking_common."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, Pocket
from deeporigin.drug_discovery.docking_common import (
    effective_docking_rotation_deg,
    resolve_pocket_docking_box,
)

_BRD_PDB = Path(os.path.join(BRD_DATA_DIR, "brd.pdb"))

_POCKET_WITH_BOX = {
    "file_path": str(_BRD_PDB),
    "protein_id": "prot_1",
    "volume": 300.0,
    "pocket_center": [1.0, 2.0, 3.0],
    "box_size_x": 25.0,
    "box_size_y": 24.0,
    "box_size_z": 25.0,
    "box": {
        "box_size_x": 22.0,
        "box_size_y": 20.0,
        "box_size_z": 21.0,
        "rotation_deg": [5.0, 10.0, 15.0],
    },
}


def test_resolve_pocket_docking_box_prefers_nested_box() -> None:
    """resolve_pocket_docking_box uses OBB sizes and inferred rotation from box."""
    pocket = Pocket.from_json([_POCKET_WITH_BOX])[0]

    center, box_size, inferred = resolve_pocket_docking_box(pocket)

    assert center == pytest.approx([1.0, 2.0, 3.0])
    assert box_size == pytest.approx([22.0, 20.0, 21.0])
    assert inferred == pytest.approx([5.0, 10.0, 15.0])


def test_resolve_pocket_docking_box_legacy_without_box(
    unregistered_pocket,
) -> None:
    """Legacy pockets without box use parent sizes and no inferred rotation."""
    center, box_size, inferred = resolve_pocket_docking_box(unregistered_pocket)

    assert len(center) == 3
    assert len(box_size) == 3
    assert all(size > 0 for size in box_size)
    assert inferred is None


def test_effective_docking_rotation_deg_prefers_session() -> None:
    """Session rotation overrides pocket-finder inferred orientation."""
    assert effective_docking_rotation_deg(
        session=[0.0, 45.0, 0.0],
        inferred=[5.0, 10.0, 15.0],
    ) == [0.0, 45.0, 0.0]


def test_effective_docking_rotation_deg_uses_inferred_when_session_unset() -> None:
    """Inferred rotation applies when session rotation is unset."""
    assert effective_docking_rotation_deg(
        session=None,
        inferred=[5.0, 10.0, 15.0],
    ) == [5.0, 10.0, 15.0]


def test_effective_docking_rotation_deg_none_when_both_absent() -> None:
    """No rotation when neither session nor inferred orientation is available."""
    assert effective_docking_rotation_deg(session=None, inferred=None) is None
