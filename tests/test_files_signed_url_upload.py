"""Unit tests for signed-URL upload hardening in Files."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from deeporigin.platform.files import Files


def _files_with_mock_client() -> Files:
    """Return a Files instance backed by a minimal mock client."""
    client = MagicMock()
    client.org_key = "test-org"
    client.get_json.return_value = {"url": "https://signed.example/upload"}
    return Files(client)


def test_put_to_signed_url_refreshes_signed_url_on_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each retry attempt should request a fresh presigned URL."""
    local_file = tmp_path / "data.bin"
    local_file.write_bytes(b"payload")

    files = _files_with_mock_client()
    signed_url_calls: list[bool] = []

    def track_signed_url(_remote_path: str, *, upload: bool = False) -> str:
        signed_url_calls.append(upload)
        return "https://signed.example/upload"

    monkeypatch.setattr(files, "signed_url", track_signed_url)

    put_attempts = {"count": 0}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    def fake_put(*_args: object, **_kwargs: object) -> FakeResponse:
        put_attempts["count"] += 1
        if put_attempts["count"] == 1:
            raise httpx.TimeoutException("simulated timeout")
        return FakeResponse()

    fake_client = MagicMock()
    fake_client.put.side_effect = fake_put
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(httpx, "Client", MagicMock(return_value=fake_client))
    monkeypatch.setattr("deeporigin.platform.files.time.sleep", lambda _seconds: None)

    remote = files._put_to_signed_url(local_file, "/remote/data.bin", max_retries=1)

    assert remote == "/remote/data.bin"
    assert signed_url_calls == [True, True]
    assert put_attempts["count"] == 2


def test_put_to_signed_url_streams_file_without_read_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upload should open the file for streaming instead of buffering read_bytes."""
    local_file = tmp_path / "stream.bin"
    local_file.write_bytes(b"stream-me")

    files = _files_with_mock_client()
    read_bytes_called = False

    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(self: Path) -> bytes:
        nonlocal read_bytes_called
        read_bytes_called = True
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    fake_client = MagicMock()
    fake_client.put.return_value = FakeResponse()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(httpx, "Client", MagicMock(return_value=fake_client))

    files._put_to_signed_url(local_file, "/remote/stream.bin", max_retries=0)

    assert read_bytes_called is False
    fake_client.put.assert_called_once()
    _args, kwargs = fake_client.put.call_args
    assert hasattr(kwargs["content"], "read")


def test_upload_tree_submits_largest_files_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parallel upload tasks should be queued largest-first."""
    small = tmp_path / "small.bin"
    medium = tmp_path / "medium.bin"
    large = tmp_path / "large.bin"
    small.write_bytes(b"x" * 10)
    medium.write_bytes(b"x" * 100)
    large.write_bytes(b"x" * 1000)

    files = _files_with_mock_client()
    submitted: list[Path] = []

    def capture_submit(
        _executor_self: object, fn: object, *args: object, **kwargs: object
    ):
        submitted.append(args[0])
        future: concurrent.futures.Future[str] = concurrent.futures.Future()
        future.set_result(str(args[1]))
        return future

    monkeypatch.setattr(
        concurrent.futures.ThreadPoolExecutor,
        "submit",
        capture_submit,
    )
    monkeypatch.setattr(
        "deeporigin.platform.files.tqdm",
        lambda iterable, **_kwargs: iterable,
    )

    results = files.upload_tree(
        local_path=[small, medium, large],
        remote_dir="/testing-size-order/",
        max_workers=3,
    )

    assert len(results) == 3
    assert submitted == [large, medium, small]
