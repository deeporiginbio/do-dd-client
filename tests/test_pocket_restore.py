"""Restoring docking executions preserves the submitted pocket geometry."""

import copy
import json
from pathlib import Path

import pytest

from deeporigin.drug_discovery.constrained_docking import ConstrainedDocking
from deeporigin.drug_discovery.docking import Docking
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.platform.client import DeepOriginClient

FIXTURES = Path(__file__).parent / "fixtures/executions"
CASES = [
    (Docking, "docking-test-execution.json"),
    (ConstrainedDocking, "constrained-docking-test-execution.json"),
]
CENTER = [1.5, -2.5, 3.5]
SIZES = {"box_size_x": 10.0, "box_size_y": 12.0, "box_size_z": 14.0}


def _dto(fixture: str, pocket: dict | None) -> dict:
    dto = json.loads((FIXTURES / fixture).read_text())
    dto = copy.deepcopy(dto)
    if pocket is None:
        dto["userInputs"].pop("pocket", None)
    else:
        dto["userInputs"]["pocket"] = pocket
    return dto


def _restore(cls, dto: dict, client: DeepOriginClient):
    """Run ``from_dto`` through the mock server's real hydration path."""
    return cls.from_dto(dto, client=client)


@pytest.mark.parametrize("cls,fixture", CASES)
def test_id_plus_edited_geometry_uses_snapshot(cls, fixture, client) -> None:
    """The submitted geometry wins over the referenced pocket row."""
    dto = _dto(fixture, {"id": "pocket-1", "center": CENTER, **SIZES})
    obj = _restore(cls, dto, client)

    assert obj.pocket.id == "pocket-1"
    assert list(obj.pocket.center) == CENTER
    assert (obj.pocket.box_size_x, obj.pocket.box_size_y, obj.pocket.box_size_z) == (
        10.0,
        12.0,
        14.0,
    )


@pytest.mark.parametrize("cls,fixture", CASES)
def test_deleted_pocket_row_does_not_break_restore(cls, fixture, client) -> None:
    """Restore succeeds when the referenced result row no longer exists."""
    dto = _dto(fixture, {"id": "gone", "center": CENTER, **SIZES})
    obj = _restore(cls, dto, client)
    assert obj.pocket.id == "gone"


@pytest.mark.parametrize("cls,fixture", CASES)
@pytest.mark.parametrize("rotation", [[10.0, 20.0, 30.0], [0.0, 0.0, 0.0]])
def test_rotation_round_trips_to_session_rotation(
    cls, fixture, rotation, client
) -> None:
    """Stored rotation (including explicit identity) is restored."""
    dto = _dto(fixture, {"center": CENTER, **SIZES, "rotation_deg": rotation})
    obj = _restore(cls, dto, client)
    assert obj._rotation_deg == rotation


@pytest.mark.parametrize("cls,fixture", CASES)
def test_absent_rotation_restores_as_none(cls, fixture, client) -> None:
    """No stored rotation leaves session rotation unset."""
    obj = _restore(cls, _dto(fixture, {"center": CENTER, **SIZES}), client)
    assert obj._rotation_deg is None


@pytest.mark.parametrize("cls,fixture", CASES)
@pytest.mark.parametrize(
    "bad",
    [
        {"box_size_x": 0.0},
        {"box_size_y": -1.0},
        {"box_size_z": float("nan")},
        {"box_size_x": None},
    ],
)
def test_invalid_sizes_raise_on_restore(cls, fixture, bad, client) -> None:
    """Zero, negative, non-finite, or missing sizes are rejected."""
    pocket = {"id": "p", "center": CENTER, **SIZES, **bad}
    with pytest.raises(ValueError, match="box"):
        _restore(cls, _dto(fixture, pocket), client)


@pytest.mark.parametrize("cls,fixture", CASES)
def test_missing_center_raises_on_restore(cls, fixture, client) -> None:
    """A snapshot without a center is rejected."""
    with pytest.raises(ValueError, match="center"):
        _restore(cls, _dto(fixture, {"id": "p", **SIZES}), client)


@pytest.mark.parametrize("cls,fixture", CASES)
@pytest.mark.parametrize(
    "center",
    [5.0, "abc", [1.0, 2.0], [float("nan"), 0.0, 0.0], [0.0, float("inf"), 0.0]],
)
def test_invalid_center_raises_value_error(cls, fixture, center, client) -> None:
    """Scalar, wrong-length, or non-finite centers are all ValueErrors."""
    pocket = {"id": "p", "center": center, **SIZES}
    with pytest.raises(ValueError, match="center"):
        _restore(cls, _dto(fixture, pocket), client)


@pytest.mark.parametrize("cls,fixture", CASES)
def test_legacy_id_only_refetches_pocket(cls, fixture, client) -> None:
    """With no geometry snapshot, the pocket row is fetched from the mock server."""
    row_id = client.results.get_pockets()["data"][0]["id"]
    obj = _restore(cls, _dto(fixture, {"id": row_id}), client)
    assert obj.pocket.id == row_id


@pytest.mark.parametrize("cls,fixture", CASES)
def test_legacy_id_only_with_deleted_row_gives_clear_error(
    cls, fixture, client
) -> None:
    """A missing row and no snapshot names the ID and the missing snapshot."""
    with pytest.raises(ValueError, match="no pocket geometry snapshot.*legacy"):
        _restore(cls, _dto(fixture, {"id": "legacy"}), client)


@pytest.mark.parametrize("cls,fixture", CASES)
def test_no_pocket_inputs_at_all_raises(cls, fixture, client) -> None:
    """No snapshot and no ID cannot be restored."""
    with pytest.raises(ValueError, match="pocket"):
        _restore(cls, _dto(fixture, None), client)


def test_resolver_rejects_pocket_without_sizes_or_volume() -> None:
    """The old zero-sized fallback is gone."""
    from deeporigin.drug_discovery.docking_common import resolve_pocket_docking_box

    with pytest.raises(ValueError, match="box"):
        resolve_pocket_docking_box(Pocket(id=None, center=CENTER))
