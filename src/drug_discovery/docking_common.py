"""Shared helpers for docking-family tool execution classes."""

from __future__ import annotations

import math
import os
from typing import Any, Callable

import numpy as np

from deeporigin.drug_discovery.structures.ligand import (
    Ligand,
    LigandSet,
    _is_scored_docking_pose_data,
    _ligand_smiles_map_from_tool_payload,
)
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.structures.pose import Pose, PoseSet
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


def _pose_label_for_viewer(item: Ligand | Pose, index: int) -> str:
    """Pick a LigandManager label: name → SMILES → ligand-{i}."""
    name = getattr(item, "name", None)
    if name and name not in ("", "Unknown_Ligand"):
        return str(name)
    smiles = getattr(item, "smiles", None) or getattr(item, "canonical_smiles", None)
    if smiles:
        return str(smiles)
    return f"ligand-{index}"


def normalize_pose_ligands(
    poses: Ligand | LigandSet | Pose | PoseSet | list[Ligand] | list[Pose],
) -> list[Ligand]:
    """Normalize a poses argument into a flat list of ``Ligand`` objects.

    :class:`Pose` / :class:`PoseSet` values are converted via
    :meth:`Pose.to_ligand` for molstar overlays.

    Args:
        poses: A single ligand/pose, set, or list.

    Returns:
        Flat list of ligands.

    Raises:
        ValueError: If ``poses`` is empty after normalization.
    """
    if isinstance(poses, Pose):
        pose_ligands = [poses.to_ligand()]
    elif isinstance(poses, PoseSet):
        pose_ligands = list(poses.to_ligand_set().ligands)
    elif isinstance(poses, Ligand):
        pose_ligands = [poses]
    elif isinstance(poses, LigandSet):
        pose_ligands = list(poses.ligands)
    else:
        pose_ligands = []
        for item in poses:
            if isinstance(item, Pose):
                pose_ligands.append(item.to_ligand())
            else:
                pose_ligands.append(item)
    if not pose_ligands:
        raise ValueError("poses must be non-empty")
    return pose_ligands


def ligand_payloads_for_viewer(
    poses: Ligand | LigandSet | Pose | PoseSet | list[Ligand] | list[Pose],
) -> list[dict[str, object]]:
    """Build per-ligand molstarLib payloads for docking visualizations.

    Args:
        poses: A single ligand/pose, set, or list.

    Returns:
        List of dicts suitable for ``render_protein_with_poses_html`` and
        ``render_protein_with_box_and_poses_html``.
    """
    from deeporigin.viz.molstar_html import ligand_data_for_js

    pose_ligands = normalize_pose_ligands(poses)
    return [
        ligand_data_for_js(
            path=item.to_sdf(),
            label=_pose_label_for_viewer(item, index),
        )
        for index, item in enumerate(pose_ligands)
    ]


def normalize_rotation_deg(value: object) -> list[float] | None:
    """Normalize a rotation payload to ``[rx, ry, rz]`` or ``None`` for identity.

    Args:
        value: ``None``, a length-3 sequence of numbers, or a dict with ``x``/``y``/``z``.

    Returns:
        A length-3 list of finite floats, or ``None`` when absent or all zeros.

    Raises:
        ValueError: If ``value`` is present but not a valid rotation triple.
    """
    if value is None:
        return None
    try:
        if isinstance(value, dict):
            rotation = [
                float(value.get("x", value.get("0", 0))),
                float(value.get("y", value.get("1", 0))),
                float(value.get("z", value.get("2", 0))),
            ]
        else:
            rotation = [float(component) for component in value]  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"rotation_deg must be a length-3 sequence of numbers, got {value!r}"
        ) from exc
    if len(rotation) != 3:
        raise ValueError(
            f"rotation_deg must have length 3, got {len(rotation)} value(s)"
        )
    if not all(math.isfinite(angle) for angle in rotation):
        raise ValueError(
            f"rotation_deg values must be finite numbers, got {rotation!r}"
        )
    if all(abs(angle) < 1e-9 for angle in rotation):
        return None
    return rotation


