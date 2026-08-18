"""Tools-related routes for the mock server.

Covers ``/tools/...`` endpoints: tool definitions, clusters, and tool
executions (list / get / cancel / confirm / run).  All runnable work goes
through ``POST /tools/{org}/tools/{tool_key}/{tool_version}/executions``;
there is no longer a legacy ``/functions`` route.
"""

from __future__ import annotations

from collections.abc import Callable
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random
import string
from typing import Any
import uuid

from fastapi import APIRouter, HTTPException, Request

from ..constants import MOCK_BULK_DOCKING_EXECUTION_ID

RBFE_TEMPLATE_EXECUTION_ID = "a5484958-059f-4b1b-ba2c-664adf23e8e8"
RBFE_NOHUP_FIXTURE_PATH = (
    Path("files")
    / "tool-runs"
    / RBFE_TEMPLATE_EXECUTION_ID
    / "workflow-mock"
    / "binding_nohup.out"
)

# Top-level workflow stage windows (fraction of mock execution duration).
_RBFE_STAGE_PREPARE = (0.00, 0.12)
_RBFE_STAGE_KONNEKTOR = (0.12, 0.20)
_RBFE_STAGE_BUILD_PAIRS = (0.20, 0.28)
_RBFE_STAGE_PAIR_PIPELINE = (0.28, 1.00)


def _rbfe_ts(start_dt: datetime, duration_s: float, fraction: float) -> str:
    """Return an ISO-8601 UTC timestamp at *fraction* of the mock run."""
    when = start_dt + timedelta(seconds=duration_s * fraction)
    return when.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _rbfe_pair_count(user_inputs: dict[str, Any], steps: list[str]) -> int:
    """Return the number of pair-pipeline branches for this RBFE request."""
    if "konnektor" in steps:
        ligands = user_inputs.get("ligands") or []
        return max(1, len(ligands) - 1) if len(ligands) > 1 else 1
    if "system-prep" in steps:
        pairs = user_inputs.get("pairs") or []
        return max(1, len(pairs))
    prepared = user_inputs.get("prepared_systems") or []
    return max(1, len(prepared))


def _rbfe_pair_sub_windows(
    *, run_system_prep: bool, run_rbfe: bool
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    """Return (system_prep, resolve, rbfe_e2e) windows within the pair-pipeline span."""
    if run_system_prep:
        return (0.28, 0.45), (0.45, 0.55), (0.55, 1.00)
    # Skipped system-prep: resolve starts immediately after pair-pipeline begins.
    return (0.28, 0.28), (0.28, 0.40), (0.40, 1.00)


def _rbfe_stage_status(
    fraction: float,
    start: float,
    end: float,
    *,
    skipped: bool = False,
) -> str | None:
    """Map elapsed fraction to a node status, or ``None`` before the pop-up time."""
    if fraction < start:
        return None
    if skipped:
        return "Skipped"
    if fraction >= end:
        return "Succeeded"
    return "Running"


def _rbfe_leaf_node(
    *,
    node_id: str,
    display_name: str,
    fraction: float,
    start: float,
    end: float,
    start_dt: datetime,
    duration_s: float,
    skipped: bool = False,
    tool_complete: int | None = None,
) -> dict[str, Any]:
    """Build one v2 progress-tree leaf node."""
    status = _rbfe_stage_status(fraction, start, end, skipped=skipped)
    if status is None:
        raise ValueError("leaf node requested before pop-up time")

    node: dict[str, Any] = {
        "id": node_id,
        "displayName": display_name,
        "status": status,
        "message": None,
        "progress": "1/1" if status == "Succeeded" else "0/1",
        "startedAt": _rbfe_ts(start_dt, duration_s, start),
    }
    if status in ("Succeeded", "Skipped"):
        node["finishedAt"] = _rbfe_ts(
            start_dt, duration_s, end if not skipped else start
        )
    else:
        node["finishedAt"] = None

    if tool_complete is not None:
        node["toolProgress"] = {"complete": tool_complete}

    if skipped and status == "Skipped":
        node["message"] = "when 'false == true' evaluated false"

    return node


def build_rbfe_progress_tree(
    *,
    execution_id: str,
    user_inputs: dict[str, Any],
    start_dt: datetime,
    duration_s: float,
    fraction: float,
) -> dict[str, Any]:
    """Build a synthetic v2 RBFE workflow progress tree for the mock server.

    Stages mirror ``platform-toolbox/tools/rbfe/workflow/workflow.yaml``. Children
    pop up as ``fraction`` advances. The RBFE simulation leaf exposes ramping
    ``toolProgress.complete`` (0–100), not the legacy top-level ``complete`` key.

    Args:
        execution_id: Tools execution UUID.
        user_inputs: RBFE ``userInputs`` from the execution DTO.
        start_dt: Mock run start time (confirm time).
        duration_s: Mock RBFE duration in seconds.
        fraction: Elapsed fraction in ``[0, 1]``.

    Returns:
        Root ``ExecutionProgressNode`` dict suitable for ``progressReport``.
    """
    frac = max(0.0, min(1.0, fraction))
    steps_raw = user_inputs.get("steps") or ["rbfe"]
    steps = list(steps_raw) if isinstance(steps_raw, list) else ["rbfe"]
    run_konnektor = "konnektor" in steps
    run_system_prep = "system-prep" in steps
    run_rbfe = "rbfe" in steps
    n_pairs = _rbfe_pair_count(user_inputs, steps)

    wf_suffix = execution_id.replace("-", "")[:12]
    root_id = f"workflow-{wf_suffix}"
    seq = 0

    def _next_id() -> str:
        nonlocal seq
        seq += 1
        return f"{root_id}-{seq}"

    children: list[dict[str, Any]] = []

    prep_start, prep_end = _RBFE_STAGE_PREPARE
    if frac >= prep_start:
        children.append(
            _rbfe_leaf_node(
                node_id=_next_id(),
                display_name="prepare-inputs",
                fraction=frac,
                start=prep_start,
                end=prep_end,
                start_dt=start_dt,
                duration_s=duration_s,
            )
        )

    konn_start, konn_end = _RBFE_STAGE_KONNEKTOR
    if frac >= konn_start:
        children.append(
            _rbfe_leaf_node(
                node_id=_next_id(),
                display_name="run-konnektor",
                fraction=frac,
                start=konn_start,
                end=konn_end,
                start_dt=start_dt,
                duration_s=duration_s,
                skipped=not run_konnektor,
            )
        )

    build_start, build_end = _RBFE_STAGE_BUILD_PAIRS
    if frac >= build_start:
        children.append(
            _rbfe_leaf_node(
                node_id=_next_id(),
                display_name="build-pair-list",
                fraction=frac,
                start=build_start,
                end=build_end,
                start_dt=start_dt,
                duration_s=duration_s,
            )
        )

    pair_start, pair_end = _RBFE_STAGE_PAIR_PIPELINE
    sp_win, resolve_win, rbfe_win = _rbfe_pair_sub_windows(
        run_system_prep=run_system_prep,
        run_rbfe=run_rbfe,
    )

    prepared_list = user_inputs.get("prepared_systems") or []
    if frac >= pair_start:
        for pair_idx in range(n_pairs):
            ps_json: dict[str, Any] = {}
            if isinstance(prepared_list, list) and pair_idx < len(prepared_list):
                item = prepared_list[pair_idx]
                if isinstance(item, dict):
                    ps_json = item
            pair_display = (
                f"pair-pipeline(0:index:{pair_idx},ligand1:{{}},ligand2:{{}},"
                f"prepared_system:{json.dumps(ps_json, separators=(',', ':'))})"
            )
            pair_children: list[dict[str, Any]] = []

            sp_start, sp_end = sp_win
            if run_system_prep or frac >= sp_start:
                sp_status = _rbfe_stage_status(
                    frac, sp_start, sp_end, skipped=not run_system_prep
                )
                if sp_status is not None:
                    pair_children.append(
                        _rbfe_leaf_node(
                            node_id=_next_id(),
                            display_name="system-prep-task",
                            fraction=frac,
                            start=sp_start,
                            end=sp_end,
                            start_dt=start_dt,
                            duration_s=duration_s,
                            skipped=not run_system_prep,
                        )
                    )

            res_start, res_end = resolve_win
            if run_rbfe:
                res_status = _rbfe_stage_status(frac, res_start, res_end)
                if res_status is not None:
                    pair_children.append(
                        _rbfe_leaf_node(
                            node_id=_next_id(),
                            display_name="resolve-prepared-system",
                            fraction=frac,
                            start=res_start,
                            end=res_end,
                            start_dt=start_dt,
                            duration_s=duration_s,
                        )
                    )

            rbfe_start, rbfe_end = rbfe_win
            if run_rbfe:
                rbfe_status = _rbfe_stage_status(frac, rbfe_start, rbfe_end)
                if rbfe_status is not None:
                    if rbfe_status == "Succeeded":
                        complete_val = 100
                    elif rbfe_status == "Running":
                        span = rbfe_end - rbfe_start
                        complete_val = (
                            int(min(99.0, ((frac - rbfe_start) / span) * 100.0))
                            if span > 0
                            else 0
                        )
                    else:
                        complete_val = 0
                    pair_children.append(
                        _rbfe_leaf_node(
                            node_id=_next_id(),
                            display_name="rbfe-e2e-task",
                            fraction=frac,
                            start=rbfe_start,
                            end=rbfe_end,
                            start_dt=start_dt,
                            duration_s=duration_s,
                            tool_complete=complete_val,
                        )
                    )

            pair_status = "Succeeded" if frac >= pair_end else "Running"
            if frac < pair_start:
                pair_status = "Pending"
            pair_node: dict[str, Any] = {
                "id": _next_id(),
                "displayName": pair_display,
                "status": pair_status,
                "message": None,
                "progress": "1/1" if pair_status == "Succeeded" else "0/1",
                "startedAt": _rbfe_ts(start_dt, duration_s, pair_start),
                "finishedAt": _rbfe_ts(start_dt, duration_s, pair_end)
                if pair_status == "Succeeded"
                else None,
                "children": pair_children,
            }
            children.append(pair_node)

    root_status = "Succeeded" if frac >= 1.0 else "Running"
    completed_top = sum(
        1
        for stage_end in (prep_end, konn_end, build_end, pair_end)
        if frac >= stage_end
    )
    return {
        "id": root_id,
        "displayName": root_id,
        "status": root_status,
        "message": None,
        "progress": f"{completed_top}/3",
        "startedAt": _rbfe_ts(start_dt, duration_s, 0.0),
        "finishedAt": _rbfe_ts(start_dt, duration_s, 1.0) if frac >= 1.0 else None,
        "children": children,
    }


def _find_progress_nodes(
    node: dict[str, Any], *, display_prefix: str
) -> list[dict[str, Any]]:
    """Collect nodes whose ``displayName`` equals or starts with *display_prefix*."""
    found: list[dict[str, Any]] = []
    name = node.get("displayName")
    if isinstance(name, str) and (
        name == display_prefix or name.startswith(f"{display_prefix}(")
    ):
        found.append(node)
    for child in node.get("children") or []:
        if isinstance(child, dict):
            found.extend(_find_progress_nodes(child, display_prefix=display_prefix))
    return found


def _generate_resource_id() -> str:
    """Generate a random resource ID.

    Returns:
        A random 20-character alphanumeric string.
    """
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choice(chars) for _ in range(20))


