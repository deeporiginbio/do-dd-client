"""Tests for UFA remote path normalization in the Files client."""

from __future__ import annotations

import httpx
import pytest

from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.files import _normalize_remote_path


def test_normalize_remote_path_strips_leading_slash() -> None:
    """Leading slashes are removed before building file-service URLs."""
    assert _normalize_remote_path("/seeded/proteins/BRD/BRD.pdb") == (
        "seeded/proteins/BRD/BRD.pdb"
    )


def test_normalize_remote_path_collapses_duplicate_slashes() -> None:
    """Repeated slashes are collapsed to a single separator."""
    assert _normalize_remote_path("//seeded//proteins/BRD.pdb") == (
        "seeded/proteins/BRD.pdb"
    )


def test_signed_url_uses_normalized_path(client: DeepOriginClient) -> None:
    """signed_url must not embed a leading slash in the signedUrl segment."""
    captured: list[str] = []

    def fake_get_json(path: str, **kwargs: object) -> dict[str, str]:
        captured.append(path)
        return {"url": "https://example.com/object"}

    client.get_json = fake_get_json  # type: ignore[method-assign]

    url = client.files.signed_url("/seeded/proteins/BRD/BRD.pdb")

    assert url == "https://example.com/object"
    assert captured == [
        f"/files/{client.org_key}/signedUrl/seeded/proteins/BRD/BRD.pdb"
    ]


def test_download_direct_uses_normalized_path(
    client: DeepOriginClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """direct downloads must hit GET /files/{org}/{path} without a leading slash."""
    captured: list[str] = []

    def fake_get(path: str, **kwargs: object) -> httpx.Response:
        captured.append(path)
        return httpx.Response(200, content=b"ATOM")

    monkeypatch.setattr(client, "_get", fake_get)

    local_path = client.files.download(
        remote_path="/seeded/proteins/BRD/BRD.pdb",
        download_to_dir="/tmp",
        direct=True,
    )

    assert captured == [f"/files/{client.org_key}/seeded/proteins/BRD/BRD.pdb"]
    assert local_path.endswith("BRD.pdb")


def test_stat_uses_normalized_path(
    client: DeepOriginClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stat must HEAD the normalized remote path."""
    captured: list[str] = []

    def fake_head(path: str, **kwargs: object) -> httpx.Response:
        captured.append(path)
        return httpx.Response(200, headers={"content-length": "1"})

    monkeypatch.setattr(client, "_head", fake_head)

    headers = client.files.stat("/seeded/proteins/BRD/BRD.pdb")

    assert captured == [f"/files/{client.org_key}/seeded/proteins/BRD/BRD.pdb"]
    assert headers["content-length"] == "1"
