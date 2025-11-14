"""Files API wrapper for DeepOriginClient."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from tqdm import tqdm

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
        delimiter: str | None = None,
        max_keys: int | None = None,
        prefix: str | None = None,
    ) -> list[str]:
        """List files in a directory.

        Automatically handles pagination using continuation tokens. All pages
        are fetched and combined into a single list.

        Args:
            file_path: The path to the directory to list files from.
            recursive: If True, recursively list files in subdirectories.
                Defaults to True.
            last_count: Used for pagination - the last count of objects in the
                bucket. Defaults to None.
            delimiter: Used to group results by a common prefix (e.g., "/").
                Defaults to None.
            max_keys: Page size (cannot exceed 1000).
                Defaults to None.
            prefix: Path prefix to filter results. Defaults to None.

        Returns:
            List of file paths found in the specified directory.
        """
        all_files: list[str] = []
        continuation_token: str | None = None

        while True:
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
            if "data" in response and isinstance(response["data"], list):
                for file_obj in response["data"]:
                    if isinstance(file_obj, dict) and "Key" in file_obj:
                        all_files.append(file_obj["Key"])

            # Check for continuation token in response
            continuation_token = response.get("continuation_token") or response.get(
                "continuationToken"
            )
            if not continuation_token:
                break

        return all_files

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

    def upload_files(
        self,
        *,
        files: dict[str, str],
    ) -> list[dict]:
        """Upload multiple files in parallel.

        Args:
            files: A dictionary mapping local paths to remote paths.
                Format: {local_path: remote_path}

        Returns:
            List of upload response dictionaries.

        Raises:
            RuntimeError: If any upload fails, with details about all failures.
        """
        results = []
        errors = []

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_pair = {
                executor.submit(
                    self.upload_file,
                    local_path=local_path,
                    remote_path=remote_path,
                ): (local_path, remote_path)
                for local_path, remote_path in files.items()
            }

            for future in concurrent.futures.as_completed(future_to_pair):
                local_path, remote_path = future_to_pair[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    errors.append((local_path, remote_path, e))

        if errors:
            error_msgs = "\n".join(
                [
                    f"Upload failed for local_path={lp}, remote_path={rp}: {str(err)}"
                    for lp, rp, err in errors
                ]
            )
            raise RuntimeError(f"Some uploads failed in upload_files:\n{error_msgs}")

        return results

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

    def download_files(
        self,
        *,
        files: dict[str, str | None] | list[str],
        skip_errors: bool = False,
        lazy: bool = False,
    ) -> list[str]:
        """Download multiple files in parallel.

        Args:
            files: Either a dictionary mapping remote paths to local paths, or a
                list of remote paths. Format: {remote_path: local_path or None} or
                [remote_path1, remote_path2, ...]. If a list is provided, local
                paths default to None (uses default location ~/.deeporigin/).
            skip_errors: If True, don't raise RuntimeError on failures.
                Defaults to False.
            lazy: If True, skip downloading if file already exists locally.
                Defaults to False.

        Returns:
            List of local paths where files were saved.

        Raises:
            RuntimeError: If any download fails and skip_errors is False,
                with details about all failures.
        """
        # Convert list to dict if needed
        if isinstance(files, list):
            files = dict.fromkeys(files, None)

        results = []
        errors = []

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_pair = {
                executor.submit(
                    self.download_file,
                    remote_path=remote_path,
                    local_path=local_path,
                    lazy=lazy,
                ): (remote_path, local_path)
                for remote_path, local_path in files.items()
            }

            for future in tqdm(
                concurrent.futures.as_completed(future_to_pair),
                total=len(files),
                desc="Downloading files",
                unit="file",
            ):
                remote_path, local_path = future_to_pair[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    errors.append((remote_path, local_path, e))

        if errors and not skip_errors:
            error_msgs = "\n".join(
                [
                    f"Download failed for remote_path={rp}, local_path={lp}: {str(err)}"
                    for rp, lp, err in errors
                ]
            )
            raise RuntimeError(
                f"Some downloads failed in download_files:\n{error_msgs}"
            )

        return results
