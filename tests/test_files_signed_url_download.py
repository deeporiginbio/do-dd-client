"""Unit tests for signed-URL download hardening in Files."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from deeporigin.platform.files import Files


def _files_with_mock_client() -> Files:
    """Return a Files instance backed by a minimal mock client."""
    client = MagicMock()
    client.org_key = "test-org"
    client.get_json.return_value = {"url": "https://signed.example/download"}
    return Files(client)


class _FakeStreamResponse:
    """Minimal stand-in for the httpx streaming context manager."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self):
        yield self._body

    def __enter__(self) -> "_FakeStreamResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_download_to_path_refreshes_signed_url_on_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each retry attempt should request a fresh presigned URL."""
    files = _files_with_mock_client()
    signed_url_calls = 0

    def track_signed_url(_remote_path: str, *, upload: bool = False) -> str:
        nonlocal signed_url_calls
        signed_url_calls += 1
        return "https://signed.example/download"

    monkeypatch.setattr(files, "signed_url", track_signed_url)

    stream_attempts = {"count": 0}

    def fake_stream(*_args: object, **_kwargs: object) -> _FakeStreamResponse:
        stream_attempts["count"] += 1
        if stream_attempts["count"] == 1:
            raise httpx.TimeoutException("simulated timeout")
        return _FakeStreamResponse(b"payload")

    fake_client = MagicMock()
    fake_client.stream.side_effect = fake_stream
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(httpx, "Client", MagicMock(return_value=fake_client))
    monkeypatch.setattr("deeporigin.platform.files.time.sleep", lambda _seconds: None)

    dest = tmp_path / "data.bin"
    files._download_to_path(
        "/remote/data.bin",
        dest,
        max_retries=1,
    )

    assert signed_url_calls == 2
    assert stream_attempts["count"] == 2
    assert dest.read_bytes() == b"payload"


def test_download_to_path_raises_after_exhausting_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persistently failing GET should surface the last exception."""
    files = _files_with_mock_client()
    monkeypatch.setattr(
        files, "signed_url", lambda *_a, **_k: "https://signed.example/x"
    )

    def always_fail(*_args: object, **_kwargs: object):
        raise httpx.TimeoutException("simulated timeout")

    fake_client = MagicMock()
    fake_client.stream.side_effect = always_fail
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(httpx, "Client", MagicMock(return_value=fake_client))
    monkeypatch.setattr("deeporigin.platform.files.time.sleep", lambda _seconds: None)

    dest = tmp_path / "data.bin"
    with pytest.raises(httpx.TimeoutException):
        files._download_to_path("/remote/data.bin", dest, max_retries=2)

    assert not dest.exists()
    assert not any(dest.parent.iterdir())


def test_download_to_path_retries_when_signed_url_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient failure while presigning should be retried, not just the GET."""
    files = _files_with_mock_client()
    signed_url_attempts = {"count": 0}

    def flaky_signed_url(_remote_path: str, *, upload: bool = False) -> str:
        signed_url_attempts["count"] += 1
        if signed_url_attempts["count"] == 1:
            raise httpx.TimeoutException("simulated presign timeout")
        return "https://signed.example/download"

    monkeypatch.setattr(files, "signed_url", flaky_signed_url)

    fake_client = MagicMock()
    fake_client.stream.side_effect = lambda *_a, **_k: _FakeStreamResponse(b"payload")
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(httpx, "Client", MagicMock(return_value=fake_client))
    monkeypatch.setattr("deeporigin.platform.files.time.sleep", lambda _seconds: None)

    dest = tmp_path / "data.bin"
    files._download_to_path("/remote/data.bin", dest, max_retries=1)

    assert signed_url_attempts["count"] == 2
    assert dest.read_bytes() == b"payload"
    # No stray temp files left behind from the presign failure.
    assert list(dest.parent.iterdir()) == [dest]


def test_open_signed_url_stream_refreshes_signed_url_on_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each retry attempt should request a fresh presigned URL and close failed clients."""
    files = _files_with_mock_client()
    signed_url_calls = 0

    def track_signed_url(_remote_path: str, *, upload: bool = False) -> str:
        nonlocal signed_url_calls
        signed_url_calls += 1
        return "https://signed.example/download"

    monkeypatch.setattr(files, "signed_url", track_signed_url)

    closed_clients: list[MagicMock] = []
    send_attempts = {"count": 0}

    def make_client(*_args: object, **_kwargs: object) -> MagicMock:
        client = MagicMock()
        closed_clients.append(client)

        def fake_send(*_a: object, **_k: object):
            send_attempts["count"] += 1
            if send_attempts["count"] == 1:
                raise httpx.TimeoutException("simulated timeout")
            response = MagicMock()
            response.raise_for_status.return_value = None
            return response

        client.send.side_effect = fake_send
        return client

    monkeypatch.setattr(httpx, "Client", make_client)
    monkeypatch.setattr("deeporigin.platform.files.time.sleep", lambda _seconds: None)

    stream = files._open_signed_url_stream("/remote/data.bin", max_retries=1)

    assert signed_url_calls == 2
    assert send_attempts["count"] == 2
    # The first (failed) client should have been closed; the second stays open
    # inside the returned FileStream.
    closed_clients[0].close.assert_called_once()
    closed_clients[1].close.assert_not_called()

    stream.close()


def test_open_signed_url_stream_retries_when_signed_url_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient failure while presigning should be retried, not escape immediately."""
    files = _files_with_mock_client()
    signed_url_attempts = {"count": 0}

    def flaky_signed_url(_remote_path: str, *, upload: bool = False) -> str:
        signed_url_attempts["count"] += 1
        if signed_url_attempts["count"] == 1:
            raise httpx.TimeoutException("simulated presign timeout")
        return "https://signed.example/download"

    monkeypatch.setattr(files, "signed_url", flaky_signed_url)

    closed_clients: list[MagicMock] = []

    def make_client(*_args: object, **_kwargs: object) -> MagicMock:
        client = MagicMock()
        closed_clients.append(client)
        response = MagicMock()
        response.raise_for_status.return_value = None
        client.send.return_value = response
        return client

    monkeypatch.setattr(httpx, "Client", make_client)
    monkeypatch.setattr("deeporigin.platform.files.time.sleep", lambda _seconds: None)

    stream = files._open_signed_url_stream("/remote/data.bin", max_retries=1)

    assert signed_url_attempts["count"] == 2
    # The client from the presign-failure attempt should have been closed.
    closed_clients[0].close.assert_called_once()
    closed_clients[1].close.assert_not_called()

    stream.close()
