"""Tests for interactive docking box helpers in docking_common."""

import numpy as np
import pytest

from deeporigin.drug_discovery.docking_common import (
    _euler_rotation_matrix_deg,
    _zyx_euler_deg_from_matrix,
    build_pocket_tool_params,
    lab_frame_aabb_extents_from_obb,
    normalize_rotation_deg,
    parse_docking_box_commit,
    transpose_rotation_deg,
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
    """parse_docking_box_commit extracts center, box_size, and lab→working Euler."""
    mesh = transpose_rotation_deg([0.0, 45.0, 0.0])
    center, box_size, rotation = parse_docking_box_commit(
        {
            "center": [1.0, 2.0, 3.0],
            "box_size": [10.0, 11.0, 12.0],
            "rotation_deg": mesh,
        }
    )
    assert center == [1.0, 2.0, 3.0]
    assert box_size == [10.0, 11.0, 12.0]
    assert rotation == pytest.approx([0.0, 45.0, 0.0])


def test_parse_docking_box_commit_inverts_mesh_euler() -> None:
    """Viewer mesh Euler is transposed to lab→working for docking."""
    lab_working = [30.0, 45.0, 15.0]
    _, _, parsed = parse_docking_box_commit(
        {
            "center": [1.0, 2.0, 3.0],
            "box_size": [10.0, 11.0, 12.0],
            "rotation_deg": transpose_rotation_deg(lab_working),
        }
    )
    got = _euler_rotation_matrix_deg(parsed)
    expected = _euler_rotation_matrix_deg(lab_working)
    assert got == pytest.approx(expected)


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


def test_lab_frame_aabb_extents_uses_transpose_of_r() -> None:
    """AABB extents use |Rᵀ| @ obb, not |R| @ obb (DDOS-7441)."""
    obb = [22.0, 10.0, 4.0]
    rotation_deg = [30.0, 45.0, 15.0]
    rotation = _euler_rotation_matrix_deg(rotation_deg)
    expected = (np.abs(rotation.T) @ np.asarray(obb)).tolist()
    mirrored = (np.abs(rotation) @ np.asarray(obb)).tolist()
    got = lab_frame_aabb_extents_from_obb(obb, rotation_deg)
    assert got == pytest.approx(expected)
    assert got != pytest.approx(mirrored)


def test_lab_frame_aabb_extents_identity_is_unchanged() -> None:
    """Identity rotation leaves OBB extents unchanged in lab frame."""
    assert lab_frame_aabb_extents_from_obb([10.0, 11.0, 12.0], [0.0, 0.0, 0.0]) == [
        10.0,
        11.0,
        12.0,
    ]


def test_transpose_rotation_deg_negates_pure_y() -> None:
    """A pure Y rotation transposes to the negated angle."""
    assert transpose_rotation_deg([0.0, 45.0, 0.0]) == pytest.approx([0.0, -45.0, 0.0])


def test_transpose_rotation_deg_round_trips_matrix() -> None:
    """transpose_rotation_deg is involutive on the rotation matrix."""
    angles = [30.0, 45.0, 15.0]
    recovered = transpose_rotation_deg(transpose_rotation_deg(angles))
    got = _euler_rotation_matrix_deg(recovered)
    expected = _euler_rotation_matrix_deg(angles)
    assert got == pytest.approx(expected)


def test_zyx_euler_recovers_rotation_matrix() -> None:
    """Extracted ZYX Euler rebuilds the original matrix, including gimbal lock."""
    for angles in (
        [0.0, 45.0, 0.0],
        [30.0, 45.0, 15.0],
        [90.0, 0.0, 0.0],
        [0.0, 90.0, 0.0],
        [0.0, -90.0, 10.0],
        [0.0, 0.0, 90.0],
    ):
        rotation = _euler_rotation_matrix_deg(angles)
        extracted = _zyx_euler_deg_from_matrix(rotation)
        assert _euler_rotation_matrix_deg(extracted) == pytest.approx(rotation)
