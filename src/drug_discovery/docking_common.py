"""Shared helpers for docking-family tool execution classes."""

from __future__ import annotations

import os
from typing import Any

import numpy as np

from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient


def resolve_docking_box_geometry(pocket: Pocket) -> tuple[list[float], list[float]]:
    """Resolve pocket center and box extents for docking tool inputs.

    Box sizes default to ``2 * cbrt(volume)`` per axis when not set on the pocket.

    Args:
        pocket: Binding pocket defining the search box.

    Returns:
        A tuple of (pocket_center, box_size) where each is a length-3 list of
        floats in Angstroms.
    """
    default_box = float(2 * np.cbrt(pocket.volume or 0))
    box_size_x = pocket.box_size_x if pocket.box_size_x is not None else default_box
    box_size_y = pocket.box_size_y if pocket.box_size_y is not None else default_box
    box_size_z = pocket.box_size_z if pocket.box_size_z is not None else default_box
    pocket_center = pocket.get_center().tolist()
    box_size = [float(box_size_x), float(box_size_y), float(box_size_z)]
    return pocket_center, box_size


def build_pocket_tool_params(
    pocket: Pocket,
    pocket_center: list[float],
    box_size: list[float],
) -> dict[str, Any]:
    """Build pocket dict for docking tool ``inputs``."""
    pocket_params: dict[str, Any] = {
        "box_size_x": box_size[0],
        "box_size_y": box_size[1],
        "box_size_z": box_size[2],
        "center": pocket_center,
    }
    if pocket.id is not None:
        pocket_params["id"] = pocket.id
    return pocket_params


def build_docking_metadata(protein: Protein) -> dict[str, str]:
    """Build execution metadata for docking-family tools."""
    protein_ref = protein.local_path or protein.remote_path
    protein_hash = ""
    if protein.structure is not None:
        protein_hash = protein.to_hash()
    return {
        "protein_file": os.path.basename(str(protein_ref)) if protein_ref else "",
        "protein_hash": protein_hash,
    }


def load_docking_poses_from_execution(
    exec_id: str,
    *,
    client: DeepOriginClient,
    dto: dict[str, Any] | None = None,
    all_poses: bool = False,
) -> LigandSet:
    """Load docked poses from the data platform or execution ``jobOutputs``.

    Args:
        exec_id: Platform execution ID.
        client: API client.
        dto: Optional execution payload to avoid an extra GET.
        all_poses: When ``True``, include every pose instead of only the best
            pose per ligand.

    Returns:
        A ``LigandSet`` of docked poses.

    Raises:
        DeepOriginException: If no poses could be loaded.
    """
    best_pose: bool | None = None if all_poses else True

    try:
        return LigandSet.from_result(
            execution_id=exec_id,
            best_pose=best_pose,
            client=client,
        )
    except Exception:
        pass

    try:
        if dto is None:
            dto = client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
        jo = dto.get("jobOutputs")
        raw = jo.get("poses", []) if isinstance(jo, dict) else []
        return LigandSet.from_json(raw, client=client)
    except Exception as exc:
        raise DeepOriginException(
            title="Could not load docking poses",
            message=("No poses could be parsed from the data platform or jobOutputs."),
        ) from exc


def load_reference_pose_from_execution(
    exec_id: str,
    *,
    client: DeepOriginClient,
    dto: dict[str, Any] | None = None,
) -> Ligand:
    """Load the reference pose from a constrained docking execution.

    Args:
        exec_id: Platform execution ID.
        client: API client.
        dto: Optional execution payload to avoid an extra GET.

    Returns:
        The reference pose as a :class:`Ligand`.

    Raises:
        DeepOriginException: If no reference pose could be loaded.
    """
    if dto is None:
        dto = client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
    jo = dto.get("jobOutputs")
    if isinstance(jo, dict):
        raw = jo.get("reference_pose")
        if isinstance(raw, dict):
            pose_set = LigandSet.from_json([raw], client=client)
            return pose_set.ligands[0]

    raise DeepOriginException(
        title="Could not load reference pose",
        message=(
            "No reference_pose could be parsed from jobOutputs for this execution."
        ),
    )