def parse_docking_box_commit(
    payload: dict[str, Any],
) -> tuple[list[float], list[float], list[float]]:
    """Parse a docking-box commit payload from the interactive viewer.

    Args:
        payload: Dict with ``center``, ``box_size``, and ``rotation_deg`` keys.

    Returns:
        Tuple of (center, box_size, rotation_deg) where ``rotation_deg`` is always
        a length-3 list (zeros when no rotation was applied).

    Raises:
        ValueError: If required geometry fields are missing or invalid.
    """
    center = payload.get("center")
    box_size = payload.get("box_size")
    if not isinstance(center, list) or len(center) != 3:
        raise ValueError(f"commit payload center must be length 3, got {center!r}")
    if not isinstance(box_size, list) or len(box_size) != 3:
        raise ValueError(f"commit payload box_size must be length 3, got {box_size!r}")
    if not all(math.isfinite(float(value)) for value in (*center, *box_size)):
        raise ValueError(
            f"commit payload center and box_size must be finite numbers, got {payload!r}"
        )
    if any(float(size) <= 0 for size in box_size):
        raise ValueError(
            f"commit payload box_size extents must be positive, got {box_size!r}"
        )

    normalized = normalize_rotation_deg(payload.get("rotation_deg"))
    rotation_deg = normalized if normalized is not None else [0.0, 0.0, 0.0]
    return (
        [float(value) for value in center],
        [float(value) for value in box_size],
        rotation_deg,
    )


def build_pocket_tool_params(
    pocket: Pocket,
    pocket_center: list[float],
    box_size: list[float],
    *,
    rotation_deg: list[float] | None = None,
) -> dict[str, Any]:
    """Build pocket dict for docking tool ``inputs``."""
    pocket_params: dict[str, Any] = {
        "box_size_x": box_size[0],
        "box_size_y": box_size[1],
        "box_size_z": box_size[2],
        "center": pocket_center,
    }
    normalized_rotation = normalize_rotation_deg(rotation_deg)
    if normalized_rotation is not None:
        pocket_params["rotation_deg"] = normalized_rotation
    if pocket.id is not None:
        pocket_params["id"] = pocket.id
    return pocket_params


def show_docking_box_in_notebook(
    *,
    protein: Protein,
    pocket: Pocket,
    client: DeepOriginClient | None,
    interactive: bool,
    on_commit: Callable[[dict[str, Any]], None] | None,
    rotation_deg: list[float] | None = None,
    poses: Ligand | LigandSet | list[Ligand] | None = None,
    height: int = 620,
):
    """Render a protein + docking search box in a Jupyter or marimo notebook.

    Args:
        protein: Target protein (structure downloaded locally when needed).
        pocket: Binding pocket defining the search box geometry.
        client: Optional API client for protein download.
        interactive: When ``True``, show molstar rotation controls with an Apply
            button that commits box orientation back to Python via AnyWidget.
        on_commit: Called with the committed payload when ``interactive=True``.
        rotation_deg: Optional committed box rotation for static rendering.
        poses: Optional docked pose(s) to overlay with the search box.
        height: Viewer iframe height in pixels.

    Returns:
        Static mode: result of :func:`~deeporigin.utils.notebook.render_html`.
        Interactive mode: :class:`~deeporigin.utils.iframe_comm_bridge.IframeCommHandle`.

    Raises:
        DeepOriginException: If the protein structure cannot be loaded locally.
        RuntimeError: If ``interactive=True`` outside Jupyter.
        ValueError: If ``poses`` is empty or interactive mode lacks ``on_commit``.
    """
    if protein.structure is None:
        protein.download(client=client)
    if protein.structure is None:
        raise DeepOriginException(
            title="Cannot visualize docking box",
            message=(
                "Protein structure is not available locally. Download the "
                "protein or call protein.load_structure_from_local() first."
            ),
        ) from None

    from deeporigin.utils.notebook import get_notebook_environment, render_html
    from deeporigin.viz.molstar_html import (
        render_docking_box_html,
        render_interactive_docking_box_html,
        render_protein_with_box_and_poses_html,
    )

    protein_file = protein._dump_state()
    pocket_center, box_size = resolve_docking_box_geometry(pocket)

    if interactive:
        if get_notebook_environment() != "jupyter":
            raise RuntimeError(
                "Interactive box adjustment requires Jupyter "
                "(JupyterLab or VS Code notebook)."
            )
        if on_commit is None:
            raise ValueError("on_commit is required when interactive=True")

        from deeporigin.utils.iframe_comm_bridge import (
            render_interactive_html_with_comm,
        )

        return render_interactive_html_with_comm(
            lambda bridge_id: render_interactive_docking_box_html(
                pdb_path=protein_file,
                box_center=list(pocket_center),
                box_size=list(box_size),
                bridge_id=bridge_id,
            ),
            on_commit=on_commit,
            height=height,
        )

    if poses is None:
        return render_html(
            render_docking_box_html(
                pdb_path=protein_file,
                box_center=list(pocket_center),
                box_size=list(box_size),
                rotation_deg=rotation_deg,
            ),
            height=height,
        )

    return render_html(
        render_protein_with_box_and_poses_html(
            pdb_path=protein_file,
            box_center=list(pocket_center),
            box_size=list(box_size),
            ligand_payloads=ligand_payloads_for_viewer(poses),
            rotation_deg=rotation_deg,
        ),
        height=height,
    )


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


