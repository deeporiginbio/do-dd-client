"""Restoring docking executions preserves the submitted pocket geometry."""

import copy
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deeporigin.drug_discovery.constrained_docking import ConstrainedDocking
from deeporigin.drug_discovery.docking import Docking
from deeporigin.drug_discovery.structures.ligand import LigandSet
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.structures.protein import Protein
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


def _restore(cls, dto: dict, *, from_id=None):
    """Run from_dto with the pocket row lookup mocked; return (obj, mock)."""
    mock = MagicMock(side_effect=from_id) if from_id else MagicMock()
    ligands = MagicMock()
    ligands.ligands = [MagicMock()]
    with (
        patch.object(Pocket, "from_id", mock),
        patch.object(Protein, "from_id", MagicMock()),
        patch.object(LigandSet, "from_ids", MagicMock(return_value=ligands)),
        patch(
            "deeporigin.drug_discovery.constrained_docking._ligand_from_structure_input",
            MagicMock(),
        ),
    ):
        return cls.from_dto(dto, client=MagicMock(spec=DeepOriginClient)), mock


@pytest.mark.parametrize("cls,fixture", CASES)
def test_id_plus_edited_geometry_uses_snapshot(cls, fixture) -> None:
    """The submitted geometry wins over the referenced pocket row."""
    dto = _dto(fixture, {"id": "pocket-1", "center": CENTER, **SIZES})
    obj, from_id = _restore(cls, dto)

    from_id.assert_not_called()
    assert obj.pocket.id == "pocket-1"
    assert list(obj.pocket.center) == CENTER
    assert (obj.pocket.box_size_x, obj.pocket.box_size_y, obj.pocket.box_size_z) == (
        10.0,
        12.0,
        14.0,
    )


@pytest.mark.parametrize("cls,fixture", CASES)
def test_deleted_pocket_row_does_not_break_restore(cls, fixture) -> None:
    """Restore succeeds when the referenced result row no longer exists."""
    dto = _dto(fixture, {"id": "gone", "center": CENTER, **SIZES})
    obj, _ = _restore(cls, dto, from_id=ValueError("No pocket record found"))
    assert obj.pocket.id == "gone"


@pytest.mark.parametrize("cls,fixture", CASES)
@pytest.mark.parametrize("rotation", [[10.0, 20.0, 30.0], [0.0, 0.0, 0.0]])
def test_rotation_round_trips_to_session_rotation(cls, fixture, rotation) -> None:
    """Stored rotation (including explicit identity) is restored."""
    dto = _dto(fixture, {"center": CENTER, **SIZES, "rotation_deg": rotation})
    obj, _ = _restore(cls, dto)
    assert obj._rotation_deg == rotation


@pytest.mark.parametrize("cls,fixture", CASES)
def test_absent_rotation_restores_as_none(cls, fixture) -> None:
    """No stored rotation leaves session rotation unset."""
    obj, _ = _restore(cls, _dto(fixture, {"center": CENTER, **SIZES}))
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
def test_invalid_sizes_raise_on_restore(cls, fixture, bad) -> None:
    """Zero, negative, non-finite, or missing sizes are rejected."""
    pocket = {"id": "p", "center": CENTER, **SIZES, **bad}
    with pytest.raises(ValueError, match="box"):
        _restore(cls, _dto(fixture, pocket))


@pytest.mark.parametrize("cls,fixture", CASES)
def test_missing_center_raises_on_restore(cls, fixture) -> None:
    """A snapshot without a center is rejected."""
    with pytest.raises(ValueError, match="center"):
        _restore(cls, _dto(fixture, {"id": "p", **SIZES}))


@pytest.mark.parametrize("cls,fixture", CASES)
def test_legacy_id_only_refetches_pocket(cls, fixture) -> None:
    """With no geometry snapshot, the ID is the only source."""
    row = Pocket(id="legacy", center=CENTER, **SIZES)
    obj, from_id = _restore(
        cls, _dto(fixture, {"id": "legacy"}), from_id=lambda *a, **k: row
    )
    from_id.assert_called_once()
    assert obj.pocket is row


@pytest.mark.parametrize("cls,fixture", CASES)
def test_legacy_id_only_with_deleted_row_gives_clear_error(cls, fixture) -> None:
    """A deleted row and no snapshot names the ID and the missing snapshot."""
    with pytest.raises(ValueError, match="no pocket geometry snapshot.*legacy"):
        _restore(
            cls,
            _dto(fixture, {"id": "legacy"}),
            from_id=ValueError("No pocket record found"),
        )


@pytest.mark.parametrize("cls,fixture", CASES)
def test_no_pocket_inputs_at_all_raises(cls, fixture) -> None:
    """No snapshot and no ID cannot be restored."""
    with pytest.raises(ValueError, match="pocket"):
        _restore(cls, _dto(fixture, None))


def test_resolver_rejects_pocket_without_sizes_or_volume() -> None:
    """The old zero-sized fallback is gone."""
    from deeporigin.drug_discovery.docking_common import resolve_pocket_docking_box

    with pytest.raises(ValueError, match="box"):
        resolve_pocket_docking_box(Pocket(id=None, center=CENTER))


def _constrained_tool_inputs(rotation: list[float] | None) -> dict:
    """Restore a ConstrainedDocking and return its submitted ``inputs``."""
    pocket = {"center": CENTER, **SIZES}
    if rotation is not None:
        pocket["rotation_deg"] = rotation
    cd, _ = _restore(
        ConstrainedDocking,
        _dto("constrained-docking-test-execution.json", pocket),
    )
    cd._ligands = []
    cd._reference_ligand = MagicMock(smiles="C")
    cd._reference_pose = MagicMock()
    module = "deeporigin.drug_discovery.constrained_docking"
    with (
        patch(f"{module}.build_docking_metadata", MagicMock(return_value={})),
        patch(f"{module}._reference_pose_tool_input_row", MagicMock(return_value={})),
    ):
        params, _ = cd._build_tool_inputs()
    return params


def test_constrained_submits_restored_rotation() -> None:
    """A restored rotation is re-submitted as pocket.rotation_deg."""
    params = _constrained_tool_inputs([10.0, 20.0, 30.0])
    assert params["pocket"]["rotation_deg"] == [10.0, 20.0, 30.0]
    assert params["pocket"]["box_size_y"] == 12.0


def test_constrained_omits_rotation_when_unset() -> None:
    """No session rotation means no rotation_deg in the submitted pocket."""
    assert "rotation_deg" not in _constrained_tool_inputs(None)["pocket"]
