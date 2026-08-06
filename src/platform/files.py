"""Files API wrapper for DeepOriginClient."""

from __future__ import annotations

from collections.abc import Iterator
import concurrent.futures
import os
from pathlib import Path
import tempfile
import time
from typing import TYPE_CHECKING, Literal, overload

import httpx
from tqdm import tqdm

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

from deeporigin.utils.env import _ensure_do_folder

_FILES_BASE = "/files"

_MISSING_URL_FIELD = "Signed URL response missing 'url' field"


def _normalize_remote_path(remote_path: str) -> str:
    """Normalize a UFA remote path for platform API URL segments.

    Data-platform rows and UUI often store paths with a leading slash
    (e.g. ``/seeded/proteins/BRD.pdb``). The file-service expects keys without
    one; embedding a leading slash in ``/signedUrl/{path}`` creates a double
    slash that misses the signedUrl route and returns 404.

    Args:
        remote_path: Raw remote path from the caller.

    Returns:
        Path with leading slashes removed and repeated ``/`` collapsed.
    """
    normalized = remote_path.replace("\\", "/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized.lstrip("/")


# Signed-URL PUTs upload full file bodies; default httpx read timeout (5s) is too
# short under concurrent upload_tree workers waiting on S3.
_SIGNED_URL_UPLOAD_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=120.0,
    write=300.0,
    pool=10.0,
)

# Platform GET for presigned URLs can queue under many concurrent upload_tree workers.
_SIGNED_URL_API_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=30.0,
    write=10.0,
    pool=10.0,
)

# Match httpx IteratorByteStream.CHUNK_SIZE for signed-URL PUT bodies.
_SIGNED_URL_UPLOAD_CHUNK_SIZE = 65_536


def _iter_local_file_chunks(
    local_path: Path,
    *,
    chunk_size: int = _SIGNED_URL_UPLOAD_CHUNK_SIZE,
) -> Iterator[bytes]:
    """Yield fixed-size byte chunks from a local file for signed-URL PUTs.

    Args:
        local_path: Local file to read.
        chunk_size: Maximum bytes per yielded chunk.

    Yields:
        Successive byte chunks until EOF.
    """
    with open(local_path, "rb") as file_obj:
        while True:
            chunk = file_obj.read(chunk_size)
            if not chunk:
                break
            yield chunk


class FileStream:
    """Streaming wrapper around an HTTP download response.

    Supports three consumption patterns:

    - **Chunk iteration** via :meth:`iter_bytes` or ``for chunk in stream``.
    - **File-like reads** via :meth:`read`, compatible with consumers such as
      ``csv.reader``, ``json.load``, or ``pandas.read_csv``.
    - **Context manager** for deterministic cleanup of the underlying
      connection.

    Always use as a context manager or call :meth:`close` explicitly::

        with client.files.download_stream("data/results.csv") as stream:
            for chunk in stream.iter_bytes():
                process(chunk)
    """

    def __init__(
        self,
        response: httpx.Response,
        *,
        _owning_client: httpx.Client | None = None,
    ) -> None:
        """Initialize the stream wrapper.

        Args:
            response: An httpx streaming response (sent with ``stream=True``).
            _owning_client: An ephemeral ``httpx.Client`` that should be closed
                when this stream is closed.  ``None`` when the response comes
                from a shared / long-lived client.
        """
        self._response = response
        self._owning_client = _owning_client
        self._buffer = bytearray()
        self._closed = False
        self._iterator: Iterator[bytes] | None = None

    @property
    def closed(self) -> bool:
        """Whether the stream has been closed."""
        return self._closed

    @property
    def content_length(self) -> int | None:
        """Total content length in bytes, or ``None`` if unknown."""
        raw = self._response.headers.get("content-length")
        return int(raw) if raw is not None else None

    @property
    def content_type(self) -> str | None:
        """MIME type of the response body, or ``None`` if unset."""
        return self._response.headers.get("content-type")

    @property
    def headers(self) -> httpx.Headers:
        """HTTP response headers."""
        return self._response.headers

    def _ensure_iterator(self) -> Iterator[bytes]:
        """Return the shared byte iterator, creating it on first use."""
        if self._iterator is None:
            self._iterator = self._response.iter_bytes()
        return self._iterator

    def iter_bytes(self, chunk_size: int | None = None) -> Iterator[bytes]:
        """Yield successive byte chunks from the response body.

        Args:
            chunk_size: Requested chunk size in bytes.  ``None`` uses the
                server/transport default.
        """
        if self._closed:
            raise ValueError("I/O operation on closed stream")
        if self._buffer:
            yield bytes(self._buffer)
            self._buffer.clear()
        if self._iterator is not None:
            yield from self._iterator
        else:
            yield from self._response.iter_bytes(chunk_size=chunk_size)

    def read(self, n: int = -1) -> bytes:
        """Read up to *n* bytes, or all remaining bytes when *n* is ``-1``.

        Args:
            n: Maximum number of bytes to return, or ``-1`` for all.
        """
        if self._closed:
            raise ValueError("I/O operation on closed stream")

        iterator = self._ensure_iterator()

        if n == -1:
            chunks = [bytes(self._buffer)] if self._buffer else []
            self._buffer.clear()
            for chunk in iterator:
                chunks.append(chunk)
            return b"".join(chunks)

        while len(self._buffer) < n:
            try:
                self._buffer.extend(next(iterator))
            except StopIteration:
                break

        result = bytes(self._buffer[:n])
        del self._buffer[:n]
        return result

    def readinto(self, b: bytearray | memoryview) -> int:
        """Read up to ``len(b)`` bytes into the pre-allocated buffer *b*.

        This makes ``FileStream`` compatible with :class:`io.BufferedReader`
        and :class:`io.TextIOWrapper`, which require the ``readinto`` protocol.

        Args:
            b: A writable buffer to fill with downloaded bytes.

        Returns:
            The number of bytes actually written into *b*, or 0 at EOF.
        """
        data = self.read(len(b))
        if not data:
            return 0
        b[: len(data)] = data
        return len(data)

    def readable(self) -> bool:
        """Return whether the stream is readable."""
        return True

    def writable(self) -> bool:
        """Return whether the stream is writable."""
        return False

    def seekable(self) -> bool:
        """Return whether the stream supports seeking."""
        return False

    def close(self) -> None:
        """Close the underlying HTTP response and optional owning client."""
        if not self._closed:
            self._closed = True
            self._response.close()
            if self._owning_client is not None:
                self._owning_client.close()

    def __enter__(self) -> FileStream:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __iter__(self) -> Iterator[bytes]:
        return self.iter_bytes()

    def __del__(self) -> None:
        self.close()


