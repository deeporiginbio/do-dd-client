"""Tools-related routes for the mock server.

Covers ``/tools/...`` endpoints: tool definitions, clusters, and tool
executions (list / get / cancel / confirm / run).  All runnable work goes
through ``POST /tools/{org}/tools/{tool_key}/{tool_version}/executions``;
there is no longer a legacy ``/functions`` route.
"""

from __future__ import annotations

from collections.abc import Callable
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import string
from typing import Any
import uuid

from fastapi import APIRouter, HTTPException, Request

from ..constants import MOCK_BULK_DOCKING_EXECUTION_ID


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


def create_tools_router(
    *,
    executions: dict[str, dict[str, Any]],
    execution_start_times: dict[str, datetime],
    mock_execution_durations: dict[str, float],
    docking_speed: float,
    fixtures_dir: Path,
    load_fixture: Callable[[str], dict[str, Any]],
    results: list[dict[str, Any]],
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

        if status == "Succeeded":
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
            execution["status"] = "Succeeded"
            ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            execution["completedAt"] = ts
            execution["updatedAt"] = ts
            execution["progressReport"] = {"complete": 100}
            return execution["progressReport"]

        execution["progressReport"] = {"complete": complete}
        execution["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        return execution["progressReport"]

    def _get_progress_report(execution: dict[str, Any], tool_key: str) -> str | None:
        """Get progress report for an execution based on elapsed time."""
        status = execution.get("status")
        execution_id = execution.get("executionId")

        if tool_key == "deeporigin.bulk-docking":
            return _get_bulk_docking_progress_report(execution, execution_id)

        if status == "Succeeded":
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
            execution["status"] = "Succeeded"
            execution["completedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            execution["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            if tool_key == "deeporigin.docking":
                _inject_docking_tool_execution_results(execution)
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
        """Build a synchronous Succeeded execution DTO for a single ``run_tool`` POST.

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
            "status": "Succeeded",
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
            "deeporigin.system-prep": ("system", "preparedsystem"),
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

    def _inject_docking_tool_execution_results(execution: dict[str, Any]) -> None:
        """Mirror docking fixture poses into ``results`` when an execution completes."""
        eid = execution.get("executionId")
        tool = execution.get("tool") or {}
        tkey = tool.get("key")
        tool_version = tool.get("version", "0.0.0")
        if not eid or tkey != "deeporigin.docking":
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

        fixture = copy.deepcopy(load_fixture("tool-runs/deeporigin.system-prep/run"))
        outputs = _legacy_outputs_to_job_outputs(fixture)
        if not isinstance(outputs, dict):
            return

        user_inputs = execution.get("userInputs", {})
        protein = (
            user_inputs.get("protein", {}) if isinstance(user_inputs, dict) else {}
        )
        protein_id = protein.get("id") if isinstance(protein, dict) else None
        ligand = user_inputs.get("ligand1") or {}
        ligand_id = ligand.get("id") if isinstance(ligand, dict) else None
        system = outputs.get("system")
        if isinstance(system, dict):
            if protein_id is not None:
                system["protein_id"] = protein_id
            if ligand_id is not None:
                system["ligand1_id"] = ligand_id
        _inject_result_explorer_records_from_outputs(
            tool_key=tkey,
            tool_version=tool_version,
            execution_id=eid,
            job_outputs=outputs,
        )

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
        return {
            "key": tool_key,
            "name": f"Tool {tool_key}",
            "version": tool_version,
            "inputs": {},
            "executors": [],
            "description": "Mock tool definition",
            "toolManifestVersion": "1.0.0",
            "enabled": True,
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
        # docking and pocket-finder declare ``sync`` inside ``inputs`` (matches
        # the toolbox tool-definitions and how the platform estimator reads it).
        if (
            tool_key == "deeporigin.docking"
            and inputs.get("sync") is True
            and n_lig == 1
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
        if tool_key == "deeporigin.pocket-finder" and inputs.get("sync") is True:
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
        if tool_key == "deeporigin.mol-props-protonation":
            execution = _build_protonation_execution(
                org_key=org_key,
                tool_key=tool_key,
                tool_version=tool_version,
                body=body,
            )
            executions[execution["executionId"]] = execution
            return _normalize_execution(execution)
        if tool_key == "deeporigin.mol-props-combined":
            execution = _build_combined_molprops_execution(
                org_key=org_key,
                tool_key=tool_key,
                tool_version=tool_version,
                body=body,
            )
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
