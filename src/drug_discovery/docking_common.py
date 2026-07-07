"""Shared helpers for docking-family tool execution classes."""

from __future__ import annotations

import os
from typing import Any

import numpy as np

from deeporigin.drug_discovery.structures.ligand import (
    Ligand,
    LigandSet,
    _is_scored_docking_pose_data,
    _ligand_smiles_map_from_tool_payload,
)
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


def _normalize_pose_row_smiles(row: dict[str, Any]) -> None:
    """Copy ``ligand_smiles`` onto ``smiles`` when the latter is absent."""
    if isinstance(row.get("smiles"), str) and row["smiles"].strip():
        return
    ligand_smiles = row.get("ligand_smiles")
    if isinstance(ligand_smiles, str) and ligand_smiles.strip():
        row["smiles"] = ligand_smiles.strip()


def _pose_result_records_to_rows(
    records: list[dict[str, Any]],
    *,
    client: DeepOriginClient,
    execution_id: str | None,
) -> list[dict[str, Any]]:
    """Convert result-explorer pose records to ``LigandSet.from_json`` rows."""
    job_ids: set[str] = set()
    if execution_id:
        job_ids.add(str(execution_id))
    for rec in records:
        jid = rec.get("compute_job_id")
        if jid:
            job_ids.add(str(jid))

    smiles_by_job: dict[str, dict[str, str]] = {}
    for jid in job_ids:
        try:
            dto = client.executions.get(jid)  # ty:ignore[unresolved-attribute]
        except Exception:
            smiles_by_job[jid] = {}
        else:
            smiles_by_job[jid] = _ligand_smiles_map_from_tool_payload(dto)

    rows: list[dict[str, Any]] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        data = rec.get("data")
        if not isinstance(data, dict):
            data = {}
        row = dict(data)
        _normalize_pose_row_smiles(row)
        jid = str(rec.get("compute_job_id") or execution_id or "")
        smi_map = smiles_by_job.get(jid, {})
        lid = row.get("ligand_id")
        if (
            not (isinstance(row.get("smiles"), str) and row["smiles"].strip())
            and not (
                isinstance(row.get("canonical_smiles"), str)
                and row["canonical_smiles"].strip()
            )
            and lid is not None
        ):
            sm = smi_map.get(str(lid))
            if sm:
                row["smiles"] = sm
        rid = rec.get("id")
        if rid is not None:
            row["id"] = str(rid)
        rows.append(row)
    return rows


def load_scored_poses_from_result_explorer(
    execution_id: str | None,
    *,
    client: DeepOriginClient,
    protein_id: str | None = None,
    best_pose: bool | None = None,
) -> LigandSet:
    """Load scored docking poses from result-explorer rows for one execution.

    Skips constrained-docking ``reference_pose`` metadata rows, which share the
    Pose catalog but lack ``pose_score`` / ``best_pose`` fields.

    Args:
        execution_id: Platform execution / compute job id.
        client: API client.
        protein_id: Optional protein id filter.
        best_pose: When set, restrict to rows whose ``data.best_pose`` matches.

    Returns:
        A ``LigandSet`` of docked poses.

    Raises:
        ValueError: If no scored pose rows match.
    """
    get_poses_kwargs: dict[str, Any] = dict(
        protein_id=protein_id,
        compute_job_id=execution_id,
        limit=None,
    )
    if best_pose is not None:
        get_poses_kwargs["best_pose"] = best_pose

    response = client.results.get_poses(**get_poses_kwargs)
    raw_records = [rec for rec in response.get("data", []) if isinstance(rec, dict)]
    records = [
        rec for rec in raw_records if _is_scored_docking_pose_data(rec.get("data"))
    ]

    if not records:
        raise ValueError(
            "No scored docking pose results found for "
            f"protein_id={protein_id!r} execution_id={execution_id!r} "
            f"({len(raw_records)} raw result-explorer row(s); "
            f"{len(raw_records) - len(records)} looked like reference/metadata only)."
        )

    rows = _pose_result_records_to_rows(
        records,
        client=client,
        execution_id=execution_id,
    )
    return LigandSet.from_json(rows, client=client)


def load_docking_poses_from_execution(
    exec_id: str,
    *,
    client: DeepOriginClient,
    dto: dict[str, Any] | None = None,
    all_poses: bool = False,
) -> LigandSet:
    """Load docked poses from the data platform or execution ``jobOutputs``.

    Async workflow executions usually persist poses only in result-explorer, not
    in ``jobOutputs.poses``.

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
    errors: list[str] = []

    try:
        poses = load_scored_poses_from_result_explorer(
            exec_id,
            client=client,
            best_pose=best_pose,
        )
        if len(poses) > 0:
            return poses
        errors.append("result-explorer returned zero scored pose rows")
    except Exception as exc:
        errors.append(f"result-explorer: {exc}")

    try:
        if dto is None:
            dto = client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
        jo = dto.get("jobOutputs")
        raw = jo.get("poses", []) if isinstance(jo, dict) else []
        if not raw:
            errors.append("jobOutputs.poses is empty")
            raise ValueError("jobOutputs.poses is empty")
        rows = [dict(item) for item in raw if isinstance(item, dict)]
        for row in rows:
            _normalize_pose_row_smiles(row)
        poses = LigandSet.from_json(rows, client=client)
        if len(poses) == 0:
            errors.append("jobOutputs.poses parsed to an empty LigandSet")
            raise ValueError("jobOutputs.poses parsed to an empty LigandSet")
        return poses
    except Exception as exc:
        if str(exc) not in errors:
            errors.append(f"jobOutputs: {exc}")

    detail = "; ".join(errors)
    raise DeepOriginException(
        title="Could not load docking poses",
        message=(
            f"No poses could be loaded for execution {exec_id!r}. {detail}. "
            "Async constrained docking stores poses in result-explorer only; "
            "confirm this id matches compute_job_id on the platform debug page."
        ),
    ) from None


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
