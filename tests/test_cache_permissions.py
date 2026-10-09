"""Tests for ~/.deeporigin and token file permission hardening."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeporigin.utils.env import _ensure_do_folder


def test_ensure_do_folder_sets_private_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_ensure_do_folder`` creates/repairs the cache dir as mode 0700."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    folder = _ensure_do_folder()

    assert folder == home / ".deeporigin"
    assert folder.is_dir()
    assert (folder.stat().st_mode & 0o777) == 0o700

    folder.chmod(0o755)
    repaired = _ensure_do_folder()
    assert repaired == folder
    assert (folder.stat().st_mode & 0o777) == 0o700