def _collect_pose_job_ids(
    records: list[dict[str, Any]],
    execution_id: str | None,
) -> set[str]:
    """Collect compute job ids referenced by result-explorer pose records."""
    job_ids: set[str] = set()
    if execution_id:
        job_ids.add(str(execution_id))
    for rec in records:
        jid = rec.get("compute_job_id")
        if jid:
            job_ids.add(str(jid))
    return job_ids


def _load_smiles_by_job(
    client: DeepOriginClient,
    job_ids: set[str],
) -> dict[str, dict[str, str]]:
    """Load ligand-id to SMILES maps for each compute job id."""
    smiles_by_job: dict[str, dict[str, str]] = {}
    for jid in job_ids:
        try:
            dto = client.executions.get(jid)  # ty:ignore[unresolved-attribute]
        except Exception:
            smiles_by_job[jid] = {}
        else:
            smiles_by_job[jid] = _ligand_smiles_map_from_tool_payload(dto)
    return smiles_by_job


def _row_has_smiles(row: dict[str, Any]) -> bool:
    """Return True when the row already has a usable SMILES field."""
    smiles = row.get("smiles")
    if isinstance(smiles, str) and smiles.strip():
        return True
    canonical = row.get("canonical_smiles")
    return isinstance(canonical, str) and bool(canonical.strip())


def _apply_execution_smiles_fallback(
    row: dict[str, Any],
    *,
    smiles_by_job: dict[str, dict[str, str]],
    job_id: str,
) -> None:
    """Backfill ``row['smiles']`` from execution userInputs when missing."""
    if _row_has_smiles(row):
        return
    ligand_id = row.get("ligand_id")
    if ligand_id is None:
        return
    smi = smiles_by_job.get(job_id, {}).get(str(ligand_id))
    if smi:
        row["smiles"] = smi


def _pose_record_to_row(
    rec: dict[str, Any],
    *,
    smiles_by_job: dict[str, dict[str, str]],
    execution_id: str | None,
) -> dict[str, Any]:
    """Convert one result-explorer pose record to a PoseSet.from_json row."""
    data = rec.get("data")
    if not isinstance(data, dict):
        data = {}
    row = dict(data)
    _normalize_pose_row_smiles(row)
    job_id = str(rec.get("compute_job_id") or execution_id or "")
    _apply_execution_smiles_fallback(
        row,
        smiles_by_job=smiles_by_job,
        job_id=job_id,
    )
    result_id = rec.get("id")
    if result_id is not None:
        row["id"] = str(result_id)
    return row


def _pose_result_records_to_rows(
    records: list[dict[str, Any]],
    *,
    client: DeepOriginClient,
    execution_id: str | None,
) -> list[dict[str, Any]]:
    """Convert result-explorer pose records to PoseSet.from_json rows."""
    job_ids = _collect_pose_job_ids(records, execution_id)
    smiles_by_job = _load_smiles_by_job(client, job_ids)
    rows: list[dict[str, Any]] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        rows.append(
            _pose_record_to_row(
                rec,
                smiles_by_job=smiles_by_job,
                execution_id=execution_id,
            )
        )
    return rows


def load_poses_from_result_explorer(
    execution_id: str | None,
    *,
    client: DeepOriginClient,
    protein_id: str | None = None,
    ligand_id: str | list[str] | None = None,
    best_pose: bool | None = None,
    scored_only: bool = False,
) -> PoseSet:
    """Load pose rows from result-explorer into a :class:`PoseSet`.

    Args:
        execution_id: Platform execution / compute job id filter.
        client: API client.
        protein_id: Optional protein id filter.
        ligand_id: Optional ligand id filter (single id or list).
        best_pose: When set, restrict to rows whose ``data.best_pose`` matches.
        scored_only: When ``True``, skip reference/metadata rows that lack
            ``pose_score`` / ``best_pose`` (constrained-docking reference rows).

    Returns:
        A :class:`PoseSet` of matching poses.

    Raises:
        ValueError: If no pose rows match.
    """
    get_poses_kwargs: dict[str, Any] = {
        "protein_id": protein_id,
        "ligand_id": ligand_id,
        "compute_job_id": execution_id,
        "limit": None,
    }
    if best_pose is not None:
        get_poses_kwargs["best_pose"] = best_pose

    response = client.results.get_poses(**get_poses_kwargs)
    raw_records = [rec for rec in response.get("data", []) if isinstance(rec, dict)]
    records = raw_records
    if scored_only:
        records = [
            rec for rec in raw_records if _is_scored_docking_pose_data(rec.get("data"))
        ]

    if not records:
        detail = (
            f"({len(raw_records)} raw result-explorer row(s); "
            f"{len(raw_records) - len(records)} excluded by scored_only filter)."
            if scored_only
            else f"({len(raw_records)} raw result-explorer row(s))."
        )
        raise ValueError(
            "No pose results found for "
            f"protein_id={protein_id!r} execution_id={execution_id!r} "
            f"ligand_id={ligand_id!r} {detail}"
        )

    rows = _pose_result_records_to_rows(
        records,
        client=client,
        execution_id=execution_id,
    )
    return PoseSet.from_json(rows, client=client)


