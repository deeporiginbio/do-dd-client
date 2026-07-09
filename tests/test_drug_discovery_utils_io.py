"""Tests for small drug-discovery utility modules (collections, files, geometry)."""

from pathlib import Path

import pytest

from deeporigin.drug_discovery.utils.collections import chunker
from deeporigin.drug_discovery.utils.files import move_file_with_extension, remove_file
from deeporigin.drug_discovery.utils.geometry import (
    calculate_box_dimensions,
    calculate_box_min_max,
)


def test_chunker_splits_iterable() -> None:
    """chunker yields fixed-size lists from an iterable."""
    assert list(chunker(range(5), 2)) == [[0, 1], [2, 3], [4]]


def test_chunker_single_element() -> None:
    """chunker handles a one-item iterable."""
    assert list(chunker([42], 3)) == [[42]]


def test_chunker_empty_iterable() -> None:
    """chunker yields nothing for an empty iterable."""
    assert list(chunker([], 2)) == []


def test_remove_file_missing(tmp_path: Path) -> None:
    """remove_file is a no-op when the path does not exist."""
    remove_file(str(tmp_path / "missing.txt"))


def test_remove_file_existing(tmp_path: Path) -> None:
    """remove_file deletes an existing file."""
    target = tmp_path / "delete-me.txt"
    target.write_text("x", encoding="utf-8")

    remove_file(str(target))

    assert not target.exists()


def test_move_file_with_extension_no_conflict(tmp_path: Path) -> None:
    """move_file_with_extension is a no-op when the target extension is absent."""
    src = tmp_path / "ligand.dat"
    src.write_text("data", encoding="utf-8")

    move_file_with_extension(str(src), "sdf")

    assert src.exists()
    assert not (tmp_path / "ligand.sdf").exists()


def test_move_file_with_extension_renames_conflict(tmp_path: Path) -> None:
    """move_file_with_extension renames an existing target file with a counter suffix."""
    src = tmp_path / "ligand.dat"
    src.write_text("new", encoding="utf-8")
    existing = tmp_path / "ligand.sdf"
    existing.write_text("old", encoding="utf-8")

    move_file_with_extension(str(src), "sdf")

    assert not existing.exists()
    assert (tmp_path / "ligand_#1.sdf").read_text(encoding="utf-8") == "old"
    assert src.exists()


def test_calculate_box_min_max_round_trip() -> None:
    """calculate_box_min_max and calculate_box_dimensions are inverse operations."""
    center = [1.0, 2.0, 3.0]
    dimensions = [4.0, 6.0, 8.0]

    min_corner, max_corner = calculate_box_min_max(center, dimensions)
    recovered = calculate_box_dimensions(min_corner, max_corner)

    assert recovered == dimensions


def test_calculate_box_dimensions_invalid_length() -> None:
    """calculate_box_dimensions requires 3D min and max coordinates."""
    with pytest.raises(ValueError, match="exactly 3 elements"):
        calculate_box_dimensions([0.0, 0.0], [1.0, 1.0, 1.0])
