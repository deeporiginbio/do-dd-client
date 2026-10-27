"""Unit tests for redacting pre-signed URL credentials from failed transfers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from deeporigin.platform.files import Files

_SECRETS = ("AKIASECRET", "TOKENSECRET", "deadbeefsig")

_SIGNED_URL = (
    "https://bucket.s3.amazonaws.com/key?X-Amz-Algorithm=AWS4-HMAC-SHA256"
    "&X-Amz-Credential=AKIASECRET%2F20261027%2Fus-east-1%2Fs3%2Faws4_request"
    "&X-Amz-Date=20261027T000000Z&X-Amz-Expires=86400"
    "&X-Amz-Security-Token=TOKENSECRET&X-Amz-Signature=deadbeefsig"
)


@pytest.fixture
def files(monkeypatch: pytest.MonkeyPatch) -> Files:
    """Return a Files instance whose signed-URL transfers all get a 403."""
    client = MagicMock()
    client.org_key = "test-org"
    files = Files(client)
    monkeypatch.setattr(files, "signed_url", lambda *_a, **_k: _SIGNED_URL)

    real_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(403))
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real_client(transport=transport, **kwargs)
    )
    return files


def _assert_redacted(text: str) -> None:
    for secret in _SECRETS:
        assert secret not in text
    assert "X-Amz-Credential=REDACTED" in text
    assert "X-Amz-Security-Token=REDACTED" in text
    assert "X-Amz-Signature=REDACTED" in text
    assert "X-Amz-Date=20261027T000000Z" in text


def test_download_to_path_error_is_redacted(files: Files, tmp_path: Path) -> None:
    """A failed download raises the httpx error with credentials redacted."""
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        files._download_to_path(
            "remote/data.bin", tmp_path / "data.bin", retry_backoff_factor=0
        )

    _assert_redacted(str(exc_info.value))
    assert exc_info.value.response.status_code == 403


def test_open_signed_url_stream_error_is_redacted(files: Files) -> None:
    """A failed stream open raises the httpx error with credentials redacted."""
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        files._open_signed_url_stream("remote/data.bin", retry_backoff_factor=0)

    _assert_redacted(str(exc_info.value))
    assert exc_info.value.response.status_code == 403


def test_put_to_signed_url_error_is_redacted(files: Files, tmp_path: Path) -> None:
    """A failed upload raises the httpx error with credentials redacted."""
    local = tmp_path / "data.bin"
    local.write_bytes(b"x")

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        files._put_to_signed_url(local, "remote/data.bin", retry_backoff_factor=0)

    _assert_redacted(str(exc_info.value))
    assert exc_info.value.response.status_code == 403


def test_interrupt_during_retry_sleep_chains_redacted_error(
    files: Files, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Ctrl-C during the retry back-off chains the already-redacted error."""

    def interrupt(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("deeporigin.platform.files.time.sleep", interrupt)

    with pytest.raises(KeyboardInterrupt) as exc_info:
        files._download_to_path("remote/data.bin", tmp_path / "data.bin")

    context = exc_info.value.__context__
    assert isinstance(context, httpx.HTTPStatusError)
    _assert_redacted(str(context))


def test_upload_tree_aggregate_error_is_redacted(files: Files, tmp_path: Path) -> None:
    """upload_tree's RuntimeError embeds the per-file errors, already redacted."""
    local = tmp_path / "data.bin"
    local.write_bytes(b"x")

    with pytest.raises(RuntimeError) as exc_info:
        files.upload_tree(local, "remote/", retry_backoff_factor=0)

    _assert_redacted(str(exc_info.value))
