"""Local test server that mimics the DeepOrigin Platform API.

This server runs locally during tests to provide mock responses for all
API endpoints used by the DeepOriginClient.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any
import uuid

from fastapi import FastAPI, Request
import uvicorn

from .routers import files


class MockServer:
    """Local test server for mocking DeepOrigin Platform API.

    When used in tests (via conftest.py), the server runs on port 4931.
    For standalone use, the port can be specified via the port parameter.
    """

    def __init__(self, port: int = 0, docking_speed: float = 1.0):
        """Initialize the test server.

        Args:
            port: Port to run the server on. If 0, uses any available port.
                Note: Tests use port 4931 (configured in conftest.py).
            docking_speed: Number of dockings to simulate per second for bulk-docking
                executions. Default is 1.0.
        """
        self.app = FastAPI()
        self.port = port
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None
        self._file_storage: dict[str, bytes] = {}
        self.host: str | None = None
        self._fixtures_dir = Path(__file__).parent.parent / "fixtures"
        self._fixture_cache: dict[str, dict[str, Any]] = {}
        # In-memory storage for executions
        self._executions: dict[str, dict[str, Any]] = {}
        self._execution_start_times: dict[str, datetime] = {}
        # Tool-specific mock execution durations (in seconds)
        self._mock_execution_durations: dict[str, float] = {
            "deeporigin.abfe-end-to-end": 30.0,  # seconds
        }
        self.docking_speed = docking_speed
        self._setup_routes()

    def _load_fixture(self, fixture_name: str) -> dict[str, Any]:
        """Load a JSON fixture file.

        Args:
            fixture_name: Name of the fixture file (without .json extension).
                Can include subdirectory paths, e.g., "abfe/execution-quoted".

        Returns:
            Dictionary containing the fixture data.

        Raises:
            FileNotFoundError: If the fixture file doesn't exist.
        """
        if fixture_name in self._fixture_cache:
            return self._fixture_cache[fixture_name]

        fixture_path = self._fixtures_dir / f"{fixture_name}.json"
        if not fixture_path.exists():
            raise FileNotFoundError(f"Fixture file not found: {fixture_path}")

        with open(fixture_path) as f:
            data = json.load(f)

        self._fixture_cache[fixture_name] = data
        return data

    def _load_execution_fixture(self, execution_id: str) -> dict[str, Any]:
        """Load an execution fixture by execution ID.

        Args:
            execution_id: The execution ID to load.

        Returns:
            Dictionary containing the execution fixture data.

        Raises:
            FileNotFoundError: If the execution fixture doesn't exist.
        """
        fixture_path = self._fixtures_dir / "executions" / f"{execution_id}.json"
        if not fixture_path.exists():
            raise FileNotFoundError(f"Execution fixture not found: {fixture_path}")

        with open(fixture_path) as f:
            return json.load(f)

    def _create_execution_dto(
        self,
        *,
        tool_key: str,
        tool_version: str,
        org_key: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Create an execution DTO dynamically.

        Args:
            tool_key: The tool key (e.g., "deeporigin.abfe-end-to-end").
            tool_version: The tool version.
            org_key: The organization key.
            body: The request body containing inputs, outputs, metadata, etc.

        Returns:
            Dictionary containing the execution DTO.
        """
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        # Generate execution ID
        execution_id = str(uuid.uuid4())

        # Determine initial status based on approveAmount
        approve_amount = body.get("approveAmount", 0)
        if approve_amount is None:
            approve_amount = 0

        if approve_amount == 0:
            status = "Quoted"
        else:
            # For approveAmount > 0, we'll handle later
            raise NotImplementedError(
                "approveAmount > 0 is not yet implemented in mock server"
            )

        # Build base execution DTO
        execution: dict[str, Any] = {
            "executionId": execution_id,
            "createdAt": timestamp,
            "updatedAt": timestamp,
            "resourceId": self._generate_resource_id(),
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

        # Load tool-specific fixtures using tool key in path
        tool_fixture_dir = self._fixtures_dir / tool_key
        if tool_fixture_dir.exists():
            # Load quotationResult fixture
            quotation_result_path = tool_fixture_dir / "quotation-result.json"
            if quotation_result_path.exists():
                try:
                    execution["quotationResult"] = self._load_fixture(
                        f"{tool_key}/quotation-result"
                    )
                except FileNotFoundError:
                    pass

            # Load billingTransaction fixture only if approveAmount > 0
            if approve_amount > 0:
                billing_transaction_path = tool_fixture_dir / "billing-transaction.json"
                if billing_transaction_path.exists():
                    try:
                        execution["billingTransaction"] = self._load_fixture(
                            f"{tool_key}/billing-transaction"
                        )
                    except FileNotFoundError:
                        pass

            # Set cluster ID to a generated UUID
            execution["cluster"] = {"id": str(uuid.uuid4())}

        # Set startedAt/completedAt to None initially
        execution["startedAt"] = None
        execution["completedAt"] = None

        return execution

    def _generate_resource_id(self) -> str:
        """Generate a resource ID.

        Returns:
            A random resource ID string.
        """
        import random
        import string

        chars = string.ascii_lowercase + string.digits
        return "".join(random.choice(chars) for _ in range(20))

    def _load_progress_reports(self, tool_key: str) -> list[dict[str, Any] | None]:
        """Load progress reports for a tool.

        Args:
            tool_key: The tool key.

        Returns:
            List of progress report objects.
        """
        # Map tool keys to progress report fixture paths
        # For now, ABFE uses abfe/progress-reports.json
        # Could be extended to use {tool_key}/progress-reports.json in the future
        if tool_key == "deeporigin.abfe-end-to-end":
            fixture_path = self._fixtures_dir / "abfe" / "progress-reports.json"
        else:
            # Default: try tool-specific path
            fixture_path = self._fixtures_dir / tool_key / "progress-reports.json"

        if not fixture_path.exists():
            return []

        with open(fixture_path) as f:
            return json.load(f)

    def _get_progress_report(
        self, execution: dict[str, Any], tool_key: str
    ) -> str | None:
        """Get progress report for an execution based on elapsed time.

        Args:
            execution: The execution object.
            tool_key: The tool key.

        Returns:
            JSON string of progress report, or None.
        """
        status = execution.get("status")
        execution_id = execution.get("executionId")

        # Special handling for bulk-docking tool
        if tool_key == "deeporigin.bulk-docking":
            return self._get_bulk_docking_progress_report(execution, execution_id)

        # For terminal states
        if status == "Succeeded":
            # Return final progress report
            progress_reports = self._load_progress_reports(tool_key)
            if progress_reports:
                final_report = progress_reports[-1]
                return json.dumps(final_report) if final_report is not None else None
            return None

        if status in ("Failed", "Cancelled"):
            # Return empty JSON object
            return json.dumps({})

        if status != "Running":
            # For other statuses (Quoted, etc.), no progress report
            return None

        # For Running status, calculate progress based on elapsed time
        if execution_id not in self._execution_start_times:
            return None

        start_time = self._execution_start_times[execution_id]
        now = datetime.now(timezone.utc)
        elapsed_seconds = (now - start_time).total_seconds()

        # Get duration for this tool
        duration = self._mock_execution_durations.get(tool_key, 300.0)

        # If elapsed time exceeds duration, transition to Succeeded
        if elapsed_seconds >= duration:
            execution["status"] = "Succeeded"
            execution["completedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            execution["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            # Return final progress report
            progress_reports = self._load_progress_reports(tool_key)
            if progress_reports:
                final_report = progress_reports[-1]
                return json.dumps(final_report) if final_report is not None else None
            return None

        # Calculate progress ratio (0.0 to 1.0)
        progress_ratio = min(elapsed_seconds / duration, 1.0)

        # Load progress reports
        progress_reports = self._load_progress_reports(tool_key)
        if not progress_reports:
            return None

        # Calculate index based on progress ratio
        max_index = len(progress_reports) - 1
        index = int(progress_ratio * max_index)
        index = max(0, min(index, max_index))  # Clamp to valid range

        # Get progress report at calculated index
        progress_report = progress_reports[index]
        return json.dumps(progress_report) if progress_report is not None else None

    def _get_bulk_docking_progress_report(
        self, execution: dict[str, Any], execution_id: str
    ) -> str | None:
        """Get progress report for bulk-docking execution.

        Args:
            execution: The execution object.
            execution_id: The execution ID.

        Returns:
            Newline-delimited text string with progress report, or None.
        """
        status = execution.get("status")

        # For terminal states, return final progress report
        if status == "Succeeded":
            user_inputs = execution.get("userInputs", {})
            smiles_list = user_inputs.get("smiles_list", [])
            if smiles_list:
                # Return all ligands docked
                lines = ["ligand docked"] * len(smiles_list)
                return "\n".join(lines)
            return None

        if status in ("Failed", "Cancelled"):
            return None

        if status != "Running":
            # For other statuses (Quoted, etc.), no progress report
            return None

        # For Running status, calculate progress based on elapsed time
        if execution_id not in self._execution_start_times:
            return None

        # Get smiles_list from userInputs
        user_inputs = execution.get("userInputs", {})
        smiles_list = user_inputs.get("smiles_list", [])
        if not smiles_list:
            return None

        # Calculate elapsed seconds since execution start
        start_time = self._execution_start_times[execution_id]
        now = datetime.now(timezone.utc)
        elapsed_seconds = (now - start_time).total_seconds()

        # Calculate number of dockings completed
        num_dockings = int(self.docking_speed * elapsed_seconds)
        num_dockings = min(num_dockings, len(smiles_list))

        # Generate progress report as newline-delimited text
        lines = ["ligand docked"] * num_dockings
        progress_report = "\n".join(lines)

        # If all ligands are docked, mark execution as Succeeded
        if num_dockings >= len(smiles_list):
            execution["status"] = "Succeeded"
            execution["completedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            execution["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        return progress_report

    def _get_molprops_fixture(self, smiles: str) -> dict[str, Any]:
        """Get molprops fixture data for a given SMILES string.

        Args:
            smiles: SMILES string to get fixture for.

        Returns:
            Dictionary containing molprops data for the SMILES.

        Note:
            Currently defaults to serotonin fixture. Can be extended to support
            multiple SMILES by adding more fixture files and a mapping.
        """
        # Map SMILES to fixture names (default to serotonin)
        smiles_to_fixture = {
            "NCCc1c[nH]c2ccc(O)cc12": "molprops_serotonin",
        }
        fixture_name = smiles_to_fixture.get(smiles, "molprops_serotonin")
        return self._load_fixture(fixture_name)

    def _setup_routes(self) -> None:
        """Set up all API routes."""
        # Include file-related routes
        files_router = files.create_files_router(self._file_storage, self._fixtures_dir)
        self.app.include_router(files_router)

        @self.app.get("/tools/protected/tools/definitions")
        def list_tools() -> dict[str, Any]:
            """List all tool definitions."""
            return {
                "data": [
                    {
                        "key": "test-tool",
                        "name": "Test Tool",
                        "version": "1.0.0",
                    }
                ]
            }

        @self.app.get("/tools/protected/tools/{tool_key}/definitions")
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

        @self.app.get("/tools/protected/functions/definitions")
        def list_functions() -> list[dict[str, Any]]:
            """List all function definitions."""
            return [
                {
                    "key": "test-function",
                    "name": "Test Function",
                    "version": "1.0.0",
                }
            ]

        @self.app.post("/tools/{org_key}/functions/{function_key}")
        def run_function(org_key: str, function_key: str) -> dict[str, str]:
            """Run a function."""
            return {"executionId": str(uuid.uuid4())}

        @self.app.post("/tools/{org_key}/functions/{function_key}/{version}")
        async def run_function_version(
            org_key: str, function_key: str, version: str, request: Request
        ) -> dict[str, Any] | list[dict[str, Any]]:
            """Run a specific version of a function."""
            # Handle mol-props functions
            if function_key.startswith("deeporigin.mol-props-"):
                # Extract property name (e.g., "logp" from "deeporigin.mol-props-logp")
                prop = function_key.replace("deeporigin.mol-props-", "")

                # Get request body to extract SMILES list
                body = await request.json()
                params = body.get("params", {})
                smiles_list = params.get("smiles_list", [])

                # Return response based on property requested
                # Each property endpoint returns a list of dicts with "smiles" key
                responses = []
                for smiles in smiles_list:
                    # Load fixture data for this SMILES
                    molprops_data = self._get_molprops_fixture(smiles)

                    response_item = {"smiles": smiles}

                    # Add the specific property data
                    if prop == "logp":
                        response_item["logP"] = molprops_data["logP"]
                    elif prop == "logd":
                        response_item["logD"] = molprops_data["logD"]
                    elif prop == "logs":
                        response_item["logS"] = molprops_data["logS"]
                    elif prop == "pains":
                        response_item["pains"] = molprops_data["pains"]
                    elif prop == "herg":
                        response_item["hERG"] = molprops_data["hERG"]
                    elif prop == "ames":
                        response_item["ames"] = molprops_data["ames"]
                    elif prop == "cyp":
                        response_item["cyp"] = molprops_data["cyp"]

                    responses.append(response_item)

                return responses

            # Handle system-prep function
            if function_key == "deeporigin.system-prep":
                # Return the sysprep response fixture
                return self._load_fixture("sysprep-response")

            # Default: return execution ID for other functions
            return {"executionId": str(uuid.uuid4())}

        @self.app.get("/tools/{org_key}/clusters")
        def list_clusters(org_key: str) -> dict[str, Any]:
            """List clusters."""
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

        @self.app.get("/entities/{org_key}/organizations/users")
        def list_organization_users(org_key: str) -> list[dict[str, Any]]:
            """List organization users."""
            return [
                {
                    "id": "576b2ec1-888c-4fc6-a137-66846e9ffaaf",
                    "createdAt": "2024-07-31T07:05:17.367Z",
                    "updatedAt": "2024-07-31T07:05:20.452Z",
                    "firstName": "user1@example.com",
                    "lastName": "user1@example.com",
                    "email": "user1@example.com",
                    "authId": "google-apps|user1@example.com",
                    "avatar": "https://s.gravatar.com/avatar/004cd3190c2f58ed8f192bdceb53aa6e?s=480&r=pg&d=https%3A%2F%2Fcdn.auth0.com%2Favatars%2Fag.png",
                    "title": "",
                    "industries": "",
                    "expertise": "",
                    "company": None,
                    "referralCode": None,
                    "emailNotificationsDisabled": None,
                    "notificationsDisabled": None,
                    "appNotificationsDisabled": None,
                },
                {
                    "id": "676b2ec1-888c-4fc6-a137-66846e9ffaaf",
                    "createdAt": "2024-08-01T07:05:17.367Z",
                    "updatedAt": "2024-08-01T07:05:20.452Z",
                    "firstName": "user2@example.com",
                    "lastName": "user2@example.com",
                    "email": "user2@example.com",
                    "authId": "google-apps|user2@example.com",
                    "avatar": "https://s.gravatar.com/avatar/004cd3190c2f58ed8f192bdceb53aa6e?s=480&r=pg&d=https%3A%2F%2Fcdn.auth0.com%2Favatars%2Fag.png",
                    "title": "",
                    "industries": "",
                    "expertise": "",
                    "company": None,
                    "referralCode": None,
                    "emailNotificationsDisabled": None,
                    "notificationsDisabled": None,
                    "appNotificationsDisabled": None,
                },
            ]

        @self.app.get("/tools/{org_key}/tools/executions")
        def list_executions(
            org_key: str,
            page: int = 0,
            pageSize: int = 100,
            limit: int = 100,
            filter: str | None = None,
        ) -> dict[str, Any]:
            """List tool executions."""
            # Parse filter if provided
            filter_dict = None
            requested_tool_key = None
            requested_statuses = None

            if filter:
                filter_dict = json.loads(filter)
                # Extract tool_key from filter if present
                if "tool" in filter_dict:
                    tool_filter = filter_dict["tool"]
                    if (
                        "toolManifest" in tool_filter
                        and "key" in tool_filter["toolManifest"]
                    ):
                        requested_tool_key = tool_filter["toolManifest"]["key"]
                    elif "key" in tool_filter:
                        requested_tool_key = tool_filter["key"]

                # Extract status filter if present
                if "status" in filter_dict:
                    status_filter = filter_dict["status"]
                    if "$in" in status_filter:
                        requested_statuses = status_filter["$in"]

            # Get all executions from in-memory store
            all_executions = list(self._executions.values())

            # Filter by org_key
            filtered_executions = [
                exec for exec in all_executions if exec.get("orgKey") == org_key
            ]

            # Apply tool_key filter if provided
            if requested_tool_key:
                filtered_executions = [
                    exec
                    for exec in filtered_executions
                    if exec.get("tool", {}).get("key") == requested_tool_key
                ]

            # Apply status filter if provided
            if requested_statuses:
                filtered_executions = [
                    exec
                    for exec in filtered_executions
                    if exec.get("status") in requested_statuses
                ]

            # Apply metadata filter if present
            if filter_dict and "metadata" in filter_dict:
                metadata_filter = filter_dict["metadata"]
                if metadata_filter.get("$exists") is True:
                    # Only include executions where metadata exists and is not None
                    filtered_executions = [
                        exec
                        for exec in filtered_executions
                        if exec.get("metadata") is not None
                    ]

            # Sort by createdAt (most recent first) for consistent ordering
            filtered_executions.sort(key=lambda x: x.get("createdAt", ""), reverse=True)

            # Apply pagination
            page_size = pageSize if pageSize else limit
            start_idx = page * page_size
            end_idx = start_idx + page_size
            paginated_executions = filtered_executions[start_idx:end_idx]

            # Return copies to avoid modifying the stored executions
            return {
                "count": len(filtered_executions),
                "data": [exec.copy() for exec in paginated_executions],
            }

        @self.app.get("/tools/{org_key}/tools/executions/{execution_id}")
        def get_execution(org_key: str, execution_id: str) -> dict[str, Any]:
            """Get execution by ID."""
            # Check in-memory storage
            if execution_id not in self._executions:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=404, detail=f"Execution {execution_id} not found"
                )

            execution = self._executions[execution_id].copy()
            # Update timestamps if execution has been started
            if execution_id in self._execution_start_times:
                start_time = self._execution_start_times[execution_id]
                execution["startedAt"] = (
                    start_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                )
                now = datetime.now(timezone.utc)
                execution["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

            # Get progress report based on execution status and elapsed time
            tool_key = execution.get("tool", {}).get("key")
            if tool_key:
                progress_report = self._get_progress_report(execution, tool_key)
                execution["progressReport"] = progress_report

            # Update execution in memory if status was changed (e.g., auto-completed)
            self._executions[execution_id] = execution

            return execution

        @self.app.patch("/tools/{org_key}/tools/executions/{execution_id}:cancel")
        def cancel_execution(org_key: str, execution_id: str) -> dict[str, Any]:
            """Cancel an execution."""
            # Get execution from memory
            if execution_id not in self._executions:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=404, detail=f"Execution {execution_id} not found"
                )

            execution = self._executions[execution_id]

            # Update status to Cancelled
            execution["status"] = "Cancelled"

            # Update updatedAt timestamp
            now = datetime.now(timezone.utc)
            execution["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

            # Update in memory storage
            self._executions[execution_id] = execution

            return execution.copy()

        @self.app.patch("/tools/{org_key}/tools/executions/{execution_id}:confirm")
        def confirm_execution(org_key: str, execution_id: str) -> dict[str, Any]:
            """Confirm an execution."""
            # Get execution from memory
            if execution_id not in self._executions:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=404, detail=f"Execution {execution_id} not found"
                )

            execution = self._executions[execution_id]

            # Update status to Running
            execution["status"] = "Running"

            # Track start time
            now = datetime.now(timezone.utc)
            self._execution_start_times[execution_id] = now
            execution["startedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

            # Update updatedAt timestamp
            execution["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

            # Update in memory storage
            self._executions[execution_id] = execution

            return execution.copy()

        @self.app.post("/tools/{org_key}/tools/{tool_key}/{tool_version}/executions")
        async def run_tool(
            org_key: str, tool_key: str, tool_version: str, request: Request
        ) -> dict[str, Any]:
            """Run a tool."""
            body = await request.json()

            # Create execution DTO dynamically
            execution = self._create_execution_dto(
                tool_key=tool_key,
                tool_version=tool_version,
                org_key=org_key,
                body=body,
            )

            # Store execution in memory
            execution_id = execution["executionId"]
            self._executions[execution_id] = execution

            return execution

        @self.app.get("/health")
        def health() -> dict[str, str]:
            """Health check endpoint."""
            return {"status": "ok"}

    def start(self) -> tuple[str, int]:
        """Start the test server.

        Returns:
            Tuple of (host, port) where the server is running.
        """
        config = uvicorn.Config(
            self.app,
            host="127.0.0.1",
            port=self.port,
            log_level="error",  # Suppress uvicorn logs during tests
        )
        self.server = uvicorn.Server(config)

        def run_server():
            self.server.run()

        self.thread = threading.Thread(target=run_server)
        self.thread.daemon = True
        self.thread.start()

        # Wait for server to start
        import time

        max_wait = 5.0
        waited = 0.0
        while not self.server.started and waited < max_wait:
            time.sleep(0.1)
            waited += 0.1

        if not self.server.started:
            raise RuntimeError("Test server failed to start")

        # Store host and port (port is already known since we set it)
        self.host = "127.0.0.1"

        return ("127.0.0.1", self.port)

    def stop(self) -> None:
        """Stop the test server."""
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=2.0)
