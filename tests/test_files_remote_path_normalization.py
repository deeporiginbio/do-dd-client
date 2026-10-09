"""Tests for UFA remote path normalization in the Files client."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.files import (
    _assert_path_under_root,
    _normalize_remote_path,
)


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


@pytest.mark.parametrize(
    "bad_path",
    [
        "../.ssh/authorized_keys",
        "seeded/../../.ssh/authorized_keys",
        "seeded/proteins/../secrets.pdb",
        "seeded\\..\\secrets.pdb",
        "a\x00b.pdb",
    ],
)
def test_normalize_remote_path_rejects_traversal_and_nul(bad_path: str) -> None:
    """Paths with ``..`` segments or NUL must not be accepted."""
    with pytest.raises(ValueError):
        _normalize_remote_path(bad_path)


def test_assert_path_under_root_accepts_nested(tmp_path: Path) -> None:
    """Destinations inside the root are allowed."""
    dest = tmp_path / "seeded" / "proteins" / "BRD.pdb"
    _assert_path_under_root(dest, tmp_path)


def test_assert_path_under_root_rejects_escape(tmp_path: Path) -> None:
    """Resolved destinations outside the root are refused."""
    outside = tmp_path.parent / "outside.pdb"
    with pytest.raises(ValueError, match="outside root"):
        _assert_path_under_root(outside, tmp_path)


def test_assert_path_under_root_rejects_symlink_under_root(tmp_path: Path) -> None:
    """Pre-existing symlinks under the download root are refused."""
    outside = tmp_path.parent / "outside"
    outside.mkdir()
    link = tmp_path / "docking"
    link.symlink_to(outside, target_is_directory=True)
    dest = link / "payload.sdf"
    with pytest.raises(ValueError, match="crosses symlink"):
        _assert_path_under_root(dest, tmp_path)


def test_download_default_folder_accepts_nested_remote_path(
    client: DeepOriginClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Nested paths under ~/.deeporigin pass containment (including on Windows)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    def fake_download_to_path(
        _self: object,
        _remote_path: str,
        dest: Path,
    ) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"ATOM")

    monkeypatch.setattr(
        type(client.files),
        "_download_to_path",
        fake_download_to_path,
    )

    local_path = client.files.download(remote_path="docking/brd-2/pose.sdf")

    expected = home / ".deeporigin" / "docking" / "brd-2" / "pose.sdf"
    assert local_path == str(expected)
    assert expected.read_bytes() == b"ATOM"


def test_download_rejects_traversal_before_write(
    client: DeepOriginClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Traversal remote paths fail closed without calling the HTTP client."""
    called: list[str] = []

    def fake_get(path: str, **kwargs: object) -> httpx.Response:
        called.append(path)
        return httpx.Response(200, content=b"ATOM")

    monkeypatch.setattr(client, "_get", fake_get)

    with pytest.raises(ValueError, match="\\.\\."):
        client.files.download(
            remote_path="../../.ssh/authorized_keys",
            download_to_dir=str(tmp_path),
            direct=True,
        )

    assert called == []


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
    client: DeepOriginClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """direct downloads must hit GET /files/{org}/{path} without a leading slash."""
    captured: list[str] = []

    def fake_get(path: str, **kwargs: object) -> httpx.Response:
        captured.append(path)
        return httpx.Response(200, content=b"ATOM")

    monkeypatch.setattr(client, "_get", fake_get)

    local_path = client.files.download(
        remote_path="/seeded/proteins/BRD/BRD.pdb",
        download_to_dir=str(tmp_path),
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


def test_normalize_rejects_windows_trailing_dot_space_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Windows, '.. ' and 'a.' are rewritten by Win32 and must be refused."""
    monkeypatch.setattr(os, "name", "nt")
    for bad in ("seeded/.. /outside.txt", "seeded/... /x", "dir./x", "dir /x"):
        with pytest.raises(ValueError, match="end with a space"):
            _normalize_remote_path(bad)
    assert _normalize_remote_path("seeded/./ok.txt") == "seeded/./ok.txt"


def test_assert_path_under_root_rejects_junction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Windows directory junctions below the root count as crossings."""
    junction = tmp_path / "docking"
    junction.mkdir()
    monkeypatch.setattr(
        os.path,
        "isjunction",
        lambda p: os.path.abspath(p) == str(junction),
        raising=False,
    )
    with pytest.raises(ValueError, match="crosses symlink"):
        _assert_path_under_root(junction / "payload.sdf", tmp_path)


def test_is_junction_fallback_reads_reparse_point_attribute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without os.path.isjunction (3.11), the reparse-point attribute is used."""
    from types import SimpleNamespace

    from deeporigin.platform.files import _is_junction

    monkeypatch.delattr(os.path, "isjunction", raising=False)
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(
        os, "lstat", lambda _p: SimpleNamespace(st_file_attributes=0x410)
    )
    assert _is_junction(tmp_path)
    monkeypatch.setattr(
        os, "lstat", lambda _p: SimpleNamespace(st_file_attributes=0x10)
    )
    assert not _is_junction(tmp_path)
