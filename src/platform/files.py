"""Files API wrapper for DeepOriginClient."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
import time
from typing import TYPE_CHECKING

import httpx
from tqdm import tqdm

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

from deeporigin.utils.core import _ensure_do_folder

_FILES_BASE = "/files"

_MISSING_URL_FIELD = "Signed URL response missing 'url' field"


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

    def _build_list_params(
        self,
        *,
        recursive: bool,
        last_count: int | None,
        continuation_token: str | None,
        delimiter: str | None,
        max_keys: int | None,
        prefix: str | None,
    ) -> dict[str, str | int | bool]:
        """Build parameters dictionary for list_files_in_dir API call.

        Args:
            recursive: If True, recursively list files in subdirectories.
            last_count: Used for pagination - the last count of objects.
            continuation_token: Token for pagination continuation.
            delimiter: Used to group results by a common prefix.
            max_keys: Page size (cannot exceed 1000).
            prefix: Path prefix to filter results.

        Returns:
            Dictionary of parameters for the API call.
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
        return params

    def _extract_file_keys(self, response: dict) -> list[str]:
        """Extract file keys from API response.

        Args:
            response: The API response dictionary.

        Returns:
            List of file keys extracted from the response.
        """
        file_keys: list[str] = []
        if "data" in response and isinstance(response["data"], list):
            for file_obj in response["data"]:
                if isinstance(file_obj, dict) and "Key" in file_obj:
                    file_keys.append(file_obj["Key"])
        return file_keys

    def _get_continuation_token(self, response: dict) -> str | None:
        """Extract continuation token from API response.

        Args:
            response: The API response dictionary.

        Returns:
            Continuation token if present, None otherwise.
        """
        return response.get("continuation_token") or response.get("continuationToken")

    def get_signed_url(self, remote_path: str, *, upload: bool = False) -> str:
        """Get a signed URL for uploading or downloading a file.

        Args:
            remote_path: The remote file path.
            upload: If True, returns a signed URL for uploading (HTTP PUT).
                If False, returns a signed URL for downloading (HTTP GET).
                Defaults to False.

        Returns:
            A signed URL string.

        Raises:
            ValueError: If the API response is missing the 'url' field.
        """
        params = {"upload": "true"} if upload else {}

        response = self._c.get_json(
            f"/files/{self._c.org_key}/signedUrl/{remote_path}",
            params=params,
        )

        if "url" not in response:
            raise ValueError(_MISSING_URL_FIELD)

        return response["url"]

    def _put_to_signed_url(
        self,
        local_path: Path,
        remote_path: str,
        *,
        max_retries: int = 3,
        retry_backoff_factor: float = 1.0,
    ) -> str:
        """Upload a single file to a signed URL with retries.

        Gets an upload signed URL for ``remote_path``, reads the file at
        ``local_path``, and PUTs its contents directly to the signed URL.

        Args:
            local_path: Local file to upload.
            remote_path: Remote path to request the signed URL for.
            max_retries: Maximum retry attempts on transient failures.
            retry_backoff_factor: Multiplier for exponential back-off between
                retries.  Delay = retry_backoff_factor * 2^attempt.

        Returns:
            The remote path that was uploaded.

        Raises:
            httpx.HTTPStatusError: If the PUT fails after all retries.
        """
        signed_url = self.get_signed_url(remote_path, upload=True)

        file_content = local_path.read_bytes()

        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                with httpx.Client() as upload_client:
                    resp = upload_client.put(
                        signed_url,
                        content=file_content,
                        headers={"Content-Type": "application/octet-stream"},
                    )
                    resp.raise_for_status()
                return remote_path
            except (
                httpx.HTTPStatusError,
                httpx.NetworkError,
                httpx.TimeoutException,
            ) as exc:
                last_exc = exc
                if attempt < max_retries:
                    time.sleep(retry_backoff_factor * (2**attempt))

        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _resolve_upload_pairs(
        local_path: str | Path | list[str | Path],
    ) -> list[tuple[Path, str]]:
        """Resolve local_path into (absolute_path, remote_suffix) pairs.

        Args:
            local_path: A local directory, a single file path, or a list of
                file paths.

        Returns:
            List of (Path, relative_suffix) tuples.

        Raises:
            ValueError: If ``local_path`` is not a file, directory, or list.
        """
        if isinstance(local_path, list):
            return [(Path(p), Path(p).name) for p in local_path]

        root = Path(local_path)
        if root.is_dir():
            return [
                (fp, fp.relative_to(root).as_posix())
                for fp in root.rglob("*")
                if fp.is_file()
            ]
        if root.is_file():
            return [(root, root.name)]

        raise ValueError(
            f"local_path must be an existing file or directory: {local_path}"
        )

    def upload_files_via_signed_url(
        self,
        local_path: str | Path | list[str | Path],
        remote_dir: str,
        *,
        max_workers: int = 20,
        max_retries: int = 3,
        retry_backoff_factor: float = 1.0,
        skip_errors: bool = False,
    ) -> list[str]:
        """Upload local files or a directory to a remote directory using signed URLs.

        Accepts either a list of file paths or a single directory path. When a
        directory is provided, all files inside it are collected recursively and
        their relative subdirectory structure is preserved under ``remote_dir``.

        Args:
            local_path: A local directory, a single file path, or a list of
                file paths to upload.
            remote_dir: Remote directory path (e.g. ``"/my-data/"``).
                A trailing ``/`` is added automatically if missing.
            max_workers: Maximum number of concurrent uploads. Defaults to 20.
            max_retries: Maximum retry attempts per file on transient failures.
                Defaults to 3.
            retry_backoff_factor: Multiplier for exponential back-off between
                retries. Defaults to 1.0.
            skip_errors: If True, don't raise on individual failures.
                Defaults to False.

        Returns:
            List of remote paths that were successfully uploaded.

        Raises:
            RuntimeError: If any upload fails and ``skip_errors`` is False.
            ValueError: If ``local_path`` is not a file, directory, or list.
        """
        if not remote_dir.endswith("/"):
            remote_dir += "/"

        upload_pairs = self._resolve_upload_pairs(local_path)

        results: list[str] = []
        errors: list[tuple[str, Exception]] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_local = {
                executor.submit(
                    self._put_to_signed_url,
                    fp,
                    f"{remote_dir}{suffix}",
                    max_retries=max_retries,
                    retry_backoff_factor=retry_backoff_factor,
                ): fp
                for fp, suffix in upload_pairs
            }

            for future in tqdm(
                concurrent.futures.as_completed(future_to_local),
                total=len(upload_pairs),
                desc="Uploading files",
                unit="file",
            ):
                local = future_to_local[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    errors.append((str(local), exc))

        if errors and not skip_errors:
            error_msgs = "\n".join(
                f"Upload failed for {lp}: {err}" for lp, err in errors
            )
            raise RuntimeError(
                f"Some uploads failed in upload_files_via_signed_url:\n{error_msgs}"
            )

        return results

    def list_files_in_dir(
        self,
        remote_path: str,
        *,
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
            remote_path: The path to the directory to list files from.
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
            params = self._build_list_params(
                recursive=recursive,
                last_count=last_count,
                continuation_token=continuation_token,
                delimiter=delimiter,
                max_keys=max_keys,
                prefix=prefix,
            )

            response = self._c.get_json(
                f"/files/{self._c.org_key}/directory/{remote_path}",
                params=params,
            )

            all_files.extend(self._extract_file_keys(response))

            continuation_token = self._get_continuation_token(response)
            if not continuation_token:
                break

        return all_files

    def list_files(
        self,
        remote_path: str,
        *,
        recursive: bool = True,
        last_count: int | None = None,
        delimiter: str | None = None,
        max_keys: int | None = None,
        prefix: str | None = None,
    ) -> list[dict]:
        """List files in a directory with full metadata.

        Like :meth:`list_files_in_dir` but returns the complete file objects
        from the API (Key, LastModified, ETag, Size, StorageClass, etc.)
        instead of just the keys.

        Automatically handles pagination using continuation tokens.

        Args:
            remote_path: The path to the directory to list files from.
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
            List of file metadata dictionaries. Each dict contains keys such as
            ``Key``, ``LastModified``, ``ETag``, ``Size``, ``StorageClass``,
            and ``ChecksumAlgorithm``.
        """
        all_files: list[dict] = []
        continuation_token: str | None = None

        while True:
            params = self._build_list_params(
                recursive=recursive,
                last_count=last_count,
                continuation_token=continuation_token,
                delimiter=delimiter,
                max_keys=max_keys,
                prefix=prefix,
            )

            response = self._c.get_json(
                f"/files/{self._c.org_key}/directory/{remote_path}",
                params=params,
            )

            if "data" in response and isinstance(response["data"], list):
                all_files.extend(response["data"])

            continuation_token = self._get_continuation_token(response)
            if not continuation_token:
                break

        return all_files

    def upload_file(
        self,
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
        max_workers: int = 20,
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

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_pair = {
                executor.submit(
                    self.upload_file,
                    local_path,
                    remote_path,
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
        remote_path: str,
        *,
        local_path: str | Path | None = None,
        lazy: bool = False,
        download_to_dir: str | Path | None = None,
    ) -> str:
        """Download a single file from UFA to ~/.deeporigin/, or some other local path.

        Args:
            remote_path: The remote path of the file to download.
            local_path: The local path to save the file to. If None, uses ~/.deeporigin/.
            lazy: If True, and the file exists locally, return the local path without downloading.
            download_to_dir: If provided, the file will be downloaded to this directory.
                The local path will be constructed by joining download_to_dir with the
                basename of remote_path. Ignored if local_path is provided.

        Returns:
            The local path where the file was saved.
        """
        # Determine local path
        if local_path is not None:
            local_path = Path(local_path)
        elif download_to_dir is not None:
            download_to_dir_path = Path(download_to_dir)
            # Extract basename from remote_path (handle both / and \ separators)
            remote_basename = Path(remote_path).name
            local_path = download_to_dir_path / remote_basename
        else:
            do_folder = _ensure_do_folder()
            local_path = do_folder / remote_path

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
            raise ValueError(_MISSING_URL_FIELD)

        signed_url = signed_url_response["url"]

        # Download file using httpx directly (signed_url is a complete URL)
        # Use a fresh client without base_url to avoid URL prefixing issues
        # Stream the response to avoid loading large files into memory
        with httpx.Client() as download_client:
            with download_client.stream("GET", signed_url) as download_response:
                download_response.raise_for_status()

                # Stream file content directly to disk
                with open(local_path, "wb") as f:
                    for chunk in download_response.iter_bytes():
                        f.write(chunk)

        return str(local_path)

    def download_files(
        self,
        *,
        files: dict[str, str | None] | list[str],
        skip_errors: bool = False,
        lazy: bool = True,
        max_workers: int = 20,
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
                Defaults to True.
            max_workers: Maximum number of concurrent downloads. Defaults to 20.

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

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
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

    def delete_file(
        self,
        remote_path: str,
        *,
        timeout: float | None = None,
    ) -> None:
        """Delete a file from UFA.

        Args:
            remote_path: The remote path of the file to delete.
            timeout: Request timeout in seconds. If None, uses the client's default timeout.

        Raises:
            RuntimeError: If the file deletion failed. Note: The API returns
                200 status even if deletion fails, so this method checks the
                response body for success.
        """
        # Temporarily increase timeout if specified
        original_timeout = None
        if timeout is not None:
            original_timeout = self._c._client.timeout
            self._c._client.timeout = timeout

        try:
            # Make DELETE request
            response = self._c._delete(
                f"/files/{self._c.org_key}/{remote_path}",
            )
        finally:
            if original_timeout is not None:
                self._c._client.timeout = original_timeout

        # Parse JSON response
        # API returns 200 even on failure, but response body indicates success
        data = response.json()

        if not data:
            raise RuntimeError(f"Failed to delete file {remote_path}")

    def delete_files(
        self,
        remote_paths: list[str],
        *,
        skip_errors: bool = False,
        max_workers: int = 20,
        timeout: float | None = None,
    ) -> None:
        """Delete multiple files in parallel.

        Args:
            remote_paths: List of remote file paths to delete.
            skip_errors: If True, don't raise RuntimeError on failures.
                Defaults to False.
            max_workers: Maximum number of concurrent deletions. Defaults to 20.
            timeout: Request timeout in seconds for each deletion. If None, uses the client's default timeout.

        Raises:
            RuntimeError: If any deletion fails and skip_errors is False,
                with details about all failures.
        """
        errors = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {
                executor.submit(
                    self.delete_file,
                    remote_path=remote_path,
                    timeout=timeout,
                ): remote_path
                for remote_path in remote_paths
            }

            for future in concurrent.futures.as_completed(future_to_path):
                remote_path = future_to_path[future]
                try:
                    future.result()
                except Exception as e:
                    errors.append((remote_path, e))

        if errors and not skip_errors:
            error_msgs = "\n".join(
                [
                    f"Delete failed for remote_path={rp}: {str(err)}"
                    for rp, err in errors
                ]
            )
            raise RuntimeError(f"Some deletions failed in delete_files:\n{error_msgs}")

    def get_file(
        self,
        remote_path: str,
        *,
        local_path: str | Path | None = None,
        download_to_dir: str | Path | None = None,
    ) -> str:
        """Download a file directly via the GET endpoint (no signed URL round-trip).

        Args:
            remote_path: The remote file path to download.
            local_path: Where to save the file locally. If None, defaults to
                ``~/.deeporigin/<remote_path>``.
            download_to_dir: If provided and ``local_path`` is None, save the
                file into this directory using the remote file's basename.

        Returns:
            The local path where the file was saved.
        """
        if local_path is not None:
            dest = Path(local_path)
        elif download_to_dir is not None:
            dest = Path(download_to_dir) / Path(remote_path).name
        else:
            dest = _ensure_do_folder() / remote_path

        dest.parent.mkdir(parents=True, exist_ok=True)

        response = self._c._get(f"/files/{self._c.org_key}/{remote_path}")

        dest.write_bytes(response.content)
        return str(dest)

    def head_file(self, remote_path: str) -> dict[str, str]:
        """Get file metadata headers without downloading the file body.

        Performs a HEAD request against ``/files/{orgKey}/{filePath}``.

        Args:
            remote_path: The remote file path to query.

        Returns:
            Dictionary of HTTP response headers (content-type, content-length,
            last-modified, etag, etc.).
        """
        response = self._c._head(f"/files/{self._c.org_key}/{remote_path}")
        return dict(response.headers)

    def upload_file_from_url(
        self,
        remote_path: str,
        *,
        source_url: str,
    ) -> dict:
        """Upload a file from a URL (server-side fetch).

        Tells the server to download the file at ``source_url`` and store it at
        ``remote_path``.  The file bytes never transit through the client.

        Args:
            remote_path: Destination path on the file server.
            source_url: Public URL the server should fetch the file from.

        Returns:
            The JSON response from the API.
        """
        response = self._c._post(
            f"/files/{self._c.org_key}/{remote_path}",
            body={"url": source_url},
        )
        return response.json()

    def download_as_zip(
        self,
        remote_path: str,
        *,
        local_path: str | Path | None = None,
        download_to_dir: str | Path | None = None,
    ) -> str:
        """Download a remote directory as a ZIP archive.

        Args:
            remote_path: The remote directory path to download.
            local_path: Where to save the ZIP file locally. If None, a default
                name is derived from ``remote_path``.
            download_to_dir: If provided and ``local_path`` is None, save the
                ZIP into this directory.

        Returns:
            The local path where the ZIP file was saved.
        """
        if local_path is not None:
            dest = Path(local_path)
        elif download_to_dir is not None:
            name = Path(remote_path.rstrip("/")).name + ".zip"
            dest = Path(download_to_dir) / name
        else:
            name = Path(remote_path.rstrip("/")).name + ".zip"
            dest = _ensure_do_folder() / name

        dest.parent.mkdir(parents=True, exist_ok=True)

        response = self._c._get(f"/files/{self._c.org_key}/zip/{remote_path}")

        dest.write_bytes(response.content)
        return str(dest)

    def health(self) -> dict:
        """Check the health of the files service.

        Returns:
            The JSON health-check response.
        """
        return self._c.get_json(f"{_FILES_BASE}/health")

    def version(self) -> dict:
        """Get the version of the files service.

        Returns:
            The JSON version response.
        """
        return self._c.get_json(f"{_FILES_BASE}/version")
