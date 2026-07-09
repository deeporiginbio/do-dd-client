"""Tests for filesystem utilities."""

import os
from pathlib import Path

import pytest

from deeporigin.utils.filesystem import (
    ensure_file_extension,
    expand_user,
    fix_embedded_newlines_in_csv,
)


def test_fix_embedded_newlines_in_csv_no_op(tmp_path: Path) -> None:
    """Return False when the file has no literal backslash-n sequences."""
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")

    assert fix_embedded_newlines_in_csv(csv_path) is False
    assert csv_path.read_text(encoding="utf-8") == "a,b\n1,2\n"


def test_fix_embedded_newlines_in_csv_rewrites(tmp_path: Path) -> None:
    """Replace literal \\n sequences with real newlines in place."""
    csv_path = tmp_path / "data.csv"
    csv_path.write_text(r"a,b\n1,2", encoding="utf-8")

    assert fix_embedded_newlines_in_csv(csv_path) is True
    assert csv_path.read_text(encoding="utf-8") == "a,b\n1,2"


def test_ensure_file_extension_already_correct(tmp_path: Path) -> None:
    """Leave paths that already have the desired extension unchanged."""
    sdf = tmp_path / "ligand.sdf"
    sdf.write_text("dummy", encoding="utf-8")

    result = ensure_file_extension(file_paths=[sdf], extension=".sdf")

    assert result == [str(sdf)]
    assert sdf.exists()


def test_ensure_file_extension_renames(tmp_path: Path) -> None:
    """Rename files that lack the desired extension."""
    src = tmp_path / "ligand"
    src.write_text("dummy", encoding="utf-8")

    result = ensure_file_extension(file_paths=[src], extension="sdf")

    assert result == [str(tmp_path / "ligand.sdf")]
    assert not src.exists()
    assert (tmp_path / "ligand.sdf").exists()


def test_ensure_file_extension_target_exists(tmp_path: Path) -> None:
    """Return existing target path when rename target already exists."""
    src = tmp_path / "ligand"
    src.write_text("new", encoding="utf-8")
    existing = tmp_path / "ligand.sdf"
    existing.write_text("old", encoding="utf-8")

    result = ensure_file_extension(file_paths=[src], extension=".sdf")

    assert result == [str(existing)]
    assert src.exists()
    assert existing.read_text(encoding="utf-8") == "old"


def test_expand_user_tilde_only() -> None:
    """Expand a lone tilde to the home directory."""
    assert expand_user("~", user_home_dirname="/home/tester") == "/home/tester"


def test_expand_user_tilde_path() -> None:
    """Expand tilde-prefixed paths under the home directory."""
    home = "/home/tester"
    path = f"~{os.path.sep}data"
    assert expand_user(path, user_home_dirname=home) == os.path.join(home, "data")


def test_expand_user_absolute_passthrough() -> None:
    """Return absolute paths unchanged."""
    path = "/var/data/file.txt"
    assert expand_user(path, user_home_dirname="/home/tester") == path
