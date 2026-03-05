"""Tools-related routes for the mock server.

Covers /tools/... endpoints: tool definitions, function runs, clusters,
and executions (list / get / cancel / confirm / run).
"""

from __future__ import annotations

from collections.abc import Callable
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import string
from typing import Any
import uuid

from fastapi import APIRouter, HTTPException, Request


def _generate_resource_id() -> str:
    """Generate a random resource ID.

    Returns:
        A random 20-character alphanumeric string.
    """
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choice(chars) for _ in range(20))


def _replace_ids_in_function_outputs(
    obj: object, protein_id: str | None = None, ligand_id: str | None = None
) -> object:
    """Recursively replace protein/ligand ID values in functionOutputs.

    Handles both ``ligand_id`` and ``ligand1_id`` keys so that the
    fixture works for both legacy and current system-prep schemas.

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
                result[key] = _replace_ids_in_function_outputs(
                    value, protein_id=protein_id, ligand_id=ligand_id
                )
        return result
    elif isinstance(obj, list):
        return [
            _replace_ids_in_function_outputs(
                item, protein_id=protein_id, ligand_id=ligand_id
            )
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
        results: Shared result-explorer record list; function runs that
            produce outputs will inject records here so they are visible
            via the result-explorer search endpoint.

    Returns:
        APIRouter instance with tools-related routes.
    """
    router = APIRouter()

    # -- helper closures (capture shared state) --------------------------------

    def _load_progress_reports(tool_key: str) -> list[dict[str, Any] | None]:
        """Load progress reports for a tool."""
        if tool_key == "deeporigin.abfe-end-to-end":
            fixture_path = fixtures_dir / "abfe" / "progress-reports.json"
        else:
            fixture_path = fixtures_dir / tool_key / "progress-reports.json"

        if not fixture_path.exists():
            return []

        with open(fixture_path) as f:
            return json.load(f)

    def _get_bulk_docking_progress_report(
        execution: dict[str, Any], execution_id: str
    ) -> str | None:
        """Get progress report for bulk-docking execution."""
        status = execution.get("status")

        if status == "Succeeded":
            user_inputs = execution.get("userInputs", {})
            smiles_list = user_inputs.get("smiles_list", [])
            if smiles_list:
                lines = ["ligand docked"] * len(smiles_list)
                return "\n".join(lines)
            return None

        if status in ("Failed", "Cancelled"):
            return None

        if status != "Running":
            return None

        if execution_id not in execution_start_times:
            return None

        user_inputs = execution.get("userInputs", {})
        smiles_list = user_inputs.get("smiles_list", [])
        if not smiles_list:
            return None

        start_time = execution_start_times[execution_id]
        now = datetime.now(timezone.utc)
        elapsed_seconds = (now - start_time).total_seconds()

        num_dockings = int(docking_speed * elapsed_seconds)
        num_dockings = min(num_dockings, len(smiles_list))

        lines = ["ligand docked"] * num_dockings
        progress_report = "\n".join(lines)

        if num_dockings >= len(smiles_list):
            execution["status"] = "Succeeded"
            execution["completedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            execution["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        return progress_report

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
        }

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

    def _get_protonation_response(
        *, smiles: str, ph: float, inputs: dict[str, Any], body: dict[str, Any]
    ) -> dict[str, Any]:
        """Get protonation response for a given SMILES and pH."""
        skeleton_path = fixtures_dir / "function-runs" / "skeleton.json"
        with open(skeleton_path) as f:
            response = json.load(f)

        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        response["id"] = str(uuid.uuid4())
        response["createdAt"] = timestamp
        response["updatedAt"] = timestamp

        response["userInputs"] = {"inputs": inputs}
        if "clusterId" in body:
            response["userInputs"]["clusterId"] = body["clusterId"]

        expected_smiles = "C=CCCn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O"
        if smiles != expected_smiles:
            protonation_data = {
                "smiles": smiles,
                "pH": ph,
                "filter_percentage": inputs.get("filter_percentage", 1),
                "protonation_states": {
                    "smiles_list": [smiles],
                    "concentration_list": [99.93319834034459],
                },
            }
        elif ph < 8:
            protonation_data = {
                "smiles": expected_smiles,
                "pH": ph,
                "filter_percentage": inputs.get("filter_percentage", 1),
                "protonation_states": {
                    "smiles_list": [expected_smiles],
                    "concentration_list": [99.93319834034459],
                },
            }
        else:
            protonation_data = {
                "smiles": expected_smiles,
                "pH": ph,
                "filter_percentage": inputs.get("filter_percentage", 1),
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

        response["functionOutputs"] = protonation_data
        return response

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

    @router.get("/tools/protected/functions/definitions")
    def list_functions() -> list[dict[str, Any]]:
        """List all function definitions."""
        return [
            {
                "id": "test-function-id",
                "key": "test-function",
                "name": "Test Function",
                "version": "1.0.0",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
                "functionManifest": {},
                "enabled": True,
                "manifestBody": {},
                "billingCode": "test-billing-code",
                "resourceId": "test-resource-id",
            }
        ]

    async def _handle_function_run(
        function_key: str, request: Request
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Handle function execution logic shared between versioned and non-versioned endpoints."""
        body = await request.json()
        from deeporigin.utils.core import hash_dict, normalize_function_body

        normalized_body = normalize_function_body(body)
        body_hash = hash_dict(normalized_body)

        try:
            response = load_fixture(f"function-runs/{function_key}/{body_hash}")
        except FileNotFoundError:
            if function_key == "deeporigin.mol-props-protonation":
                inputs = body.get("inputs", body.get("params", {}))
                smiles = inputs.get("smiles", "")
                ph = inputs.get("pH", 7.4)
                return _get_protonation_response(
                    smiles=smiles, ph=ph, inputs=inputs, body=body
                )
            raise FileNotFoundError(
                f"No fixture found for function '{function_key}' with request hash '{body_hash}'. "
                f"Please create a fixture at: function-runs/{function_key}/{body_hash}.json"
            ) from None

        # Make a deep copy to avoid mutating the cached fixture
        response = copy.deepcopy(response)

        if isinstance(response, dict):
            response["id"] = str(uuid.uuid4())

        # Replace protein_id and ligand_id in functionOutputs with IDs from userInputs
        # This is needed because normalize_function_body strips IDs before hashing,
        # so different IDs hash to the same value
        inputs = body.get("inputs", body.get("params", {}))
        protein = inputs.get("protein", {})
        protein_id = protein.get("id") if isinstance(protein, dict) else None
        ligand = inputs.get("ligand1", inputs.get("ligand", {}))
        ligand_id = ligand.get("id") if isinstance(ligand, dict) else None

        if protein_id or ligand_id:
            if isinstance(response, dict):
                function_outputs = response.get("functionOutputs")
                if function_outputs is not None:
                    response["functionOutputs"] = _replace_ids_in_function_outputs(
                        function_outputs, protein_id=protein_id, ligand_id=ligand_id
                    )
            elif isinstance(response, list):
                for item in response:
                    if isinstance(item, dict):
                        function_outputs = item.get("functionOutputs")
                        if function_outputs is not None:
                            item["functionOutputs"] = _replace_ids_in_function_outputs(
                                function_outputs,
                                protein_id=protein_id,
                                ligand_id=ligand_id,
                            )

        _inject_result_explorer_records(function_key, response)

        return response

    def _inject_result_explorer_records(
        function_key: str, response: dict[str, Any] | list[dict[str, Any]]
    ) -> None:
        """Populate the shared result-explorer store from function outputs.

        When a function run produces structured outputs (e.g. pockets, poses),
        this mirrors the production MQ flow by creating result-explorer records
        so that subsequent result-explorer queries return the data.
        """
        if not isinstance(response, dict):
            return

        function_outputs = response.get("functionOutputs")
        if not isinstance(function_outputs, dict):
            return

        execution_id = response.get("id", str(uuid.uuid4()))

        tool_key = function_key
        tool_version = "0.0.0"
        func_info = response.get("function", {})
        manifest = func_info.get("manifestBody", {})
        if manifest.get("version"):
            tool_version = manifest["version"]

        # Maps function keys to the field in functionOutputs that should
        # be mirrored into the result-explorer store.  This emulates the
        # production message-queue flow where function outputs are written
        # to the result-explorer table asynchronously.  When adding a new
        # function type, add an entry here so that downstream queries
        # (e.g. LigandSet.from_docking_result, Pocket.from_result) can
        # find the records via result-explorer/search.
        output_key_map = {
            "deeporigin.pocketfinder": "pockets",
            "deeporigin.docking": "poses",
            "deeporigin.system-prep": "system",
        }

        output_key = output_key_map.get(function_key)
        if not output_key:
            return

        output_value = function_outputs.get(output_key)
        if output_value is None:
            return

        # Some functions produce a list of items (pockets, poses) while
        # others produce a single dict (system-prep).  Normalise to a
        # list so the injection logic is uniform.
        items = output_value if isinstance(output_value, list) else [output_value]
        for item in items:
            record = {
                "id": "08" + str(uuid.uuid4()).replace("-", "").upper()[:11],
                "tool_id": tool_key,
                "tool_version": tool_version,
                "data": dict(item),
                "compute_job_id": execution_id,
            }
            results.append(record)

    @router.post("/tools/{org_key}/functions/{function_key}")
    async def run_function(
        org_key: str, function_key: str, request: Request
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Run a function (latest version)."""
        return await _handle_function_run(function_key, request)

    @router.post("/tools/{org_key}/functions/{function_key}/{version}")
    async def run_function_version(
        org_key: str, function_key: str, version: str, request: Request
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Run a specific version of a function."""
        return await _handle_function_run(function_key, request)

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

    @router.post("/tools/{org_key}/tools/{tool_key}/{tool_version}/executions")
    async def run_tool(
        org_key: str, tool_key: str, tool_version: str, request: Request
    ) -> dict[str, Any]:
        """Run a tool."""
        body = await request.json()

        execution = _create_execution_dto(
            tool_key=tool_key,
            tool_version=tool_version,
            org_key=org_key,
            body=body,
        )

        execution_id = execution["executionId"]
        executions[execution_id] = execution

        return _normalize_execution(execution)

    return router
