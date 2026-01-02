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
        Path object pointing to the file in the fixtures/files directory.
    """
    # Normalize path: remove leading slashes and resolve any '..' components
    normalized = remote_path.lstrip("/")
    # Use Path to handle path components safely
    # Files are stored in fixtures/files/ subdirectory
    fixture_path = fixtures_dir / "files" / normalized
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
        # Get the directory path in fixtures
        dir_path = _get_fixture_path(file_path, fixtures_dir)

        # Ensure the resolved path is within fixtures/files directory (prevent path traversal)
        files_dir = fixtures_dir / "files"
        files_dir_resolved = files_dir.resolve()
        try:
            dir_resolved = dir_path.resolve()
            if not str(dir_resolved).startswith(str(files_dir_resolved)):
                # Path traversal detected, return empty list
                return {"data": []}
        except (OSError, ValueError):
            # If resolution fails, return empty list
            return {"data": []}

        # Check if directory exists
        if not dir_path.exists() or not dir_path.is_dir():
            return {"data": []}

        # List files in the directory
        files: list[dict[str, str]] = []

        files_dir = fixtures_dir / "files"
        if recursive:
            # Recursively list all files
            for file_path_obj in dir_path.rglob("*"):
                if file_path_obj.is_file():
                    # Get relative path from fixtures/files directory
                    relative_path = file_path_obj.relative_to(files_dir)
                    files.append({"Key": str(relative_path)})
        else:
            # List only files directly in the directory (not subdirectories)
            for file_path_obj in dir_path.iterdir():
                if file_path_obj.is_file():
                    # Get relative path from fixtures/files directory
                    relative_path = file_path_obj.relative_to(files_dir)
                    files.append({"Key": str(relative_path)})

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

        # Ensure the resolved path is within fixtures/files directory (prevent path traversal)
        files_dir = fixtures_dir / "files"
        files_dir_resolved = files_dir.resolve()
        try:
            fixture_resolved = fixture_path.resolve()
            if not str(fixture_resolved).startswith(str(files_dir_resolved)):
                # Path traversal detected
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=404,
                    detail=f"File not found: {remote_path}, expected: {fixture_resolved}",
                )
        except (OSError, ValueError):
            from fastapi import HTTPException

            raise HTTPException(
                status_code=404,
                detail=f"File not found: {remote_path}, expected: {fixture_resolved}",
            ) from None

        # Try to serve from fixtures/files first
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

        # Ensure the resolved path is within fixtures/files directory (prevent path traversal)
        files_dir = fixtures_dir / "files"
        files_dir_resolved = files_dir.resolve()
        try:
            fixture_resolved = fixture_path.resolve()
            if not str(fixture_resolved).startswith(str(files_dir_resolved)):
                # Path traversal detected
                return {"eTag": "mock-etag", "key": remote_path}
        except (OSError, ValueError):
            return {"eTag": "mock-etag", "key": remote_path}

        # Create parent directories for convenience
        fixture_path.parent.mkdir(parents=True, exist_ok=True)

        # Check if file already exists in fixtures/files
        if fixture_path.exists():
            # File exists, nothing to do!
            return {"eTag": "mock-etag", "key": remote_path}

        # File doesn't exist - write it to disk so it's available for future downloads
        # This ensures files are automatically created during test runs
        fixture_path.write_bytes(content)

        return {"eTag": "mock-etag", "key": remote_path}

    @router.delete("/files/{org_key}/{remote_path:path}")
    def delete_file(org_key: str, remote_path: str) -> bool:
        """Delete a file."""
        # Check if file exists in fixtures/files
        fixture_path = _get_fixture_path(remote_path, fixtures_dir)
        file_exists = fixture_path.exists() or remote_path in file_storage

        # Remove file from storage if it exists (but don't delete from disk)
        if remote_path in file_storage:
            del file_storage[remote_path]

        # Return True if file exists (in fixtures or storage), False otherwise
        return file_exists

    return router