def _replace_ids_in_outputs(
    obj: object, protein_id: str | None = None, ligand_id: str | None = None
) -> object:
    """Recursively replace protein/ligand ID values in tool ``jobOutputs``.

    Handles both ``ligand_id`` and ``ligand1_id`` keys so that the same fixture
    works for both the legacy and the current sysprep schemas.

    Args:
        obj: The object to traverse (dict, list, or scalar).
        protein_id: The protein ID to use for replacement (optional).
        ligand_id: The ligand ID to use for replacement (optional).

    Returns:
        A copy of obj with protein_id and ligand_id values replaced.
    """
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if key == "protein_id" and protein_id is not None:
                result[key] = protein_id
            elif key in ("ligand_id", "ligand1_id") and ligand_id is not None:
                result[key] = ligand_id
            else:
                result[key] = _replace_ids_in_outputs(
                    value, protein_id=protein_id, ligand_id=ligand_id
                )
        return result
    elif isinstance(obj, list):
        return [
            _replace_ids_in_outputs(item, protein_id=protein_id, ligand_id=ligand_id)
            for item in obj
        ]
    return obj


def _normalize_execution(execution: dict[str, Any]) -> dict[str, Any]:
    """Normalize an execution to ensure all required fields are present.

    Args:
        execution: The execution dictionary to normalize.

    Returns:
        A normalized execution dictionary with all required fields.
    """
    normalized = execution.copy()
    for field in ("startedAt", "completedAt", "billingTransaction", "quotationResult"):
        if field not in normalized:
            normalized[field] = None
    return normalized


def _legacy_outputs_to_job_outputs(legacy: dict[str, Any]) -> Any:
    """Pull ``jobOutputs`` from a fixture, falling back to legacy ``functionOutputs``.

    Older fixtures are still recorded with the ``functionOutputs`` key from
    when tool executions were called function runs.  This helper hides that
    detail so the rest of the mock server only deals with ``jobOutputs``.
    """
    if "jobOutputs" in legacy:
        return legacy["jobOutputs"]
    return legacy.get("functionOutputs")


def _legacy_quotation(legacy: dict[str, Any]) -> dict[str, Any] | None:
    """Return ``quotationResult`` from a recorded fixture if present."""
    quotation = legacy.get("quotationResult")
    return quotation if isinstance(quotation, dict) else None


