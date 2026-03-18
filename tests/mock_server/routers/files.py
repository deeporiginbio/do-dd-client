"""File-related routes for the mock server."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any
import zipfile

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
    normalized = remote_path.lstrip("/")
    fixture_path = fixtures_dir / "files" / normalized
    try:
        resolved = fixture_path.resolve()
        fixtures_resolved = fixtures_dir.resolve()
        if not str(resolved).startswith(str(fixtures_resolved)):
            return fixture_path
        return resolved
    except (OSError, ValueError):
        return fixture_path


def _resolve_file_content(
    remote_path: str,
    fixtures_dir: Path,
    file_storage: dict[str, bytes],
) -> bytes:
    """Resolve file content from fixtures or in-memory storage.

    Args:
        remote_path: The remote path from the API request.
        fixtures_dir: The fixtures directory path.
        file_storage: In-memory storage for files.

    Returns:
        The file content as bytes.

    Raises:
        fastapi.HTTPException: If the file is not found.
    """
    from fastapi import HTTPException

    normalized = remote_path.lstrip("/").replace("\\", "/")
    brd_fixture = fixtures_dir / "files" / "tests" / "brd.pdb"
    if (
        brd_fixture.is_file()
        and normalized.endswith(".pdb")
        and "entities/proteins/" in normalized
    ):
        return brd_fixture.read_bytes()

    fixture_path = _get_fixture_path(remote_path, fixtures_dir)

    files_dir = fixtures_dir / "files"
    files_dir_resolved = files_dir.resolve()
    try:
        fixture_resolved = fixture_path.resolve()
        if not str(fixture_resolved).startswith(str(files_dir_resolved)):
            raise HTTPException(
                status_code=404,
                detail=f"File not found: {remote_path}",
            )
    except (OSError, ValueError):
        raise HTTPException(
            status_code=404, detail=f"File not found: {remote_path}"
        ) from None

    if fixture_path.exists() and fixture_path.is_file():
        return fixture_path.read_bytes()
    if remote_path in file_storage:
        return file_storage[remote_path]

    raise HTTPException(status_code=404, detail=f"File not found: {remote_path}")


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

    # --- Non-parameterized routes (must be registered first) ---

    @router.get("/files/health")
    def files_health() -> dict[str, str]:
        """Health check for the files service."""
        return {"status": "ok"}

    @router.get("/files/version")
    def files_version() -> dict[str, str]:
        """Get the version of the files service."""
        return {"version": "mock-1.0.0"}

    # --- Routes with specific sub-paths (before catch-all) ---

    @router.get("/files/{org_key}/directory/{file_path:path}")
    def list_files(
        org_key: str, file_path: str, recursive: bool = False
    ) -> dict[str, Any]:
        """List files in a directory."""
        dir_path = _get_fixture_path(file_path, fixtures_dir)

        files_dir = fixtures_dir / "files"
        files_dir_resolved = files_dir.resolve()
        try:
            dir_resolved = dir_path.resolve()
            if not str(dir_resolved).startswith(str(files_dir_resolved)):
                return {"data": []}
        except (OSError, ValueError):
            return {"data": []}

        if not dir_path.exists() or not dir_path.is_dir():
            return {"data": []}

        files: list[dict[str, str]] = []

        files_dir = fixtures_dir / "files"
        if recursive:
            for file_path_obj in dir_path.rglob("*"):
                if file_path_obj.is_file():
                    relative_path = file_path_obj.relative_to(files_dir)
                    files.append({"Key": str(relative_path)})
        else:
            for file_path_obj in dir_path.iterdir():
                if file_path_obj.is_file():
                    relative_path = file_path_obj.relative_to(files_dir)
                    files.append({"Key": str(relative_path)})

        return {"data": files}

    @router.get("/files/{org_key}/signedUrl/{remote_path:path}")
    def get_signed_url(
        org_key: str, remote_path: str, request: Request
    ) -> dict[str, str]:
        """Get a signed URL for downloading a file."""
        base_url = str(request.base_url).rstrip("/")
        return {"url": f"{base_url}/files/{org_key}/download/{remote_path}"}

    @router.get("/files/{org_key}/zip/{file_path:path}")
    def get_file_as_zip(org_key: str, file_path: str) -> Response:
        """Download a directory as a ZIP archive."""
        dir_path = _get_fixture_path(file_path, fixtures_dir)

        files_dir = fixtures_dir / "files"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            if dir_path.exists() and dir_path.is_dir():
                for fp in dir_path.rglob("*"):
                    if fp.is_file():
                        arcname = str(fp.relative_to(files_dir))
                        zf.write(fp, arcname)
        buf.seek(0)

        return Response(content=buf.getvalue(), media_type="application/zip")

    @router.get("/files/{org_key}/download/{remote_path:path}")
    def download_file_via_signed_url(org_key: str, remote_path: str) -> Response:
        """Download a file (used by signed-URL redirect)."""
        content = _resolve_file_content(remote_path, fixtures_dir, file_storage)
        return Response(content=content, media_type="application/octet-stream")

    # --- Catch-all routes ---

    @router.put("/files/{org_key}/{remote_path:path}")
    async def upload_file(
        org_key: str,
        remote_path: str,
        request: Request,
    ) -> dict[str, str]:
        """Upload a file."""
        content = await request.body()
        file_storage[remote_path] = content

        fixture_path = _get_fixture_path(remote_path, fixtures_dir)

        files_dir = fixtures_dir / "files"
        files_dir_resolved = files_dir.resolve()
        try:
            fixture_resolved = fixture_path.resolve()
            if not str(fixture_resolved).startswith(str(files_dir_resolved)):
                return {"eTag": "mock-etag", "key": remote_path}
        except (OSError, ValueError):
            return {"eTag": "mock-etag", "key": remote_path}

        fixture_path.parent.mkdir(parents=True, exist_ok=True)

        if fixture_path.exists():
            return {"eTag": "mock-etag", "key": remote_path}

        fixture_path.write_bytes(content)

        return {"eTag": "mock-etag", "key": remote_path}

    @router.post("/files/{org_key}/{remote_path:path}")
    async def upload_file_from_url(
        org_key: str,
        remote_path: str,
        request: Request,
    ) -> dict[str, str]:
        """Upload a file from a URL (mock: just records the request)."""
        body = await request.json()
        source_url = body.get("url", "")
        file_storage[remote_path] = source_url.encode()
        return {"eTag": "mock-etag", "key": remote_path, "sourceUrl": source_url}

    @router.head("/files/{org_key}/{remote_path:path}")
    def head_file(org_key: str, remote_path: str) -> Response:
        """Return file metadata headers without the body."""
        content = _resolve_file_content(remote_path, fixtures_dir, file_storage)
        return Response(
            content=b"",
            headers={
                "content-length": str(len(content)),
                "content-type": "application/octet-stream",
            },
        )

    @router.get("/files/{org_key}/{remote_path:path}")
    def get_file(org_key: str, remote_path: str) -> Response:
        """Download a file directly."""
        content = _resolve_file_content(remote_path, fixtures_dir, file_storage)
        return Response(content=content, media_type="application/octet-stream")

    @router.delete("/files/{org_key}/{remote_path:path}")
    def delete_file(org_key: str, remote_path: str) -> bool:
        """Delete a file."""
        fixture_path = _get_fixture_path(remote_path, fixtures_dir)
        file_exists = fixture_path.exists() or remote_path in file_storage

        if remote_path in file_storage:
            del file_storage[remote_path]

        return file_exists

    return router
