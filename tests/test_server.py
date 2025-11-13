"""Local test server that mimics the DeepOrigin Platform API.

This server runs locally during tests to provide mock responses for all
API endpoints used by the DeepOriginClient.
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import Response
import uvicorn


class TestServer:
    """Local test server for mocking DeepOrigin Platform API."""

    def __init__(self, port: int = 0):
        """Initialize the test server.

        Args:
            port: Port to run the server on. If 0, uses an available port.
        """
        self.app = FastAPI()
        self.port = port
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None
        self._file_storage: dict[str, bytes] = {}
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Set up all API routes."""

        @self.app.get("/files/{org_key}/directory/{file_path:path}")
        def list_files(
            org_key: str, file_path: str, recursive: bool = False
        ) -> dict[str, Any]:
            """List files in a directory."""
            # Return mock file list
            files = [
                {"Key": f"{file_path}file1.txt"},
                {"Key": f"{file_path}file2.txt"},
            ]
            if recursive:
                files.append({"Key": f"{file_path}subdir/file3.txt"})
            return {"data": files}

        @self.app.get("/files/{org_key}/signedUrl/{remote_path:path}")
        def get_signed_url(
            org_key: str, remote_path: str, request: Request
        ) -> dict[str, str]:
            """Get a signed URL for downloading a file."""
            # Return a URL that points back to our server
            base_url = str(request.base_url).rstrip("/")
            return {"url": f"{base_url}/files/{org_key}/download/{remote_path}"}

        @self.app.get("/files/{org_key}/download/{remote_path:path}")
        def download_file(org_key: str, remote_path: str) -> Response:
            """Download a file."""
            # Return file content if stored, otherwise create dummy content
            if remote_path in self._file_storage:
                content = self._file_storage[remote_path]
            else:
                content = b"test file content"
            return Response(content=content, media_type="application/octet-stream")

        @self.app.put("/files/{org_key}/{remote_path:path}")
        async def upload_file(
            org_key: str,
            remote_path: str,
            request: Request,
        ) -> dict[str, str]:
            """Upload a file."""
            # Try to get file from form data, otherwise read body
            content_type = request.headers.get("content-type", "")
            if "multipart/form-data" in content_type:
                form = await request.form()
                if "file" in form:
                    file_obj = form["file"]
                    if hasattr(file_obj, "read"):
                        file_data = await file_obj.read()
                    else:
                        file_data = (
                            file_obj.encode() if isinstance(file_obj, str) else b""
                        )
                else:
                    file_data = await request.body()
            else:
                file_data = await request.body()
            self._file_storage[remote_path] = file_data
            return {"eTag": "mock-etag", "key": remote_path}

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

        @self.app.post("/tools/{org_key}/functions/{function_key}")
        def run_function(org_key: str, function_key: str) -> dict[str, str]:
            """Run a function."""
            return {"executionId": f"exec-{function_key}-123"}

        @self.app.post("/tools/{org_key}/functions/{function_key}/{version}")
        def run_function_version(
            org_key: str, function_key: str, version: str
        ) -> dict[str, str]:
            """Run a specific version of a function."""
            return {"executionId": f"exec-{function_key}-{version}-123"}

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

        @self.app.get("/tools/{org_key}/tools/executions")
        def list_executions(org_key: str, limit: int = 100) -> dict[str, Any]:
            """List tool executions."""
            return {
                "data": [
                    {
                        "executionId": f"exec-{i}",
                        "status": "Succeeded",
                        "toolKey": "test-tool",
                    }
                    for i in range(min(limit, 10))
                ]
            }

        @self.app.get("/tools/{org_key}/tools/executions/{execution_id}")
        def get_execution(org_key: str, execution_id: str) -> dict[str, str]:
            """Get execution by ID."""
            return {
                "executionId": execution_id,
                "status": "Succeeded",
                "toolKey": "test-tool",
            }

        @self.app.patch("/tools/{org_key}/tools/executions/{execution_id}:cancel")
        def cancel_execution(org_key: str, execution_id: str) -> dict[str, str]:
            """Cancel an execution."""
            return {"status": "Cancelled"}

        @self.app.patch("/tools/{org_key}/tools/executions/{execution_id}:confirm")
        def confirm_execution(org_key: str, execution_id: str) -> dict[str, str]:
            """Confirm an execution."""
            return {"status": "Confirmed"}

        @self.app.post("/tools/{org_key}/tools/{tool_key}/{tool_version}/executions")
        def run_tool(org_key: str, tool_key: str, tool_version: str) -> dict[str, str]:
            """Run a tool."""
            return {"executionId": f"exec-{tool_key}-{tool_version}-123"}

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

        # Wait for server to start and get the actual port
        import time

        max_wait = 5.0
        waited = 0.0
        while not self.server.started and waited < max_wait:
            time.sleep(0.1)
            waited += 0.1

        if not self.server.started:
            raise RuntimeError("Test server failed to start")

        # Get the actual port from the server
        if hasattr(self.server, "servers") and self.server.servers:
            server_socket = self.server.servers[0].sockets[0]
            actual_port = server_socket.getsockname()[1]
        else:
            # Fallback: use the configured port
            actual_port = self.port if self.port > 0 else 8000

        return ("127.0.0.1", actual_port)

    def stop(self) -> None:
        """Stop the test server."""
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=2.0)
