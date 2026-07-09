"""Tests for terminal display helpers."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

from deeporigin.utils.display import (
    _supports_color,
    _supports_unicode_output,
    _truncate,
    humanize_file_size,
)


def test_supports_unicode_output_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    """_supports_unicode_output returns True for UTF encodings."""
    fake_stdout = SimpleNamespace(encoding="utf-8")
    monkeypatch.setattr("deeporigin.utils.display.sys.stdout", fake_stdout)

    assert _supports_unicode_output() is True


def test_supports_unicode_output_missing_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_supports_unicode_output returns False when encoding is unknown."""
    fake_stdout = SimpleNamespace(encoding=None)
    monkeypatch.setattr("deeporigin.utils.display.sys.stdout", fake_stdout)

    assert _supports_unicode_output() is False


def test_supports_color_tty_without_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    """_supports_color returns True for a capable TTY."""
    fake_stdout = SimpleNamespace(isatty=lambda: True)
    monkeypatch.setattr("deeporigin.utils.display.sys.stdout", fake_stdout)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(sys, "platform", "linux")

    assert _supports_color() is True


def test_supports_color_disabled_by_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    """_supports_color returns False when NO_COLOR is set."""
    fake_stdout = SimpleNamespace(isatty=lambda: True)
    monkeypatch.setattr("deeporigin.utils.display.sys.stdout", fake_stdout)
    monkeypatch.setenv("NO_COLOR", "1")

    assert _supports_color() is False


def test_supports_color_non_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """_supports_color returns False when stdout is not a TTY."""
    fake_stdout = SimpleNamespace(isatty=lambda: False)
    monkeypatch.setattr("deeporigin.utils.display.sys.stdout", fake_stdout)

    assert _supports_color() is False


def test_humanize_file_size_bytes() -> None:
    """humanize_file_size formats small byte counts."""
    assert humanize_file_size(512) == "512.00 B"


def test_humanize_file_size_kilobytes() -> None:
    """humanize_file_size scales into kilobytes."""
    assert humanize_file_size(2048) == "2.00 KB"


def test_truncate_short_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """_truncate leaves short strings unchanged."""
    monkeypatch.setattr(
        "deeporigin.utils.display.shutil.get_terminal_size",
        lambda: os.terminal_size((80, 24)),
    )
    assert _truncate("short") == "short"


def test_truncate_long_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """_truncate adds ellipsis when text exceeds half the terminal width."""
    monkeypatch.setattr(
        "deeporigin.utils.display.shutil.get_terminal_size",
        lambda: os.terminal_size((40, 24)),
    )
    text = "x" * 30
    truncated = _truncate(text)

    assert truncated.endswith("...")
    assert len(truncated) == 20


def test_truncate_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """_truncate returns None unchanged."""
    monkeypatch.setattr(
        "deeporigin.utils.display.shutil.get_terminal_size",
        lambda: os.terminal_size((80, 24)),
    )
    assert _truncate(None) is None