def _stable_unit_float(seed: str, suffix: str) -> float:
    """Deterministic float in ``[0.0, 1.0)`` derived from ``(seed, suffix)``.

    Used by the combined-molprops mock to synthesize stable per-ligand values
    keyed by SMILES so the same request always returns the same numbers.
    """
    digest = hashlib.md5(f"{seed}|{suffix}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0x1_0000_0000


def _stable_log_value(seed: str, suffix: str, *, low: float, high: float) -> float:
    """Deterministic float in ``[low, high)`` derived from ``(seed, suffix)``."""
    return round(low + _stable_unit_float(seed, suffix) * (high - low), 6)


def _konnektor_ligand_display_name(ligand: dict[str, Any], index: int) -> str:
    """Stable component name aligned with rbfe-tools ``ligand_resolve``."""
    ligand_id = str(ligand.get("id") or "").strip()
    if ligand_id:
        return ligand_id
    file_path = str(ligand.get("file_path") or "").strip()
    if file_path:
        stem = Path(file_path).stem.strip()
        if stem:
            return stem
    return f"ligand_{index + 1}"


def _konnektor_edges(
    names: list[str],
    *,
    network_type: str,
) -> list[dict[str, str]]:
    """Build mock Konnektor edges for ``names`` (order matches input ligands)."""
    if len(names) < 2:
        return []
    if network_type == "star":
        hub = names[0]
        return [{"source": hub, "target": target} for target in names[1:]]
    if network_type == "cyclic":
        return [
            {"source": names[i], "target": names[(i + 1) % len(names)]}
            for i in range(len(names))
        ]
    return [{"source": names[i], "target": names[i + 1]} for i in range(len(names) - 1)]


def _synthesize_molprops_row(
    *, smiles: str, ligand_id: str, requested: list[str]
) -> dict[str, Any]:
    """Build a synthetic combined-molprops output row for one ligand.

    Includes only the output keys for properties named in ``requested`` (see
    the combined tool's input schema for valid property keys: ``ames``,
    ``cyp``, ``herg``, ``logd``, ``logp``, ``logs``, ``pains``).
    """
    row: dict[str, Any] = {"ligand_id": ligand_id}
    seed = smiles or ligand_id
    if "ames" in requested:
        row["ames_probability"] = round(_stable_unit_float(seed, "ames"), 6)
    if "herg" in requested:
        row["herg_inhibition_probability"] = round(_stable_unit_float(seed, "herg"), 6)
    if "cyp" in requested:
        for iso in ("cyp1a2", "cyp2c9", "cyp2c19", "cyp2d6", "cyp3a4"):
            row[iso] = round(_stable_unit_float(seed, iso), 6)
    if "logd" in requested:
        row["logD"] = _stable_log_value(seed, "logd", low=-2.0, high=6.0)
    if "logp" in requested:
        row["logP"] = _stable_log_value(seed, "logp", low=-2.0, high=6.0)
    if "logs" in requested:
        row["logS"] = _stable_log_value(seed, "logs", low=-6.0, high=0.0)
    if "pains" in requested:
        row["has_pains"] = False
        row["pains_fragments"] = []
    return row


def _synthesize_admet_prediction_row(
    *, smiles: str, ligand_id: str, requested: list[str]
) -> dict[str, Any]:
    """Build a synthetic admet-properties prediction row for one ligand."""

    row: dict[str, Any] = {"smiles": smiles, "ligand_id": ligand_id}
    seed = smiles or ligand_id
    for prop in requested:
        if prop.endswith("_classification"):
            row[prop] = round(_stable_unit_float(seed, prop), 6)
        elif prop.endswith("_regression"):
            row[prop] = _stable_log_value(seed, prop, low=0.1, high=100.0)
        else:
            row[prop] = round(_stable_unit_float(seed, prop), 6)
    return row


def create_tools_router(
    *,
    executions: dict[str, dict[str, Any]],
    execution_start_times: dict[str, datetime],
    mock_execution_durations: dict[str, float],
    docking_speed: float,
    fixtures_dir: Path,
    load_fixture: Callable[[str], dict[str, Any]],
    results: list[dict[str, Any]],
    user_logs: dict[str, dict[str, Any]],
    file_storage: dict[str, bytes],
) -> APIRouter:
    """Create a router for tools-related endpoints.

    Args:
        executions: In-memory storage for executions.
        execution_start_times: Mapping of execution ID to start time.
        mock_execution_durations: Tool-specific mock durations in seconds.
        docking_speed: Dockings per second for bulk-docking simulations.
        fixtures_dir: Directory where fixture files are stored.
        load_fixture: Callable to load fixture data by name.
        results: Shared result-explorer record list; tool executions that
            produce outputs will inject records here so they are visible
            via the result-explorer search endpoint.
        user_logs: Shared user_logs store keyed by row id.
        file_storage: In-memory file bytes keyed by remote path.

    Returns:
        APIRouter instance with tools-related routes.
    """
    router = APIRouter()

    # -- helper closures (capture shared state) --------------------------------

    def _load_progress_reports(tool_key: str) -> list[dict[str, Any] | None]:
        """Load progress reports for a tool."""
        if tool_key == "deeporigin.abfe-e2e-workflow":
            fixture_path = fixtures_dir / "abfe" / "progress-reports.json"
        else:
            fixture_path = fixtures_dir / tool_key / "progress-reports.json"

        if not fixture_path.exists():
            return []

        with open(fixture_path) as f:
            return json.load(f)

    def _ligand_count(user_inputs: dict[str, Any]) -> int:
        """Count ligands from bulk-docking ``userInputs`` (``ligands`` or ``smiles_list``)."""
        ligands = user_inputs.get("ligands") or []
        smiles_list = user_inputs.get("smiles_list") or []
        if ligands:
            return len(ligands)
        if smiles_list:
            return len(smiles_list)
        return 1

    def _get_bulk_docking_progress_report(
        execution: dict[str, Any], execution_id: str
    ) -> dict[str, Any] | None:
        """Update bulk-docking execution progress and return ``progressReport`` JSON."""
        status = execution.get("status")

        if status == "Completed":
            existing = execution.get("progressReport")
            if isinstance(existing, dict) and "complete" in existing:
                return existing
            report = {"complete": 100}
            execution["progressReport"] = report
            return report

        if status in ("Failed", "Cancelled"):
            return None

        if status != "Running":
            return None

        if execution_id not in execution_start_times:
            return None

        user_inputs = execution.get("userInputs", {})
        n_ligands = max(1, _ligand_count(user_inputs))

        speed = docking_speed if docking_speed > 0 else 0.5
        duration_seconds = n_ligands / speed

        start_time = execution_start_times[execution_id]
        now = datetime.now(timezone.utc)
        elapsed_seconds = (now - start_time).total_seconds()

        if duration_seconds <= 0:
            complete = 100
        else:
            complete = int(min(100.0, (elapsed_seconds / duration_seconds) * 100.0))

        if complete >= 100:
            execution["status"] = "Completed"
            ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            execution["completedAt"] = ts
            execution["updatedAt"] = ts
            execution["progressReport"] = {"complete": 100}
            return execution["progressReport"]

        execution["progressReport"] = {"complete": complete}
        execution["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        return execution["progressReport"]

    def _get_rbfe_progress_report(
        execution: dict[str, Any], execution_id: str
    ) -> dict[str, Any] | None:
        """Simulate RBFE v2 workflow progress tree until the mock run completes."""
        status = execution.get("status")
        user_inputs = execution.get("userInputs") or {}
        if not isinstance(user_inputs, dict):
            user_inputs = {}

        duration = mock_execution_durations.get("deeporigin.rbfe", 5.0)
        start_time = execution_start_times.get(execution_id)

        if status == "Succeeded":
            cached = execution.get("progressReport")
            if isinstance(cached, dict) and cached.get("displayName"):
                return cached
            if start_time is None:
                start_time = datetime.now(timezone.utc)
            report = build_rbfe_progress_tree(
                execution_id=str(execution_id),
                user_inputs=user_inputs,
                start_dt=start_time,
                duration_s=duration,
                fraction=1.0,
            )
            execution["progressReport"] = report
            return report

        if status in ("Failed", "Cancelled"):
            return None

        if status != "Running" or start_time is None:
            return None

        now = datetime.now(timezone.utc)
        elapsed_seconds = (now - start_time).total_seconds()
        fraction = min(1.0, elapsed_seconds / duration) if duration > 0 else 1.0

        if elapsed_seconds >= duration:
            execution["status"] = "Succeeded"
            ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            execution["completedAt"] = ts
            execution["updatedAt"] = ts
            _inject_rbfe_tool_execution_results(execution)
            report = build_rbfe_progress_tree(
                execution_id=str(execution_id),
                user_inputs=user_inputs,
                start_dt=start_time,
                duration_s=duration,
                fraction=1.0,
            )
            execution["progressReport"] = report
            return report

        report = build_rbfe_progress_tree(
            execution_id=str(execution_id),
            user_inputs=user_inputs,
            start_dt=start_time,
            duration_s=duration,
            fraction=fraction,
        )
        execution["progressReport"] = report
        execution["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        return report

    def _get_progress_report(
        execution: dict[str, Any], tool_key: str
    ) -> dict[str, Any] | str | None:
        """Get progress report for an execution based on elapsed time."""
        status = execution.get("status")
        execution_id = execution.get("executionId")

        if tool_key == "deeporigin.bulk-docking":
            bulk = _get_bulk_docking_progress_report(execution, execution_id)
            return bulk

        if tool_key == "deeporigin.rbfe":
            return _get_rbfe_progress_report(execution, execution_id)

        if status == "Completed":
            progress_reports = _load_progress_reports(tool_key)
            if progress_reports:
                final_report = progress_reports[-1]
                return json.dumps(final_report) if final_report is not None else None
            return None

        if status in ("Failed", "Cancelled"):
            return json.dumps({})

        if status != "Running":
            return None

        if execution_id not in execution_start_times:
            return None

        start_time = execution_start_times[execution_id]
        now = datetime.now(timezone.utc)
        elapsed_seconds = (now - start_time).total_seconds()

        duration = mock_execution_durations.get(tool_key, 300.0)

        if elapsed_seconds >= duration:
            execution["status"] = "Completed"
            execution["completedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            execution["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            if tool_key in (
                "deeporigin.docking",
                "deeporigin.constrained-docking",
            ):
                _inject_docking_tool_execution_results(execution)
            if tool_key == "deeporigin.draco":
                _inject_patent_tool_execution_results(execution)
            progress_reports = _load_progress_reports(tool_key)
            if progress_reports:
                final_report = progress_reports[-1]
                return json.dumps(final_report) if final_report is not None else None
            return None

        progress_ratio = min(elapsed_seconds / duration, 1.0)

        progress_reports = _load_progress_reports(tool_key)
        if not progress_reports:
            return None

        max_index = len(progress_reports) - 1
        index = int(progress_ratio * max_index)
        index = max(0, min(index, max_index))

        progress_report = progress_reports[index]
        return json.dumps(progress_report) if progress_report is not None else None

    def _create_execution_dto(
        *,
        tool_key: str,
        tool_version: str,
        org_key: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Create an execution DTO dynamically."""
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        execution_id = str(uuid.uuid4())

        approve_amount = body.get("approveAmount", 0)
        if approve_amount is None:
            approve_amount = 0

        if approve_amount == 0:
            status = "Quoted"
        else:
            raise NotImplementedError(
                "approveAmount > 0 is not yet implemented in mock server"
            )

        execution: dict[str, Any] = {
            "executionId": execution_id,
            "createdAt": timestamp,
            "updatedAt": timestamp,
            "resourceId": _generate_resource_id(),
            "status": status,
            "userInputs": body.get("inputs", {}),
            "userOutputs": body.get("outputs", {}),
            "metadata": body.get("metadata", {}),
            "approveAmount": approve_amount,
            "jobOutputs": None,
            "resourcesUsed": None,
            "resourcesRequested": None,
            "progressReport": None,
            "statusReason": None,
            "name": None,
            "orgKey": org_key,
            "tool": {"key": tool_key, "version": tool_version},
            "type": "ToolExecution",
        }
        proj = body.get("projectId")
        if proj is not None:
            execution["projectId"] = proj

        tool_fixture_dir = fixtures_dir / tool_key
        if tool_fixture_dir.exists():
            quotation_result_path = tool_fixture_dir / "quotation-result.json"
            if quotation_result_path.exists():
                try:
                    execution["quotationResult"] = load_fixture(
                        f"{tool_key}/quotation-result"
                    )
                except FileNotFoundError:
                    pass

            if approve_amount > 0:
                billing_transaction_path = tool_fixture_dir / "billing-transaction.json"
                if billing_transaction_path.exists():
                    try:
                        execution["billingTransaction"] = load_fixture(
                            f"{tool_key}/billing-transaction"
                        )
                    except FileNotFoundError:
                        pass

            execution["cluster"] = {"id": str(uuid.uuid4())}

        execution["startedAt"] = None
        execution["completedAt"] = None

        return execution

    def _create_blocking_run_dto(
        *,
        org_key: str,
        tool_key: str,
        tool_version: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a synchronous Completed execution DTO for a single ``run_tool`` POST.

        Used for tools whose ``sync=True`` mock path completes the execution
        in one POST: docking (single ligand), pocket-finder, system-prep.
        """
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        eid = str(uuid.uuid4())
        approve_amount = body.get("approveAmount", 0) or 0
        execution: dict[str, Any] = {
            "executionId": eid,
            "createdAt": ts,
            "updatedAt": ts,
            "resourceId": _generate_resource_id(),
            "status": "Completed",
            "userInputs": body.get("inputs", {}),
            "userOutputs": body.get("outputs", {}),
            "metadata": body.get("metadata", {}),
            "approveAmount": approve_amount,
            "jobOutputs": None,
            "resourcesUsed": None,
            "resourcesRequested": None,
            "progressReport": json.dumps({"complete": 100}),
            "statusReason": None,
            "name": body.get("name"),
            "orgKey": org_key,
            "tool": {"key": tool_key, "version": tool_version},
            "type": "ToolExecution",
            "startedAt": ts,
            "completedAt": ts,
        }
        if body.get("projectId") is not None:
            execution["projectId"] = body["projectId"]
        tdir = fixtures_dir / tool_key
        if tdir.exists():
            qr = tdir / "quotation-result.json"
            if qr.exists():
                try:
                    execution["quotationResult"] = load_fixture(
                        f"{tool_key}/quotation-result"
                    )
                except FileNotFoundError:
                    pass
            execution["cluster"] = {"id": str(uuid.uuid4())}
        return execution

    def _build_protonation_outputs(
        *, smiles: str, ph: float, filter_percentage: float
    ) -> dict[str, Any]:
        """Return the synthetic ``jobOutputs`` for a protonation tool execution."""
        expected_smiles = "C=CCCn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O"
        if smiles != expected_smiles:
            return {
                "smiles": smiles,
                "pH": ph,
                "filter_percentage": filter_percentage,
                "protonation_states": {
                    "smiles_list": [smiles],
                    "concentration_list": [99.93319834034459],
                },
            }
        if ph < 8:
            return {
                "smiles": expected_smiles,
                "pH": ph,
                "filter_percentage": filter_percentage,
                "protonation_states": {
                    "smiles_list": [expected_smiles],
                    "concentration_list": [99.93319834034459],
                },
            }
        return {
            "smiles": expected_smiles,
            "pH": ph,
            "filter_percentage": filter_percentage,
            "protonation_states": {
                "smiles_list": [
                    "C=CCCn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[n-]c2c1=O",
                    expected_smiles,
                ],
                "concentration_list": [
                    79.69080764827427,
                    20.309192281585123,
                ],
            },
        }

    def _build_pose_registration_execution(
        *,
        org_key: str,
        tool_key: str,
        tool_version: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a synchronous ImportTool execution that registers one pose row."""
        execution = _create_blocking_run_dto(
            org_key=org_key,
            tool_key=tool_key,
            tool_version=tool_version,
            body=body,
        )
        inputs = body.get("inputs", {}) or {}
        if not inputs.get("register_pose"):
            execution["jobOutputs"] = {"poses": []}
            return execution

        ligand_id = str(inputs.get("ligand_id") or "")
        file_path = str(inputs.get("file_path") or "")
        origin = str(inputs.get("origin") or "registered")
        pose_row: dict[str, Any] = {
            "file_path": file_path,
            "ligand_id": ligand_id,
            "origin": origin,
        }
        protein_id = inputs.get("protein_id")
        if protein_id is not None:
            pose_row["protein_id"] = str(protein_id)
        execution["jobOutputs"] = {"poses": [pose_row]}
        return execution

    def _build_protonation_execution(
        *, org_key: str, tool_key: str, tool_version: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Build a synchronous protonation execution DTO with realistic outputs."""
        execution = _create_blocking_run_dto(
            org_key=org_key,
            tool_key=tool_key,
            tool_version=tool_version,
            body=body,
        )

        inputs = body.get("inputs", body.get("params", {})) or {}
        ligand_in = inputs.get("ligand") or {}
        smiles = (
            ligand_in.get("smiles") if isinstance(ligand_in, dict) else None
        ) or inputs.get("smiles", "")
        ph = float(inputs.get("pH", 7.4))
        filter_percentage = float(inputs.get("filter_percentage", 1))

        if execution.get("quotationResult") is None:
            try:
                fixture = load_fixture(
                    "tool-runs/deeporigin.mol-props-protonation/"
                    "d9309dc3b122fc636e63c88a2dbf0b32f04cb23a5557affb9f1bb577ec6e5ffb"
                )
            except FileNotFoundError:
                fixture = None
            if isinstance(fixture, dict):
                quotation = _legacy_quotation(fixture)
                if quotation is not None:
                    execution["quotationResult"] = quotation

        execution["jobOutputs"] = _build_protonation_outputs(
            smiles=smiles, ph=ph, filter_percentage=filter_percentage
        )
        return execution

    def _build_molprops_execution(
        *, org_key: str, tool_key: str, tool_version: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Build a synchronous molprops execution DTO with fixture-backed outputs.

        Looks up a recorded fixture by hash for the given tool key; if the
        fixture is found it copies the legacy ``functionOutputs`` (a list of
        per-ligand rows) into ``jobOutputs`` and re-keys ``ligand_id`` to
        match the inputs that were actually sent.
        """
        from deeporigin.utils.hashing import (
            hash_dict,
            normalize_tool_execution_body,
        )

        execution = _create_blocking_run_dto(
            org_key=org_key,
            tool_key=tool_key,
            tool_version=tool_version,
            body=body,
        )

        normalized_body = normalize_tool_execution_body(body)
        body_hash = hash_dict(normalized_body)

        try:
            fixture = load_fixture(f"tool-runs/{tool_key}/{body_hash}")
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"No fixture found for tool '{tool_key}' with request hash "
                f"'{body_hash}'. Please create a fixture at: "
                f"tool-runs/{tool_key}/{body_hash}.json"
            ) from e

        fixture = copy.deepcopy(fixture)
        outputs = _legacy_outputs_to_job_outputs(fixture)
        if isinstance(outputs, list):
            inputs = body.get("inputs", {})
            ligands = inputs.get("ligands") or []
            ligand_ids: list[str] = []
            for lig in ligands:
                if isinstance(lig, dict) and lig.get("id") is not None:
                    ligand_ids.append(str(lig["id"]))
            if ligand_ids and len(ligand_ids) == len(outputs):
                for row, lid in zip(outputs, ligand_ids, strict=True):
                    if isinstance(row, dict):
                        row["ligand_id"] = lid

        execution["jobOutputs"] = outputs
        quotation = _legacy_quotation(fixture)
        if quotation is not None:
            execution["quotationResult"] = quotation
        return execution

    def _build_admet_properties_execution(
        *, org_key: str, tool_key: str, tool_version: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Build a synchronous ``deeporigin.admet-properties`` execution DTO."""

        from deeporigin.utils.constants import ADMET_PROPERTY_NAMES

        execution = _create_blocking_run_dto(
            org_key=org_key,
            tool_key=tool_key,
            tool_version=tool_version,
            body=body,
        )

        inputs = body.get("inputs", {}) or {}
        ligands_in = inputs.get("ligands") or []
        requested_raw = inputs.get("properties")
        if isinstance(requested_raw, list) and requested_raw:
            requested = [p for p in requested_raw if isinstance(p, str)]
        else:
            requested = list(ADMET_PROPERTY_NAMES)

        rows: list[dict[str, Any]] = []
        for i, lig in enumerate(ligands_in):
            if not isinstance(lig, dict):
                continue
            smiles = str(lig.get("smiles") or "")
            lid = str(lig.get("id") if lig.get("id") is not None else i)
            rows.append(
                _synthesize_admet_prediction_row(
                    smiles=smiles,
                    ligand_id=lid,
                    requested=requested,
                )
            )

        execution["jobOutputs"] = {"admet_properties": rows}
        execution["quotationResult"] = {
            "anyFailed": False,
            "failedQuotations": [],
            "successfulQuotations": [
                {
                    "status": "OK",
                    "itemCode": "DO_TOGO",
                    "orgId": org_key,
                    "qty": 1,
                    "priceEach": 1.0,
                    "priceTotal": 1.0,
                    "pricingRecordType": "regular",
                    "pricingRecords": [
                        {
                            "itemKey": "DO_TOGO",
                            "itemName": "ADMET Properties prediction",
                            "priceEach": 1.0,
                            "totalPrice": 1.0,
                            "qty": 1,
                            "tierQtyFrom": 0,
                            "tierQtyTo": 0,
                        }
                    ],
                }
            ],
        }
        return execution

    def _build_combined_molprops_execution(
        *, org_key: str, tool_key: str, tool_version: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Build a synchronous ``deeporigin.mol-props-combined`` execution DTO.

        Synthesizes one ``molprops`` row per input ligand containing the output
        keys for every property requested in ``inputs.molprops``. Per-ligand
        scalar values are derived deterministically from the SMILES so repeat
        calls with the same payload return the same numbers (without needing
        a recorded fixture). Returns the full execution DTO with both
        ``jobOutputs`` (wrapped under ``molprops``, matching the combined
        tool's output schema) and a synthetic ``quotationResult`` priced at a
        flat per-(ligand × property) rate.
        """
        execution = _create_blocking_run_dto(
            org_key=org_key,
            tool_key=tool_key,
            tool_version=tool_version,
            body=body,
        )

        inputs = body.get("inputs", {}) or {}
        ligands_in = inputs.get("ligands") or []
        requested = [p for p in (inputs.get("molprops") or []) if isinstance(p, str)]

        rows: list[dict[str, Any]] = []
        for i, lig in enumerate(ligands_in):
            if not isinstance(lig, dict):
                continue
            smiles = str(lig.get("smiles") or "")
            lid = str(lig.get("id") if lig.get("id") is not None else i)
            rows.append(
                _synthesize_molprops_row(
                    smiles=smiles, ligand_id=lid, requested=requested
                )
            )

        execution["jobOutputs"] = {"molprops": rows}

        n_billable = len(rows) * len(requested)
        if n_billable > 0:
            price_each = 0.02
            price_total = round(price_each * n_billable, 6)
            execution["quotationResult"] = {
                "anyFailed": False,
                "failedQuotations": [],
                "successfulQuotations": [
                    {
                        "status": "OK",
                        "itemCode": "DO_MOLPROPS",
                        "orgId": org_key,
                        "qty": n_billable,
                        "priceEach": price_each,
                        "priceTotal": price_total,
                        "pricingRecordType": "regular",
                        "pricingRecords": [
                            {
                                "itemKey": "DO_MOLPROPS",
                                "itemName": "Molecular Properties (combined)",
                                "priceEach": price_each,
                                "totalPrice": price_total,
                                "qty": n_billable,
                                "tierQtyFrom": 0,
                                "tierQtyTo": 0,
                            }
                        ],
                    }
                ],
            }

        return execution

    def _synthesize_available_reactions(smiles: str) -> list[dict[str, Any]]:
        """Return deterministic AVAILABLE_REACTIONS hits for a parent SMILES."""
        return [
            {
                "reaction_id": "suzuki",
                "reaction_name": "Suzuki Coupling",
                "reactant_role": "core_halide",
                "atom_indices": [0, 1],
            },
            {
                "reaction_id": "buchwald_hartwig",
                "reaction_name": "Buchwald-Hartwig",
                "reactant_role": "core_halide",
                "atom_indices": [0, 1],
            },
        ]

    def _synthesize_enumerator_csv(
        *,
        job_type: str,
        inputs: dict[str, Any],
        smiles: str,
        parent_ligand_id: str,
    ) -> str:
        """Build a descriptor-enriched enumerator ``results.csv`` for MMP / REACTION."""
        import csv
        import io

        from deeporigin.utils.constants import (
            ENUMERATOR_RDKIT_DESCRIPTOR_COLUMNS,
            ENUMERATOR_RESULTS_CSV_COLUMNS,
        )

        columns = list(ENUMERATOR_RESULTS_CSV_COLUMNS) + list(
            ENUMERATOR_RDKIT_DESCRIPTOR_COLUMNS
        )
        is_reaction = job_type == "REACTION"
        enumeration_mode = "REACTION" if is_reaction else "MMP"
        reaction_sites = inputs.get("reaction_sites") or []
        first_site = reaction_sites[0] if reaction_sites else {}
        products = (
            ["c1ccc(-c2ccccc2)cc1", "c1ccc(-c2ccncc2)cc1"]
            if is_reaction
            else ["Cc1ccccc1", "CCc1ccccc1"]
        )

        rows: list[dict[str, Any]] = []
        for i, product in enumerate(products, start=1):
            row: dict[str, Any] = {c: "" for c in columns}
            row["row_id"] = i
            row["smiles"] = product
            row["parent_smiles"] = smiles
            row["enumeration_mode"] = enumeration_mode
            row["parent_ligand_id"] = parent_ligand_id
            row["job_type"] = job_type
            if is_reaction:
                row["reaction_id"] = first_site.get("reaction_id", "")
                row["reactant_role"] = first_site.get("reactant_role", "")
                row["atom_indices"] = json.dumps(first_site.get("atom_indices", []))
                row["building_block_id"] = f"EN300-{i:04d}"
            else:
                row["replace_ix"] = json.dumps(inputs.get("replace_ix", []))
                row["radius"] = inputs.get("radius", 1)
                row["max_fragment_size"] = inputs.get("max_fragment_size", 10)
            descriptor_values = {
                "molecular_weight": round(92.14 + i, 3),
                "hbond_donor_count": 0,
                "hbond_acceptor_count": 0,
                "logp": round(1.5 + i * 0.1, 3),
                "tpsa": 0.0,
                "rotatable_bond_count": i,
            }
            for key, value in descriptor_values.items():
                row[key] = value
            rows.append(row)

        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue()

    def _build_enumerator_execution(
        *, org_key: str, tool_key: str, tool_version: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Build a synchronous ``deeporigin.enumerator`` execution DTO.

        For ``AVAILABLE_REACTIONS`` it returns inline ``available_reactions`` and
        writes no CSV. For the MMP modes (``SCAFFOLD`` / ``ANALOGUE``) and
        ``REACTION`` it writes a descriptor-enriched ``results.csv`` into the
        mock file store and returns an ``enumeration_results`` row pointing at it.
        """
        execution = _create_blocking_run_dto(
            org_key=org_key,
            tool_key=tool_key,
            tool_version=tool_version,
            body=body,
        )
        eid = execution["executionId"]
        inputs = body.get("inputs", {}) or {}
        job_type = str(inputs.get("job_type") or "")
        ligand_in = inputs.get("ligand") or {}
        smiles = str(ligand_in.get("smiles") or "")
        parent_ligand_id = str(ligand_in.get("id") or "")

        if job_type == "AVAILABLE_REACTIONS":
            execution["jobOutputs"] = {
                "available_reactions": _synthesize_available_reactions(smiles),
            }
            return execution

        csv_text = _synthesize_enumerator_csv(
            job_type=job_type,
            inputs=inputs,
            smiles=smiles,
            parent_ligand_id=parent_ligand_id,
        )
        csv_path = f"tool-runs/{eid}/results.csv"
        file_storage[csv_path] = csv_text.encode("utf-8")

        row: dict[str, Any] = {
            "parent_smiles": smiles,
            "cap_hit": False,
            "csv_file_path": csv_path,
        }
        if parent_ligand_id:
            row["parent_ligand_id"] = parent_ligand_id
        execution["jobOutputs"] = {"enumeration_results": [row]}
        return execution

    def _inject_result_explorer_records_from_outputs(
        *,
        tool_key: str,
        tool_version: str,
        execution_id: str,
        job_outputs: object,
    ) -> None:
        """Mirror tool ``jobOutputs`` into ``results`` (the result-explorer pool)."""
        if not isinstance(job_outputs, dict):
            return

        output_key_map: dict[str, tuple[str, str]] = {
            "deeporigin.pocketfinder": ("pockets", "pocket"),
            "deeporigin.pocket-finder": ("pockets", "pocket"),
            "deeporigin.docking": ("poses", "pose"),
            "deeporigin.constrained-docking": ("poses", "pose"),
            "deeporigin.import-dataset": ("poses", "pose"),
            "deeporigin.system-prep": ("system", "preparedsystem"),
            "deeporigin.protein-prep": ("protein", "preparedprotein"),
            "deeporigin.draco": ("do_patent_molecules", "dopatentmolecule"),
        }

        entry = output_key_map.get(tool_key)
        if not entry:
            return

        output_key, result_type = entry
        output_value = job_outputs.get(output_key)
        if output_value is None:
            return

        items = output_value if isinstance(output_value, list) else [output_value]
        # For docking poses: mark the first pose per ligand as best_pose=True so
        # that the mock's top-level equality filter (best_pose == True) works.
        best_pose_seen: set[str] = set()
        for item in items:
            data = dict(item)
            extra: dict[str, Any] = {}
            if result_type == "pose":
                if "best_pose" not in data:
                    ligand_key = str(data.get("ligand_id") or "")
                    is_best = ligand_key not in best_pose_seen
                    data["best_pose"] = is_best
                    best_pose_seen.add(ligand_key)
                extra["best_pose"] = data["best_pose"]
            record = {
                "id": "08" + str(uuid.uuid4()).replace("-", "").upper()[:11],
                "tool_key": tool_key,
                "tool_version": tool_version,
                "result_type": result_type,
                "data": data,
                "compute_job_id": execution_id,
                **extra,
            }
            results.append(record)

        if tool_key == "deeporigin.constrained-docking":
            reference_pose = job_outputs.get("reference_pose")
            if isinstance(reference_pose, dict):
                results.append(
                    {
                        "id": "08" + str(uuid.uuid4()).replace("-", "").upper()[:11],
                        "tool_key": tool_key,
                        "tool_version": tool_version,
                        "result_type": result_type,
                        "data": dict(reference_pose),
                        "compute_job_id": execution_id,
                    }
                )

    def _inject_docking_tool_execution_results(execution: dict[str, Any]) -> None:
        """Mirror docking fixture poses into ``results`` when an execution completes."""
        eid = execution.get("executionId")
        tool = execution.get("tool") or {}
        tkey = tool.get("key")
        tool_version = tool.get("version", "0.0.0")
        if not eid or tkey not in (
            "deeporigin.docking",
            "deeporigin.constrained-docking",
        ):
            return
        if any(r.get("compute_job_id") == eid for r in results):
            return

        fixture = copy.deepcopy(load_fixture("tool-runs/deeporigin.docking/run"))
        outputs = _legacy_outputs_to_job_outputs(fixture)
        if not isinstance(outputs, dict):
            return

        user_inputs = execution.get("userInputs", {})
        protein = (
            user_inputs.get("protein", {}) if isinstance(user_inputs, dict) else {}
        )
        protein_id = protein.get("id") if isinstance(protein, dict) else None
        ligand_id = None
        ligands_list = user_inputs.get("ligands") or []
        if (
            isinstance(ligands_list, list)
            and ligands_list
            and isinstance(ligands_list[0], dict)
        ):
            ligand_id = ligands_list[0].get("id")
        outputs = _replace_ids_in_outputs(
            outputs, protein_id=protein_id, ligand_id=ligand_id
        )
        if tkey == "deeporigin.constrained-docking":
            poses = outputs.get("poses")
            if isinstance(poses, list):
                for pose in poses:
                    if isinstance(pose, dict):
                        pose.setdefault("constrained", True)
                        pose.setdefault("effort", user_inputs.get("effort", 1))
                        pose.setdefault("best_pose", True)
            reference = (
                user_inputs.get("reference", {})
                if isinstance(user_inputs, dict)
                else {}
            )
            ref_pose = reference.get("pose", {}) if isinstance(reference, dict) else {}
            ref_ligand = (
                reference.get("ligand", {}) if isinstance(reference, dict) else {}
            )
            if isinstance(ref_pose, dict) and ref_pose.get("file_path"):
                reference_pose_output: dict[str, Any] = {
                    "file_path": ref_pose["file_path"],
                    "ligand_id": ref_ligand.get("id")
                    if isinstance(ref_ligand, dict)
                    else None,
                    "protein_id": protein_id,
                }
                ref_smiles = (
                    ref_ligand.get("smiles") if isinstance(ref_ligand, dict) else None
                )
                if ref_smiles:
                    reference_pose_output["smiles"] = ref_smiles
                outputs["reference_pose"] = reference_pose_output
        execution["jobOutputs"] = outputs
        _inject_result_explorer_records_from_outputs(
            tool_key=tkey,
            tool_version=tool_version,
            execution_id=eid,
            job_outputs=outputs,
        )

    def _inject_pocketfinder_tool_execution_results(
        execution: dict[str, Any],
    ) -> None:
        """Mirror pocket-finder fixture outputs into ``results`` for tool executions."""
        eid = execution.get("executionId")
        tool = execution.get("tool") or {}
        tkey = tool.get("key")
        tool_version = tool.get("version", "0.0.0")
        if not eid or tkey != "deeporigin.pocket-finder":
            return
        if any(r.get("compute_job_id") == eid for r in results):
            return

        fixture = copy.deepcopy(load_fixture("tool-runs/deeporigin.pocketfinder/run"))
        outputs = _legacy_outputs_to_job_outputs(fixture)
        if not isinstance(outputs, dict):
            return

        user_inputs = execution.get("userInputs", {})
        protein = (
            user_inputs.get("protein", {}) if isinstance(user_inputs, dict) else {}
        )
        protein_id = protein.get("id") if isinstance(protein, dict) else None
        pockets = outputs.get("pockets")
        if isinstance(pockets, list):
            for p in pockets:
                if isinstance(p, dict) and protein_id is not None:
                    p["protein_id"] = protein_id
        execution["jobOutputs"] = outputs
        _inject_result_explorer_records_from_outputs(
            tool_key=tkey,
            tool_version=tool_version,
            execution_id=eid,
            job_outputs=outputs,
        )

    def _inject_patent_tool_execution_results(execution: dict[str, Any]) -> None:
        """Mirror patent fixture outputs into ``results`` for tool executions."""
        eid = execution.get("executionId")
        tool = execution.get("tool") or {}
        tkey = tool.get("key")
        tool_version = tool.get("version", "0.0.0")
        if not eid or tkey != "deeporigin.draco":
            return
        if any(r.get("compute_job_id") == eid for r in results):
            return

        fixture = copy.deepcopy(load_fixture("tool-runs/deeporigin.draco/run"))
        outputs = _legacy_outputs_to_job_outputs(fixture)
        if not isinstance(outputs, dict):
            return

        execution["jobOutputs"] = outputs
        _inject_result_explorer_records_from_outputs(
            tool_key=tkey,
            tool_version=tool_version,
            execution_id=eid,
            job_outputs=outputs,
        )

    def _inject_sysprep_tool_execution_results(execution: dict[str, Any]) -> None:
        """Mirror system-prep fixture outputs into ``results`` for tool executions."""
        eid = execution.get("executionId")
        tool = execution.get("tool") or {}
        tkey = tool.get("key")
        tool_version = tool.get("version", "0.0.0")
        if not eid or tkey != "deeporigin.system-prep":
            return
        if any(r.get("compute_job_id") == eid for r in results):
            return

        user_inputs = execution.get("userInputs", {})
        if not isinstance(user_inputs, dict):
            user_inputs = {}
        fixture_name = "tool-runs/deeporigin.system-prep/run"
        if user_inputs.get("ligand2") is not None:
            fixture_name = "tool-runs/deeporigin.system-prep/run-rbfe"
        fixture = copy.deepcopy(load_fixture(fixture_name))
        outputs = _legacy_outputs_to_job_outputs(fixture)
        if not isinstance(outputs, dict):
            return

        protein = user_inputs.get("protein", {})
        protein_id = protein.get("id") if isinstance(protein, dict) else None
        ligand1 = user_inputs.get("ligand1") or {}
        ligand1_id = ligand1.get("id") if isinstance(ligand1, dict) else None
        ligand2 = user_inputs.get("ligand2") or {}
        ligand2_id = ligand2.get("id") if isinstance(ligand2, dict) else None
        system = outputs.get("system")
        if isinstance(system, dict):
            if protein_id is not None:
                system["protein_id"] = protein_id
            if ligand1_id is not None:
                system["ligand1_id"] = ligand1_id
            if ligand2_id is not None:
                system["ligand2_id"] = ligand2_id
        execution["jobOutputs"] = outputs
        _inject_result_explorer_records_from_outputs(
            tool_key=tkey,
            tool_version=tool_version,
            execution_id=eid,
            job_outputs=outputs,
        )

    def _inject_protein_prep_tool_execution_results(
        execution: dict[str, Any],
    ) -> None:
        """Mirror protein-prep fixture outputs into ``results`` for tool executions."""
        eid = execution.get("executionId")
        tool = execution.get("tool") or {}
        tkey = tool.get("key")
        tool_version = tool.get("version", "0.0.0")
        if not eid or tkey != "deeporigin.protein-prep":
            return
        if any(r.get("compute_job_id") == eid for r in results):
            return

        fixture = copy.deepcopy(load_fixture("tool-runs/deeporigin.protein-prep/run"))
        outputs = _legacy_outputs_to_job_outputs(fixture)
        if not isinstance(outputs, dict):
            return

        user_inputs = execution.get("userInputs", {})
        protein = (
            user_inputs.get("protein", {}) if isinstance(user_inputs, dict) else {}
        )
        protein_id = protein.get("id") if isinstance(protein, dict) else None
        pdb_id = user_inputs.get("pdb_id") if isinstance(user_inputs, dict) else None
        protein_out = outputs.get("protein")
        if isinstance(protein_out, dict):
            if protein_id is not None:
                protein_out["protein_id"] = protein_id
            if pdb_id is not None:
                protein_out["pdb_id"] = pdb_id
        execution["jobOutputs"] = outputs
        _inject_result_explorer_records_from_outputs(
            tool_key=tkey,
            tool_version=tool_version,
            execution_id=eid,
            job_outputs=outputs,
        )

    def _inject_rbfe_user_logs(execution_id: str) -> None:
        """Append captured RBFE user_logs rows scoped to *execution_id*."""
        fixture_path = fixtures_dir / "user_logs-rbfe-a5484958.json"
        if not fixture_path.is_file():
            return
        with open(fixture_path) as f:
            rows = json.load(f)
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            new_row = copy.deepcopy(row)
            row_id = "0AE" + str(uuid.uuid4()).replace("-", "").upper()[:11]
            new_row["id"] = row_id
            new_row["execution_id"] = execution_id
            user_logs[row_id] = new_row

    def _inject_rbfe_binding_nohup(execution_id: str) -> None:
        """Serve ``binding_nohup.out`` for dynamic RBFE execution ids."""
        template_path = fixtures_dir / RBFE_NOHUP_FIXTURE_PATH
        if not template_path.is_file():
            return
        remote_path = f"tool-runs/{execution_id}/workflow-mock/binding_nohup.out"
        file_storage[remote_path] = template_path.read_bytes()

    def _inject_rbfe_tool_execution_results(execution: dict[str, Any]) -> None:
        """Append RBFE result-explorer rows captured from a successful dev run."""
        eid = execution.get("executionId")
        tool = execution.get("tool") or {}
        tkey = tool.get("key")
        tool_version = tool.get("version", "0.0.0")
        if not eid or tkey != "deeporigin.rbfe":
            return
        if any(r.get("compute_job_id") == eid for r in results):
            return

        template = copy.deepcopy(
            load_fixture("tool-runs/deeporigin.rbfe/result-template")
        )
        template["compute_job_id"] = eid
        template["tool_key"] = tkey
        template["tool_version"] = tool_version
        template["id"] = "08" + str(uuid.uuid4()).replace("-", "").upper()[:11]

        user_inputs = execution.get("userInputs", {})
        if not isinstance(user_inputs, dict):
            user_inputs = {}
        data = template.get("data")
        if isinstance(data, dict):
            ps_list = user_inputs.get("prepared_systems") or []
            if isinstance(ps_list, list) and ps_list and isinstance(ps_list[0], dict):
                ps0 = ps_list[0]
                for key in ("ligand1_id", "ligand2_id", "protein_id"):
                    if ps0.get(key) is not None:
                        data[key] = ps0[key]
        if isinstance(data, dict) and "cycleclosureresults" not in data:
            data["cycleclosureresults"] = [
                {
                    "ligand_id": data.get("ligand1_id") or "lig-1",
                    "dG": -10.0,
                    "unit": "kcal/mol",
                },
            ]
        results.append(template)
        executions[eid] = execution
        _inject_rbfe_user_logs(str(eid))
        _inject_rbfe_binding_nohup(str(eid))

    # -- route handlers --------------------------------------------------------

    @router.get("/tools/health")
    def tools_health() -> dict[str, str]:
        """Health check for the tools service."""
        return {"status": "ok"}

    @router.get("/tools/protected/tools/definitions")
    def list_tools() -> dict[str, Any]:
        """List all tool definitions."""
        return {
            "data": [
                {
                    "key": "test-tool",
                    "name": "Test Tool",
                    "version": "1.0.0",
                    "inputs": {},
                    "executors": [],
                    "description": "Test tool description",
                    "billingParser": {},
                    "toolManifestVersion": "1.0.0",
                },
                {
                    "key": "deeporigin.docking",
                    "name": "Docking Tool",
                    "version": "1.0.0",
                    "inputs": {},
                    "executors": [],
                    "description": "Docking tool description",
                    "billingParser": {},
                    "toolManifestVersion": "1.0.0",
                },
            ]
        }

    @router.get("/tools/protected/tools/{tool_key}/definitions")
    def get_tool_by_key(tool_key: str) -> dict[str, Any]:
        """Get tool definitions by key."""
        if tool_key == "nonexistent-tool":
            return {"data": []}
        return {
            "data": [
                {
                    "key": tool_key,
                    "name": f"Tool {tool_key}",
                    "version": "1.0.0",
                }
            ]
        }

    @router.get("/tools/protected/tools/{tool_key}/{tool_version}/definitions")
    def get_tool_by_key_and_version(tool_key: str, tool_version: str) -> dict[str, Any]:
        """Get a single tool definition by key and version."""
        if tool_key == "nonexistent-tool":
            raise HTTPException(status_code=404, detail="Tool not found")
        enabled = tool_key != "disabled-tool"
        return {
            "key": tool_key,
            "name": f"Tool {tool_key}",
            "version": tool_version,
            "inputs": {},
            "executors": [],
            "description": "Mock tool definition",
            "toolManifestVersion": "1.0.0",
            "enabled": enabled,
        }

    @router.get("/tools/{org_key}/clusters")
    async def list_clusters(org_key: str, request: Request) -> dict[str, Any]:
        """List clusters."""
        if org_key == "empty-org":
            return {
                "data": [],
                "pagination": {"count": 0},
            }
        return {
            "data": [
                {
                    "id": "cluster-dev-1",
                    "hostname": "dev-cluster.example.com",
                    "name": "Dev Cluster",
                },
                {
                    "id": "cluster-prod-1",
                    "hostname": "prod-cluster.example.com",
                    "name": "Prod Cluster",
                },
            ],
            "pagination": {"count": 2},
        }

    @router.get("/tools/{org_key}/tools/executions")
    def list_executions(
        org_key: str,
        page: int = 0,
        pageSize: int = 100,
        limit: int = 100,
        filter: str | None = None,
    ) -> dict[str, Any]:
        """List tool executions."""
        filter_dict = None
        requested_tool_key = None
        requested_statuses = None
        project_id_filter_set = False
        project_id_filter_value: str | None = None

        if filter:
            filter_dict = json.loads(filter)
            if "tool" in filter_dict:
                tool_filter = filter_dict["tool"]
                if (
                    "toolManifest" in tool_filter
                    and "key" in tool_filter["toolManifest"]
                ):
                    requested_tool_key = tool_filter["toolManifest"]["key"]
                elif "key" in tool_filter:
                    requested_tool_key = tool_filter["key"]

            if "status" in filter_dict:
                status_filter = filter_dict["status"]
                if "$in" in status_filter:
                    requested_statuses = status_filter["$in"]

            if "projectId" in filter_dict:
                project_id_filter_set = True
                project_id_filter_value = filter_dict["projectId"]

        created_after_gt: str | None = None
        if filter_dict and "createdAt" in filter_dict:
            ca_filter = filter_dict["createdAt"]
            if isinstance(ca_filter, dict) and ca_filter.get("$gt") is not None:
                created_after_gt = str(ca_filter["$gt"])

        all_executions = list(executions.values())

        filtered_executions = [
            exec for exec in all_executions if exec.get("orgKey") == org_key
        ]

        if requested_tool_key:
            filtered_executions = [
                exec
                for exec in filtered_executions
                if exec.get("tool", {}).get("key") == requested_tool_key
            ]

        if requested_statuses:
            filtered_executions = [
                exec
                for exec in filtered_executions
                if exec.get("status") in requested_statuses
            ]

        if project_id_filter_set:
            if project_id_filter_value is None:
                filtered_executions = [
                    exec
                    for exec in filtered_executions
                    if exec.get("projectId") is None
                ]
            else:
                filtered_executions = [
                    exec
                    for exec in filtered_executions
                    if exec.get("projectId") == project_id_filter_value
                ]

        if filter_dict and "session" in filter_dict:
            session_filter_value = filter_dict["session"]
            filtered_executions = [
                exec
                for exec in filtered_executions
                if exec.get("session") is None
                or exec.get("session") == session_filter_value
            ]

        if created_after_gt is not None:

            def _parse_created_at(value: str) -> datetime:
                normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
                parsed = datetime.fromisoformat(normalized)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)

            threshold = _parse_created_at(created_after_gt)
            filtered_executions = [
                exec
                for exec in filtered_executions
                if exec.get("createdAt")
                and _parse_created_at(str(exec["createdAt"])) > threshold
            ]

        if filter_dict and "metadata" in filter_dict:
            metadata_filter = filter_dict["metadata"]
            if metadata_filter.get("$exists") is True:
                filtered_executions = [
                    exec
                    for exec in filtered_executions
                    if exec.get("metadata") is not None
                ]

        filtered_executions.sort(key=lambda x: x.get("createdAt", ""), reverse=True)

        page_size = pageSize if pageSize else limit
        start_idx = page * page_size
        end_idx = start_idx + page_size
        paginated_executions = filtered_executions[start_idx:end_idx]

        normalized_executions = [
            _normalize_execution(exec.copy()) for exec in paginated_executions
        ]

        return {
            "count": len(filtered_executions),
            "data": normalized_executions,
        }

    @router.get("/tools/{org_key}/tools/executions/{execution_id}")
    def get_execution(org_key: str, execution_id: str) -> dict[str, Any]:
        """Get execution by ID."""
        if execution_id not in executions:
            raise HTTPException(
                status_code=404, detail=f"Execution {execution_id} not found"
            )

        execution = executions[execution_id].copy()
        if execution_id in execution_start_times:
            start_time = execution_start_times[execution_id]
            execution["startedAt"] = (
                start_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            )
            now = datetime.now(timezone.utc)
            execution["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        tool_key = execution.get("tool", {}).get("key")
        if tool_key:
            progress_report = _get_progress_report(execution, tool_key)
            execution["progressReport"] = progress_report

        executions[execution_id] = execution

        return _normalize_execution(execution)

    @router.patch("/tools/{org_key}/tools/executions/{execution_id}:cancel")
    def cancel_execution(org_key: str, execution_id: str) -> dict[str, Any]:
        """Cancel an execution."""
        if execution_id not in executions:
            raise HTTPException(
                status_code=404, detail=f"Execution {execution_id} not found"
            )

        execution = executions[execution_id]
        execution["status"] = "Cancelled"

        now = datetime.now(timezone.utc)
        execution["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        executions[execution_id] = execution

        return _normalize_execution(execution.copy())

    @router.patch("/tools/{org_key}/tools/executions/{execution_id}:confirm")
    def confirm_execution(org_key: str, execution_id: str) -> dict[str, Any]:
        """Confirm an execution."""
        if execution_id not in executions:
            raise HTTPException(
                status_code=404, detail=f"Execution {execution_id} not found"
            )

        execution = executions[execution_id]
        execution["status"] = "Running"

        now = datetime.now(timezone.utc)
        execution_start_times[execution_id] = now
        execution["startedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        execution["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        executions[execution_id] = execution

        return _normalize_execution(execution.copy())

    def _create_bulk_docking_quote(
        *,
        org_key: str,
        tool_key: str,
        tool_version: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a Quoted execution DTO for bulk-docking from the captured fixture.

        Loads the reference quote fixture (1 ligand) and scales the
        quotation quantities and totals by the number of ligands in the
        request payload.

        Args:
            org_key: Organisation key from the URL path.
            tool_key: Tool key (``deeporigin.bulk-docking``).
            tool_version: Tool version from the URL path.
            body: Raw POST body.

        Returns:
            A complete execution DTO with ``status="Quoted"`` and a
            correctly-scaled ``quotationResult``.
        """
        fixture = copy.deepcopy(load_fixture("tool-runs/deeporigin.bulk-docking/quote"))

        inputs = body.get("inputs", {})
        num_ligands = len(inputs.get("ligands", []))
        if num_ligands < 1:
            num_ligands = 1

        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        fixture["executionId"] = MOCK_BULK_DOCKING_EXECUTION_ID
        fixture["createdAt"] = timestamp
        fixture["updatedAt"] = timestamp
        fixture["resourceId"] = _generate_resource_id()
        fixture["orgKey"] = org_key
        fixture["userInputs"] = inputs
        fixture["userOutputs"] = body.get("outputs", {})
        fixture["metadata"] = body.get("metadata", {})
        fixture["approveAmount"] = 0
        fixture["tool"] = {"key": tool_key, "version": tool_version}

        quotation = fixture.get("quotationResult", {})
        for sq in quotation.get("successfulQuotations", []):
            price_each = sq.get("priceEach", 0)
            sq["qty"] = num_ligands
            sq["priceTotal"] = round(price_each * num_ligands, 6)
            for pr in sq.get("pricingRecords", []):
                pr["qty"] = num_ligands
                pr["totalPrice"] = round(pr.get("priceEach", 0) * num_ligands, 6)

        for field in ("startedAt", "completedAt"):
            fixture.setdefault(field, None)

        return fixture

    @router.post("/tools/{org_key}/tools/{tool_key}/{tool_version}/executions")
    async def run_tool(
        org_key: str, tool_key: str, tool_version: str, request: Request
    ) -> dict[str, Any]:
        """Run a tool."""
        body = await request.json()

        approve_amount = body.get("approveAmount", 0)
        if approve_amount is None:
            approve_amount = 0

        inputs = body.get("inputs", {}) or {}
        n_lig = len(inputs.get("ligands") or [])
        # Explicit approveAmount 0 means quote-only; do not return a completed run DTO.
        quote_only = "approveAmount" in body and body.get("approveAmount") == 0
        # docking and pocket-finder declare ``sync`` inside ``inputs`` (matches
        # the toolbox tool-definitions and how the platform estimator reads it).
        if (
            tool_key == "deeporigin.docking"
            and inputs.get("sync") is True
            and n_lig == 1
            and not quote_only
        ):
            execution = _create_blocking_run_dto(
                org_key=org_key,
                tool_key=tool_key,
                tool_version=tool_version,
                body=body,
            )
            eid = execution["executionId"]
            executions[eid] = execution
            _inject_docking_tool_execution_results(execution)
            return _normalize_execution(execution)
        if (
            tool_key == "deeporigin.constrained-docking"
            and inputs.get("sync") is True
            and n_lig == 1
            and not quote_only
        ):
            execution = _create_blocking_run_dto(
                org_key=org_key,
                tool_key=tool_key,
                tool_version=tool_version,
                body=body,
            )
            eid = execution["executionId"]
            executions[eid] = execution
            _inject_docking_tool_execution_results(execution)
            return _normalize_execution(execution)
        if (
            tool_key == "deeporigin.pocket-finder"
            and inputs.get("sync") is True
            and not quote_only
        ):
            execution = _create_blocking_run_dto(
                org_key=org_key,
                tool_key=tool_key,
                tool_version=tool_version,
                body=body,
            )
            eid = execution["executionId"]
            executions[eid] = execution
            _inject_pocketfinder_tool_execution_results(execution)
            return _normalize_execution(execution)
        if tool_key == "deeporigin.system-prep" and body.get("sync") is True:
            execution = _create_blocking_run_dto(
                org_key=org_key,
                tool_key=tool_key,
                tool_version=tool_version,
                body=body,
            )
            eid = execution["executionId"]
            executions[eid] = execution
            _inject_sysprep_tool_execution_results(execution)
            return _normalize_execution(execution)
        if tool_key == "deeporigin.protein-prep" and not quote_only:
            execution = _create_blocking_run_dto(
                org_key=org_key,
                tool_key=tool_key,
                tool_version=tool_version,
                body=body,
            )
            eid = execution["executionId"]
            executions[eid] = execution
            _inject_protein_prep_tool_execution_results(execution)
            return _normalize_execution(execution)
        if tool_key == "deeporigin.konnektor":
            if quote_only:
                execution = _create_execution_dto(
                    tool_key=tool_key,
                    tool_version=tool_version,
                    org_key=org_key,
                    body=body,
                )
                executions[execution["executionId"]] = execution
                return _normalize_execution(execution)
            if body.get("sync") is True:
                execution = _create_blocking_run_dto(
                    org_key=org_key,
                    tool_key=tool_key,
                    tool_version=tool_version,
                    body=body,
                )
                inputs = body.get("inputs", {}) or {}
                ligand_inputs = inputs.get("ligands") or []
                network_type = str(inputs.get("network_type") or "mst")
                names = [
                    _konnektor_ligand_display_name(row, idx)
                    for idx, row in enumerate(ligand_inputs)
                    if isinstance(row, dict)
                ]
                edges = _konnektor_edges(names, network_type=network_type)
                eid = execution["executionId"]
                is_connected = len(names) <= 1 or len(edges) >= len(names) - 1
                execution["jobOutputs"] = {
                    "ligand_network": {
                        "edges": edges,
                        "is_connected": is_connected,
                        "network": {},
                        "network_html_file": f"tool-runs/{eid}/network.html",
                    },
                    "network_html": "<html><body>Konnektor network</body></html>",
                }
                executions[execution["executionId"]] = execution
                return _normalize_execution(execution)
        if tool_key == "deeporigin.enumerator" and body.get("sync") is True:
            execution = _build_enumerator_execution(
                org_key=org_key,
                tool_key=tool_key,
                tool_version=tool_version,
                body=body,
            )
            executions[execution["executionId"]] = execution
            return _normalize_execution(execution)
        if tool_key == "deeporigin.import-dataset" and body.get("sync") is True:
            execution = _build_pose_registration_execution(
                org_key=org_key,
                tool_key=tool_key,
                tool_version=tool_version,
                body=body,
            )
            eid = execution["executionId"]
            executions[eid] = execution
            _inject_result_explorer_records_from_outputs(
                tool_key=tool_key,
                tool_version=tool_version,
                execution_id=eid,
                job_outputs=execution.get("jobOutputs"),
            )
            return _normalize_execution(execution)
        if tool_key == "deeporigin.mol-props-protonation":
            execution = _build_protonation_execution(
                org_key=org_key,
                tool_key=tool_key,
                tool_version=tool_version,
                body=body,
            )
            executions[execution["executionId"]] = execution
            return _normalize_execution(execution)
        if tool_key == "deeporigin.admet-properties":
            execution = _build_admet_properties_execution(
                org_key=org_key,
                tool_key=tool_key,
                tool_version=tool_version,
                body=body,
            )
            if quote_only:
                execution["status"] = "Quoted"
                execution["jobOutputs"] = None
                execution["approveAmount"] = 0
                execution["startedAt"] = None
                execution["completedAt"] = None
                execution["progressReport"] = None
            executions[execution["executionId"]] = execution
            return _normalize_execution(execution)
        if tool_key == "deeporigin.mol-props-combined":
            execution = _build_combined_molprops_execution(
                org_key=org_key,
                tool_key=tool_key,
                tool_version=tool_version,
                body=body,
            )
            if quote_only:
                execution["status"] = "Quoted"
                execution["jobOutputs"] = None
                execution["approveAmount"] = 0
                execution["startedAt"] = None
                execution["completedAt"] = None
                execution["progressReport"] = None
            executions[execution["executionId"]] = execution
            return _normalize_execution(execution)
        if tool_key.startswith("deeporigin.mol-props-"):
            execution = _build_molprops_execution(
                org_key=org_key,
                tool_key=tool_key,
                tool_version=tool_version,
                body=body,
            )
            executions[execution["executionId"]] = execution
            return _normalize_execution(execution)
        if tool_key == "deeporigin.bulk-docking" and approve_amount == 0:
            execution = _create_bulk_docking_quote(
                org_key=org_key,
                tool_key=tool_key,
                tool_version=tool_version,
                body=body,
            )
        else:
            execution = _create_execution_dto(
                tool_key=tool_key,
                tool_version=tool_version,
                org_key=org_key,
                body=body,
            )

        execution_id = execution["executionId"]
        if tool_key == "deeporigin.bulk-docking":
            # New quote replaces any prior run; drop stale confirm/start times.
            execution_start_times.pop(execution_id, None)
        executions[execution_id] = execution

        return _normalize_execution(execution)

    return router
