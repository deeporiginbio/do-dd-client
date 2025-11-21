"""File-related routes for the mock server."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response


def _get_fixture_path(remote_path: str, fixtures_dir: Path) -> Path:
    """Get the fixture file path for a given remote path.

    Args:
        remote_path: The remote path from the API request.
        fixtures_dir: The fixtures directory path.

    Returns:
        Path object pointing to the file in the fixtures directory.
    """
    # Normalize path: remove leading slashes and resolve any '..' components
    normalized = remote_path.lstrip("/")
    # Use Path to handle path components safely
    fixture_path = fixtures_dir / normalized
    # Resolve to ensure we're within fixtures directory (prevent path traversal)
    try:
        resolved = fixture_path.resolve()
        # Ensure the resolved path is still within fixtures_dir
        fixtures_resolved = fixtures_dir.resolve()
        if not str(resolved).startswith(str(fixtures_resolved)):
            # If path traversal detected, just use the normalized path
            return fixture_path
        return resolved
    except (OSError, ValueError):
        # If resolution fails, return the normalized path
        return fixture_path


def create_files_router(
    file_storage: dict[str, bytes], fixtures_dir: Path
) -> APIRouter:
    """Create a router for file-related endpoints.

    Args:
        file_storage: In-memory storage for files.
        fixtures_dir: Directory where fixture files are stored.

    Returns:
        APIRouter instance with file-related routes.
    """
    router = APIRouter()

    @router.get("/files/{org_key}/directory/{file_path:path}")
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

    @router.get("/files/{org_key}/signedUrl/{remote_path:path}")
    def get_signed_url(
        org_key: str, remote_path: str, request: Request
    ) -> dict[str, str]:
        """Get a signed URL for downloading a file."""
        # Return a URL that points back to our server
        base_url = str(request.base_url).rstrip("/")
        return {"url": f"{base_url}/files/{org_key}/download/{remote_path}"}

    @router.get("/files/{org_key}/download/{remote_path:path}")
    def download_file(org_key: str, remote_path: str) -> Response:
        """Download a file."""
        # Normalize path and construct fixture path
        fixture_path = _get_fixture_path(remote_path, fixtures_dir)

        # Try to serve from fixtures first
        if fixture_path.exists():
            content = fixture_path.read_bytes()
        # Fall back to in-memory storage for backward compatibility
        elif remote_path in file_storage:
            content = file_storage[remote_path]
        else:
            # Raise error if file doesn't exist
            from fastapi import HTTPException

            raise HTTPException(
                status_code=404, detail=f"File not found: {remote_path}"
            )

        return Response(content=content, media_type="application/octet-stream")

    @router.put("/files/{org_key}/{remote_path:path}")
    async def upload_file(
        org_key: str,
        remote_path: str,
        request: Request,
    ) -> dict[str, str]:
        """Upload a file."""
        # Read the file content from the request body
        content = await request.body()

        # Store in file_storage for tracking uploaded files
        file_storage[remote_path] = content

        # Normalize path and construct fixture path
        fixture_path = _get_fixture_path(remote_path, fixtures_dir)

        # Check if file already exists in fixtures
        if fixture_path.exists():
            # File exists, nothing to do!
            return {"eTag": "mock-etag", "key": remote_path}

        # File doesn't exist - prompt dev to manually place it
        print("\n⚠️  Mock Server: File not found in fixtures")
        print(f"   Expected path: {fixture_path}")
        print(f"   Remote path: {remote_path}")
        print(f"   Please manually place the file at: {fixture_path}")
        print()

        # Create parent directories for convenience
        fixture_path.parent.mkdir(parents=True, exist_ok=True)

        # Return success anyway - the file will be there next time
        return {"eTag": "mock-etag", "key": remote_path}

    @router.delete("/files/{org_key}/{remote_path:path}")
    def delete_file(org_key: str, remote_path: str) -> bool:
        """Delete a file."""
        # Check if file exists in fixtures
        fixture_path = _get_fixture_path(remote_path, fixtures_dir)
        file_exists = fixture_path.exists() or remote_path in file_storage

        # Remove file from storage if it exists (but don't delete from disk)
        if remote_path in file_storage:
            del file_storage[remote_path]

        # Return True if file exists (in fixtures or storage), False otherwise
        return file_exists

    return router
