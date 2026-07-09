"""Tests for network utility functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from deeporigin.exceptions import DeepOriginException
from deeporigin.utils import network


def test_parse_params_from_url() -> None:
    """_parse_params_from_url extracts single-valued query parameters."""
    params = network._parse_params_from_url(
        "https://example.com/path?foo=1&bar=two&foo=ignored"
    )

    assert params == {"foo": "1", "bar": "two"}


def test_download_sync_writes_file(tmp_path) -> None:
    """download_sync streams a successful GET response to disk."""
    destination = tmp_path / "downloaded.bin"
    response = MagicMock()
    response.status_code = 200
    response.iter_bytes.return_value = [b"chunk-1", b"chunk-2"]
    context = MagicMock()
    context.__enter__.return_value = response
    context.__exit__.return_value = None

    with patch("deeporigin.utils.network.httpx.stream", return_value=context):
        network.download_sync("https://example.com/file", destination)

    assert destination.read_bytes() == b"chunk-1chunk-2"


def test_download_sync_non_200_raises() -> None:
    """download_sync raises DeepOriginException on HTTP errors."""
    response = MagicMock()
    response.status_code = 404
    response.text = "missing"
    context = MagicMock()
    context.__enter__.return_value = response
    context.__exit__.return_value = None

    with (
        patch("deeporigin.utils.network.httpx.stream", return_value=context),
        pytest.raises(DeepOriginException, match="404"),
    ):
        network.download_sync("https://example.com/missing", "/tmp/out.bin")


def test_check_for_updates_prints_when_newer(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """check_for_updates prints a message when PyPI has a newer release."""
    network.check_for_updates.cache_clear()
    monkeypatch.setattr(network, "_get_pypi_version", lambda: "9.9.9")
    monkeypatch.setattr("deeporigin.utils.network.__version__", "1.0.0")

    network.check_for_updates()

    assert "new version" in capsys.readouterr().out.lower()
    network.check_for_updates.cache_clear()


def test_get_pypi_version_success() -> None:
    """_get_pypi_version returns the latest version from PyPI JSON."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"info": {"version": "2.3.4"}}

    with patch("deeporigin.utils.network.httpx.get", return_value=response):
        assert network._get_pypi_version() == "2.3.4"


def test_get_pypi_version_failure() -> None:
    """_get_pypi_version returns None when PyPI is unreachable."""
    response = MagicMock()
    response.status_code = 500

    with patch("deeporigin.utils.network.httpx.get", return_value=response):
        assert network._get_pypi_version() is None
