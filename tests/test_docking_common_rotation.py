"""Tests for interactive docking box helpers in docking_common."""

import pytest

from deeporigin.drug_discovery.docking_common import (
    build_pocket_tool_params,
    lab_frame_aabb_extents_from_obb,
    normalize_rotation_deg,
    parse_docking_box_commit,
)


def test_normalize_rotation_deg_accepts_sequence() -> None:
    """normalize_rotation_deg returns a float triple for valid input."""
    assert normalize_rotation_deg([0.0, 45.0, -10.0]) == [0.0, 45.0, -10.0]


def test_normalize_rotation_deg_accepts_xyz_dict() -> None:
    """normalize_rotation_deg accepts x/y/z dict payloads from older prototypes."""
    assert normalize_rotation_deg({"x": 1.0, "y": 2.0, "z": 3.0}) == [1.0, 2.0, 3.0]


def test_normalize_rotation_deg_none_and_zero_are_identity() -> None:
    """Absent or all-zero rotation normalizes to None."""
    assert normalize_rotation_deg(None) is None
    assert normalize_rotation_deg([0.0, 0.0, 0.0]) is None


def test_normalize_rotation_deg_rejects_invalid_length() -> None:
    """normalize_rotation_deg rejects wrong-length sequences."""
    with pytest.raises(ValueError, match="length 3"):
        normalize_rotation_deg([0.0, 1.0])


def test_normalize_rotation_deg_rejects_non_numeric_dict() -> None:
    """normalize_rotation_deg raises ValueError for non-numeric dict values."""
    with pytest.raises(ValueError, match="length-3 sequence of numbers"):
        normalize_rotation_deg({"x": None, "y": 1.0, "z": 2.0})


def test_parse_docking_box_commit_returns_geometry() -> None:
    """parse_docking_box_commit extracts center, box_size, and rotation."""
    center, box_size, rotation = parse_docking_box_commit(
        {
            "center": [1.0, 2.0, 3.0],
            "box_size": [10.0, 11.0, 12.0],
            "rotation_deg": [0.0, 45.0, 0.0],
        }
    )
    assert center == [1.0, 2.0, 3.0]
    assert box_size == [10.0, 11.0, 12.0]
    assert rotation == [0.0, 45.0, 0.0]


def test_build_pocket_tool_params_includes_rotation_deg(
    unregistered_pocket,
) -> None:
    """build_pocket_tool_params forwards non-identity rotation_deg."""
    params = build_pocket_tool_params(
        unregistered_pocket,
        [1.0, 2.0, 3.0],
        [10.0, 10.0, 10.0],
        rotation_deg=[0.0, 45.0, 0.0],
    )
    assert params["rotation_deg"] == [0.0, 45.0, 0.0]


def test_build_pocket_tool_params_omits_identity_rotation(
    unregistered_pocket,
) -> None:
    """build_pocket_tool_params omits rotation_deg when identity."""
    params = build_pocket_tool_params(
        unregistered_pocket,
        [1.0, 2.0, 3.0],
        [10.0, 10.0, 10.0],
        rotation_deg=[0.0, 0.0, 0.0],
    )
    assert "rotation_deg" not in params


def test_lab_frame_aabb_extents_from_obb_y_rotation() -> None:
    """45° Y rotation expands lab-frame X/Z AABB from local OBB extents."""
    aabb = lab_frame_aabb_extents_from_obb([22.0, 20.0, 21.0], [0.0, 45.0, 0.0])
    assert aabb[0] == pytest.approx(30.405, rel=1e-3)
    assert aabb[1] == pytest.approx(20.0)
    assert aabb[2] == pytest.approx(30.405, rel=1e-3)


def test_lab_frame_aabb_extents_identity_is_unchanged() -> None:
    """Identity rotation leaves OBB extents unchanged in lab frame."""
    assert lab_frame_aabb_extents_from_obb([10.0, 11.0, 12.0], [0.0, 0.0, 0.0]) == [
        10.0,
        11.0,
        12.0,
    ]