def load_scored_poses_from_result_explorer(
    execution_id: str | None,
    *,
    client: DeepOriginClient,
    protein_id: str | None = None,
    best_pose: bool | None = None,
) -> PoseSet:
    """Load scored docking poses from result-explorer rows for one execution.

    Skips constrained-docking ``reference_pose`` metadata rows, which share the
    Pose catalog but lack ``pose_score`` / ``best_pose`` fields.

    Args:
        execution_id: Platform execution / compute job id.
        client: API client.
        protein_id: Optional protein id filter.
        best_pose: When set, restrict to rows whose ``data.best_pose`` matches.

    Returns:
        A :class:`PoseSet` of docked poses.

    Raises:
        ValueError: If no scored pose rows match.
    """
    return load_poses_from_result_explorer(
        execution_id,
        client=client,
        protein_id=protein_id,
        best_pose=best_pose,
        scored_only=True,
    )


def load_docking_poses_from_execution(
    exec_id: str,
    *,
    client: DeepOriginClient,
    dto: dict[str, Any] | None = None,
    all_poses: bool = False,
) -> PoseSet:
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
        A :class:`PoseSet` of docked poses.

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
        poses = PoseSet.from_json(rows, client=client)
        if len(poses) == 0:
            errors.append("jobOutputs.poses parsed to an empty PoseSet")
            raise ValueError("jobOutputs.poses parsed to an empty PoseSet")
        return poses
    except Exception as exc:
        if str(exc) not in errors:
            errors.append(f"jobOutputs: {exc}")

    detail = "; ".join(errors)
    raise DeepOriginException(
        title="Could not load docking poses",
        message=(
            f"No poses could be loaded for execution {exec_id!r}. {detail}. "
            "Async executions often store poses in result-explorer only; "
            "confirm this id matches compute_job_id on the platform debug page."
        ),
    ) from None


def _enrich_reference_pose_row(
    row: dict[str, Any],
    *,
    dto: dict[str, Any],
) -> dict[str, Any]:
    """Ensure ``reference_pose`` jobOutputs rows include SMILES for remote loading."""
    enriched = dict(row)
    _normalize_pose_row_smiles(enriched)
    if isinstance(enriched.get("smiles"), str) and enriched["smiles"].strip():
        return enriched
    canonical = enriched.get("canonical_smiles")
    if isinstance(canonical, str) and canonical.strip():
        return enriched

    params = dto.get("userInputs") or dto.get("inputs") or {}
    reference = params.get("reference") if isinstance(params, dict) else {}
    ref_ligand = reference.get("ligand") if isinstance(reference, dict) else {}
    ref_smiles = ref_ligand.get("smiles") if isinstance(ref_ligand, dict) else None
    if isinstance(ref_smiles, str) and ref_smiles.strip():
        enriched["smiles"] = ref_smiles.strip()
        return enriched

    ligand_id = enriched.get("ligand_id")
    if ligand_id is not None:
        smi = _ligand_smiles_map_from_tool_payload(dto).get(str(ligand_id))
        if smi:
            enriched["smiles"] = smi
    return enriched


def load_reference_pose_from_execution(
    exec_id: str,
    *,
    client: DeepOriginClient,
    dto: dict[str, Any] | None = None,
) -> Pose:
    """Load the reference pose from a constrained docking execution.

    Args:
        exec_id: Platform execution ID.
        client: API client.
        dto: Optional execution payload to avoid an extra GET.

    Returns:
        The reference pose as a :class:`Pose`.

    Raises:
        DeepOriginException: If no reference pose could be loaded.
    """
    if dto is None:
        dto = client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
    jo = dto.get("jobOutputs")
    if isinstance(jo, dict):
        raw = jo.get("reference_pose")
        if isinstance(raw, dict):
            row = _enrich_reference_pose_row(raw, dto=dto)
            return Pose.from_json([row], client=client)[0]

    raise DeepOriginException(
        title="Could not load reference pose",
        message=(
            "No reference_pose could be parsed from jobOutputs for this execution."
        ),
    )
