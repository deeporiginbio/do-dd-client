"""Tests for :class:`deeporigin.drug_discovery.constrained_docking.ConstrainedDocking`."""

import json
from pathlib import Path

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, ConstrainedDocking, Docking, Ligand
from deeporigin.drug_discovery.constrained_docking import (
    _constraints_from_reference,
    _validate_explicit_constraints,
)
from deeporigin.drug_discovery.structures.ligand import LigandSet
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from tests.conftest import check_tool_exists

_SAMPLE_CONSTRAINTS = [
    {"coordinates": [-15.0, -0.23, 10.56], "energy": 5.0, "index": 1},
]


def test_constrained_docking_requires_constraints_or_reference(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """Constructor requires exactly one of constraints or reference."""
    with pytest.raises(ValueError, match="Exactly one of constraints or reference"):
        ConstrainedDocking(
            protein=registered_protein,
            pocket=unregistered_pocket,
            ligand=registered_ligand,
            client=client,
        )

    with pytest.raises(ValueError, match="Exactly one of constraints or reference"):
        ConstrainedDocking(
            protein=registered_protein,
            pocket=unregistered_pocket,
            ligand=registered_ligand,
            constraints=_SAMPLE_CONSTRAINTS,
            reference=registered_ligand,
            client=client,
        )


def test_constrained_docking_rejects_invalid_effort(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """Constructor rejects effort outside 1–5."""
    with pytest.raises(DeepOriginException, match="effort must be between"):
        ConstrainedDocking(
            protein=registered_protein,
            pocket=unregistered_pocket,
            ligand=registered_ligand,
            constraints=_SAMPLE_CONSTRAINTS,
            effort=0,
            client=client,
        )


def test_validate_explicit_constraints_requires_keys() -> None:
    """Explicit constraints must include index, coordinates, and energy."""
    with pytest.raises(ValueError, match="missing required keys"):
        _validate_explicit_constraints([{"index": 1}])


def test_build_tool_inputs_includes_file_path_and_sync(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """Payload includes ligand file_path and constraints (no ``sync`` input)."""
    cd = ConstrainedDocking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
        constraints=_SAMPLE_CONSTRAINTS,
        client=client,
    )
    cd._ensure_platform_inputs()
    params, _metadata = cd._build_tool_inputs()

    assert params["constraints"] == _SAMPLE_CONSTRAINTS
    assert "sync" not in params
    assert len(params["ligands"]) == 1
    assert params["ligands"][0]["file_path"] == registered_ligand.remote_path
    assert params["ligands"][0]["id"] == registered_ligand.id


def test_constraints_from_reference_produces_expected_shape() -> None:
    """Reference path returns constraint dicts with required keys."""
    query = Ligand.from_sdf(BRD_DATA_DIR / "brd-3.sdf")
    reference = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")
    constraints = _constraints_from_reference(
        ligand=query,
        reference=reference,
        constraint_energy=5.0,
    )
    assert constraints
    for entry in constraints:
        assert {"index", "coordinates", "energy"} <= set(entry.keys())
        assert entry["index"] >= 1


def test_constrained_docking_from_dto_maps_fields(client) -> None:
    """from_dto rehydrates protein, pocket, ligand, constraints, and effort."""
    fixture_path = (
        Path(__file__).parent
        / "fixtures/executions/constrained-docking-test-execution.json"
    )
    dto = json.loads(fixture_path.read_text())

    cd = ConstrainedDocking.from_dto(dto, client=client)

    assert cd.id == dto["executionId"]
    assert cd.status == dto["status"]
    assert cd.effort == 1
    assert cd.constraints == dto["userInputs"]["constraints"]
    assert cd.ligand.id == "brd-2"
    assert cd.protein.id == "brd"
    assert cd.reference is None


def test_constrained_docking_from_dto_raises_on_tool_key_mismatch(client) -> None:
    """from_dto fails fast when DTO tool key does not match."""
    fixture_path = (
        Path(__file__).parent
        / "fixtures/executions/constrained-docking-test-execution.json"
    )
    dto = json.loads(fixture_path.read_text())
    dto["tool"]["key"] = "deeporigin.foo-fake-tool"

    with pytest.raises(ValueError, match="tool key mismatch"):
        ConstrainedDocking.from_dto(dto, client=client)


@pytest.mark.expects_results
def test_constrained_docking_run_quote_true(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """run(quote=True) returns None and populates estimate."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["constrained_docking"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["constrained_docking"]["tool_version"],
    ), "Constrained docking tool not registered on platform."

    cd = ConstrainedDocking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
        constraints=_SAMPLE_CONSTRAINTS,
        client=client,
    )
    result = cd.run(quote=True)

    assert result is None
    assert cd.estimate is not None
    assert cd.status == "Quoted"


@pytest.mark.expects_results
def test_constrained_docking_run_with_explicit_constraints(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """run() with explicit constraints returns docked poses."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["constrained_docking"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["constrained_docking"]["tool_version"],
    )

    cd = ConstrainedDocking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
        constraints=_SAMPLE_CONSTRAINTS,
        client=client,
    )
    poses = cd.run()

    assert isinstance(poses, LigandSet)
    assert len(poses) >= 1
    for pose in poses:
        assert pose.mol is not None
        assert pose.smiles is not None


@pytest.mark.expects_results
def test_constrained_docking_run_with_reference_mcs_workflow(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """Dock a reference ligand, then constrained-dock a similar ligand via reference=."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["docking"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["docking"]["tool_version"],
    )
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["constrained_docking"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["constrained_docking"]["tool_version"],
    )

    ref_docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
        client=client,
    )
    ref_poses = ref_docking.run()
    assert ref_poses is not None and len(ref_poses) >= 1
    reference_pose = ref_poses.ligands[0]

    query_ligand = Ligand.from_sdf(BRD_DATA_DIR / "brd-3.sdf")
    query_ligand.sync(
        client=client,
        remote_path="testing/constrained-docking/brd-3.sdf",
    )

    cd = ConstrainedDocking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=query_ligand,
        reference=reference_pose,
        client=client,
    )
    poses = cd.run()

    assert isinstance(poses, LigandSet)
    assert len(poses) >= 1
