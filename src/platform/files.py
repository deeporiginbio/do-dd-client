"""Files API wrapper for DeepOriginClient."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

from deeporigin.utils.core import _ensure_do_folder


class Files:
    """Files API wrapper.

    Provides access to files-related endpoints through the DeepOriginClient.
    """

    def __init__(self, client: DeepOriginClient) -> None:
        """Initialize Files wrapper.

        Args:
            client: The DeepOriginClient instance to use for API calls.
        """
        self._c = client

    def list_files_in_dir(
        self,
        *,
        file_path: str,
        recursive: bool = True,
        last_count: int | None = None,
        continuation_token: str | None = None,
        delimiter: str | None = None,
        max_keys: int | None = None,
        prefix: str | None = None,
    ) -> list[str]:
        """List files in a directory.

        Args:
            file_path: The path to the directory to list files from.
            recursive: If True, recursively list files in subdirectories.
                Defaults to True.
            last_count: Used for pagination - the last count of objects in the
                bucket. Defaults to None.
            continuation_token: Token for pagination. Defaults to None.
            delimiter: Used to group results by a common prefix (e.g., "/").
                Defaults to None.
            max_keys: Maximum number of keys to return (cannot exceed 1000).
                Defaults to None.
            prefix: Path prefix to filter results. Defaults to None.

        Returns:
            List of file paths found in the specified directory.
        """
        params: dict[str, str | int | bool] = {}
        if recursive:
            params["recursive"] = True
        if last_count is not None:
            params["last-count"] = str(last_count)
        if continuation_token is not None:
            params["continuation-token"] = continuation_token
        if delimiter is not None:
            params["delimiter"] = delimiter
        if max_keys is not None:
            params["max-orgKeys"] = max_keys
        if prefix is not None:
            params["prefix"] = prefix

        response = self._c.get_json(
            f"/files/{self._c.org_key}/directory/{file_path}",
            params=params,
        )

        # Extract file keys from the response
        files = []
        if "data" in response and isinstance(response["data"], list):
            for file_obj in response["data"]:
                if isinstance(file_obj, dict) and "Key" in file_obj:
                    files.append(file_obj["Key"])

        return files

    def upload_file(
        self,
        *,
        local_path: str | Path,
        remote_path: str | Path,
    ) -> dict:
        """Upload a single file to UFA.

        Args:
            local_path: The local path of the file to upload.
            remote_path: The remote path where the file will be stored.

        Returns:
            Dictionary containing the upload response (e.g., eTag, s3 metadata).
        """
        local_path_str = str(local_path)
        remote_path_str = str(remote_path)

        # Read file content
        with open(local_path_str, "rb") as f:
            file_content = f.read()

        # Prepare multipart form data
        files = {
            "file": (
                Path(local_path_str).name,
                file_content,
                "application/octet-stream",
            )
        }

        response = self._c._put(
            f"/files/{self._c.org_key}/{remote_path_str}",
            files=files,
        )

        return response.json()

    def download_file(
        self,
        *,
        remote_path: str,
        local_path: str | Path | None = None,
        lazy: bool = False,
    ) -> str:
        """Download a single file from UFA to ~/.deeporigin/, or some other local path.

        Args:
            remote_path: The remote path of the file to download.
            local_path: The local path to save the file to. If None, uses ~/.deeporigin/.
            lazy: If True, and the file exists locally, return the local path without downloading.

        Returns:
            The local path where the file was saved.
        """
        # Determine local path
        if local_path is None:
            do_folder = _ensure_do_folder()
            local_path = do_folder / remote_path
        else:
            local_path = Path(local_path)

        # Create parent directories
        local_path.parent.mkdir(parents=True, exist_ok=True)

        # Handle lazy mode
        if lazy and local_path.exists():
            return str(local_path)

        # Get signed URL
        signed_url_response = self._c.get_json(
            f"/files/{self._c.org_key}/signedUrl/{remote_path}",
        )

        if "url" not in signed_url_response:
            raise ValueError("Signed URL response missing 'url' field")

        signed_url = signed_url_response["url"]

        # Download file using httpx directly (signed_url is a complete URL)
        # Use a fresh client without base_url to avoid URL prefixing issues
        with httpx.Client() as download_client:
            download_response = download_client.get(signed_url)
            download_response.raise_for_status()

            # Save file
            with open(local_path, "wb") as f:
                f.write(download_response.content)

        return str(local_path)