class Files:
    """Files API wrapper for org file storage (list, upload, download, delete).

    For guidance on choosing between ``upload`` / ``upload_many`` / ``upload_tree``,
    ``download`` / ``download_many``, and related methods, see
    ``docs/platform/ref/files.md`` (section *Choosing a method*).
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
        """Build parameters dictionary for :meth:`Files.list` API call.

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
            params["max-keys"] = max_keys
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

    def signed_url(self, remote_path: str, *, upload: bool = False) -> str:
        """Return a signed URL for uploading or downloading a file.

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
        remote_path = _normalize_remote_path(remote_path)
        params = {"upload": "true"} if upload else {}

        response = self._c.get_json(
            f"/files/{self._c.org_key}/signedUrl/{remote_path}",
            params=params,
            timeout=_SIGNED_URL_API_TIMEOUT,
        )

        if "url" not in response:
            raise ValueError(_MISSING_URL_FIELD)

        return response["url"]

    def _put_to_signed_url(
        self,
        local_path: Path,
        remote_path: str,
        *,
        file_size: int | None = None,
        max_retries: int = 3,
        retry_backoff_factor: float = 1.0,
    ) -> str:
        """Upload a single file to a signed URL with retries.

        On each attempt, requests a fresh upload signed URL for ``remote_path``,
        streams the file at ``local_path`` in fixed-size chunks via HTTP PUT to
        that URL, and retries on transient failures.

        Args:
            local_path: Local file to upload.
            remote_path: Remote path to request the signed URL for.
            file_size: Optional precomputed ``st_size`` to avoid a duplicate stat
                when ``upload_tree`` has already measured the file for sorting.
            max_retries: Maximum retry attempts on transient failures.
            retry_backoff_factor: Multiplier for exponential back-off between
                retries.  Delay = retry_backoff_factor * 2^attempt.

        Returns:
            The remote path that was uploaded.

        Raises:
            httpx.HTTPStatusError: If the PUT fails after all retries.
        """
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                signed_url = self.signed_url(remote_path, upload=True)
                headers = {"Content-Type": "application/octet-stream"}
                if file_size is None:
                    file_size = self._local_file_size(local_path)
                if file_size > 0:
                    headers["Content-Length"] = str(file_size)

                with httpx.Client(timeout=_SIGNED_URL_UPLOAD_TIMEOUT) as upload_client:
                    resp = upload_client.put(
                        signed_url,
                        content=_iter_local_file_chunks(local_path),
                        headers=headers,
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
    def _local_file_size(local_path: Path) -> int:
        """Return ``st_size`` for a local file, or ``0`` when stat fails."""
        try:
            return local_path.stat().st_size
        except OSError:
            return 0

    @staticmethod
    def _sort_upload_pairs_by_size_desc(
        upload_pairs: list[tuple[Path, str]],
    ) -> list[tuple[Path, str, int]]:
        """Return upload pairs with cached sizes, largest first."""
        sized_pairs = [
            (path, suffix, Files._local_file_size(path))
            for path, suffix in upload_pairs
        ]
        sized_pairs.sort(key=lambda pair: pair[2], reverse=True)
        return sized_pairs

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

    def upload_tree(
        self,
        local_path: str | Path | list[str | Path],
        remote_dir: str,
        *,
        max_workers: int = 20,
        max_retries: int = 3,
        retry_backoff_factor: float = 1.0,
        skip_errors: bool = False,
    ) -> list[str]:
        """Upload a local file, directory tree, or file list under a remote directory.

        Uses signed URLs and parallel workers. Directory uploads preserve relative
        paths under ``remote_dir``.

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
        remote_dir = _normalize_remote_path(remote_dir)
        if not remote_dir.endswith("/"):
            remote_dir += "/"

        upload_pairs = self._resolve_upload_pairs(local_path)
        upload_pairs = self._sort_upload_pairs_by_size_desc(upload_pairs)

        results: list[str] = []
        errors: list[tuple[str, Exception]] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_local = {
                executor.submit(
                    self._put_to_signed_url,
                    fp,
                    f"{remote_dir}{suffix}",
                    file_size=file_size,
                    max_retries=max_retries,
                    retry_backoff_factor=retry_backoff_factor,
                ): fp
                for fp, suffix, file_size in upload_pairs
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
            raise RuntimeError(f"Some uploads failed in upload_tree:\n{error_msgs}")

        return results

    @overload
    def list(
        self,
        remote_path: str,
        *,
        metadata: Literal[False] = False,
        recursive: bool = True,
        last_count: int | None = None,
        delimiter: str | None = None,
        max_keys: int | None = None,
        prefix: str | None = None,
    ) -> list[str]:
        """List remote object keys under a path (default).

        Omit ``metadata`` or set ``metadata=False`` to get a ``list[str]`` of
        remote keys. Pagination is handled automatically.

        Args:
            remote_path: Directory path to list from.
            metadata: Must be ``False`` for this overload (default).
            recursive: If True, include objects in subdirectories.
            last_count: Pagination hint for the backing store.
            delimiter: Group keys by a common prefix (e.g. ``"/"``).
            max_keys: Page size (cannot exceed 1000).
            prefix: Filter keys by this path prefix.

        Returns:
            List of remote key strings.
        """
        ...

    @overload
    def list(
        self,
        remote_path: str,
        *,
        metadata: Literal[True],
        recursive: bool = True,
        last_count: int | None = None,
        delimiter: str | None = None,
        max_keys: int | None = None,
        prefix: str | None = None,
    ) -> list[dict]:
        """List remote objects with full metadata from the API.

        Set ``metadata=True`` to get a ``list[dict]`` (e.g. ``Key``, ``Size``,
        ``ETag``, ``LastModified``). Pagination is handled automatically.

        Args:
            remote_path: Directory path to list from.
            metadata: Must be ``True`` for this overload.
            recursive: If True, include objects in subdirectories.
            last_count: Pagination hint for the backing store.
            delimiter: Group results by a common prefix (e.g. ``"/"``).
            max_keys: Page size (cannot exceed 1000).
            prefix: Filter results by this path prefix.

        Returns:
            List of file metadata dictionaries from the API.
        """
        ...

    def list(
        self,
        remote_path: str,
        *,
        metadata: bool = False,
        recursive: bool = True,
        last_count: int | None = None,
        delimiter: str | None = None,
        max_keys: int | None = None,
        prefix: str | None = None,
    ) -> list[str] | list[dict]:
        """List objects under a remote path.

        Automatically handles pagination using continuation tokens.

        Args:
            remote_path: Directory path to list from.
            metadata: If False (default), return remote keys only. If True,
                return full file objects from the API (``Key``, ``LastModified``,
                ``ETag``, ``Size``, etc.).
            recursive: If True, recursively list files in subdirectories.
            last_count: Pagination hint — last count of objects in the bucket.
            delimiter: Group results by a common prefix (e.g. ``"/"``).
            max_keys: Page size (cannot exceed 1000).
            prefix: Path prefix to filter results.

        Returns:
            Either a list of remote keys or a list of metadata dicts.
        """
        remote_path = _normalize_remote_path(remote_path)
        all_keys: list[str] = []
        all_objects: list[dict] = []
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

            if metadata:
                if "data" in response and isinstance(response["data"], list):
                    all_objects.extend(response["data"])
            else:
                all_keys.extend(self._extract_file_keys(response))

            continuation_token = self._get_continuation_token(response)
            if not continuation_token:
                break

        return all_objects if metadata else all_keys

    def upload(
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
        remote_path_str = _normalize_remote_path(str(remote_path))

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

    def upload_many(
        self,
        *,
        files: dict[str, str],
        max_workers: int = 20,
    ) -> list[dict]:
        """Upload multiple files in parallel via multipart upload.

        Args:
            files: Mapping of local paths to remote paths.
            max_workers: Maximum concurrent uploads.

        Returns:
            List of upload response dictionaries.

        Raises:
            RuntimeError: If any upload fails, with details about all failures.
        """
        results: list[dict] = []
        errors: list[tuple[str, str, Exception]] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_pair = {
                executor.submit(
                    self.upload,
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
            raise RuntimeError(f"Some uploads failed in upload_many:\n{error_msgs}")

        return results

    def download(
        self,
        remote_path: str,
        *,
        local_path: str | Path | None = None,
        lazy: bool = False,
        download_to_dir: str | Path | None = None,
        direct: bool = False,
    ) -> str:
        """Download a remote file to a local path.

        By default uses a signed URL and streams the body to disk (good for large
        files). Set ``direct=True`` to use the HTTP GET file endpoint instead
        (no signed-URL round trip; body is buffered in memory).

        Args:
            remote_path: Remote file path.
            local_path: Local path to save to. If None, uses ``~/.deeporigin/``
                (signed-URL mode uses ``remote_path`` with leading slashes
                stripped; direct mode uses ``remote_path`` as given).
            lazy: If True and the file already exists locally, skip downloading.
            download_to_dir: Save using the basename of ``remote_path`` under
                this directory (ignored if ``local_path`` is set).
            direct: If True, download via ``GET /files/{org}/{path}`` instead of
                a signed URL.

        Returns:
            The local path where the file was saved.
        """
        remote_path = _normalize_remote_path(remote_path)
        dest: Path
        if direct:
            if local_path is not None:
                dest = Path(local_path)
            elif download_to_dir is not None:
                dest = Path(download_to_dir) / Path(remote_path).name
            else:
                dest = _ensure_do_folder() / remote_path
        elif local_path is not None:
            dest = Path(local_path)
        elif download_to_dir is not None:
            download_to_dir_path = Path(download_to_dir)
            remote_basename = Path(remote_path).name
            dest = download_to_dir_path / remote_basename
        else:
            do_folder = _ensure_do_folder()
            dest = do_folder / remote_path.lstrip("/")

        dest.parent.mkdir(parents=True, exist_ok=True)

        if lazy and dest.exists():
            return str(dest)

        if direct:
            response = self._c._get(f"/files/{self._c.org_key}/{remote_path}")
            tmp = tempfile.NamedTemporaryFile(
                dir=dest.parent, suffix=".tmp", delete=False
            )
            try:
                with tmp:
                    tmp.write(response.content)
                os.replace(tmp.name, dest)
            except BaseException:
                os.unlink(tmp.name)
                raise
            return str(dest)

        signed_url_response = self._c.get_json(
            f"/files/{self._c.org_key}/signedUrl/{remote_path}",
        )

        if "url" not in signed_url_response:
            raise ValueError(_MISSING_URL_FIELD)

        signed_url = signed_url_response["url"]

        tmp = tempfile.NamedTemporaryFile(dir=dest.parent, suffix=".tmp", delete=False)
        try:
            with tmp:
                with httpx.Client() as download_client:
                    with download_client.stream("GET", signed_url) as download_response:
                        download_response.raise_for_status()
                        for chunk in download_response.iter_bytes():
                            tmp.write(chunk)
            os.replace(tmp.name, dest)
        except BaseException:
            os.unlink(tmp.name)
            raise

        return str(dest)

    def download_stream(
        self,
        remote_path: str,
        *,
        direct: bool = False,
    ) -> FileStream:
        """Stream a remote file without writing to disk.

        Returns a :class:`FileStream` that yields bytes on demand, letting
        callers process data while the download is still in flight.

        By default uses a signed URL (good for large files, auth embedded in
        the URL).  Set ``direct=True`` to stream through the platform gateway
        instead (no signed-URL round trip; uses bearer auth).

        Always use as a context manager::

            with client.files.download_stream("data/big.csv") as stream:
                for chunk in stream.iter_bytes(chunk_size=1 << 16):
                    process(chunk)

        The stream also supports file-like :meth:`~FileStream.read` calls::

            with client.files.download_stream("data/big.csv") as stream:
                header = stream.read(1024)

        Args:
            remote_path: Remote file path.
            direct: If ``True``, stream via ``GET /files/{org}/{path}``
                instead of a signed URL.

        Returns:
            A :class:`FileStream` wrapping the in-flight HTTP response.

        Raises:
            ValueError: If the signed-URL response is missing the ``url``
                field.
            httpx.HTTPStatusError: If the server returns a non-2xx status.
        """
        remote_path = _normalize_remote_path(remote_path)
        if direct:
            self._c.check_token()
            request = self._c._client.build_request(
                "GET",
                f"/files/{self._c.org_key}/{remote_path}",
            )
            response = self._c._client.send(request, stream=True)
            try:
                response.raise_for_status()
            except Exception:
                response.close()
                raise
            return FileStream(response)

        signed_url_response = self._c.get_json(
            f"/files/{self._c.org_key}/signedUrl/{remote_path}",
        )

        if "url" not in signed_url_response:
            raise ValueError(_MISSING_URL_FIELD)

        signed_url = signed_url_response["url"]
        download_client = httpx.Client()
        response: httpx.Response | None = None
        try:
            request = download_client.build_request("GET", signed_url)
            response = download_client.send(request, stream=True)
            response.raise_for_status()
        except Exception:
            if response is not None:
                response.close()
            download_client.close()
            raise

        return FileStream(response, _owning_client=download_client)

    def download_many(
        self,
        *,
        files: dict[str, str | None] | list[str],
        skip_errors: bool = False,
        lazy: bool = True,
        max_workers: int = 20,
    ) -> dict[str, str]:
        """Download multiple files in parallel.

        Args:
            files: Mapping of remote paths to local paths (or None for default
                ``~/.deeporigin/`` layout), or a list of remote paths.
            skip_errors: If True, collect failures instead of raising.
            lazy: If True, skip download when the local file already exists.
            max_workers: Maximum concurrent downloads.

        Returns:
            Mapping of each **remote** path to the local path where that file was
            saved. Failed downloads are omitted when ``skip_errors`` is True.

        Raises:
            RuntimeError: If any download fails and ``skip_errors`` is False.
        """
        if isinstance(files, list):
            files = dict.fromkeys(files, None)

        results: dict[str, str] = {}
        errors: list[tuple[str, str | None, Exception]] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_pair = {
                executor.submit(
                    self.download,
                    remote_path,
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
                    results[remote_path] = result
                except Exception as e:
                    errors.append((remote_path, local_path, e))

        if errors and not skip_errors:
            error_msgs = "\n".join(
                [
                    f"Download failed for remote_path={rp}, local_path={lp}: {str(err)}"
                    for rp, lp, err in errors
                ]
            )
            raise RuntimeError(f"Some downloads failed in download_many:\n{error_msgs}")

        return results

    def delete(
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
        remote_path = _normalize_remote_path(remote_path)
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

    def delete_many(
        self,
        remote_paths: list[str],
        *,
        skip_errors: bool = False,
        max_workers: int = 20,
        timeout: float | None = None,
    ) -> None:
        """Delete multiple files in parallel.

        Args:
            remote_paths: Remote file paths to delete.
            skip_errors: If True, don't raise on failures.
            max_workers: Maximum concurrent deletions.
            timeout: Per-request timeout in seconds.

        Raises:
            RuntimeError: If any deletion fails and ``skip_errors`` is False.
        """
        errors: list[tuple[str, Exception]] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {
                executor.submit(
                    self.delete,
                    remote_path,
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
            raise RuntimeError(f"Some deletions failed in delete_many:\n{error_msgs}")

    def stat(self, remote_path: str) -> dict[str, str]:
        """Return file metadata from a HEAD request (no body download).

        Args:
            remote_path: Remote file path.

        Returns:
            HTTP response headers (content-type, content-length, etag, etc.).
        """
        remote_path = _normalize_remote_path(remote_path)
        response = self._c._head(f"/files/{self._c.org_key}/{remote_path}")
        return dict(response.headers)

    def upload_from_url(
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
        remote_path = _normalize_remote_path(remote_path)
        response = self._c._post(
            f"/files/{self._c.org_key}/{remote_path}",
            body={"url": source_url},
        )
        return response.json()

    def download_zip(
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
        remote_path = _normalize_remote_path(remote_path)
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
