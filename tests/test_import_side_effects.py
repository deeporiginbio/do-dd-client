"""Regression tests for import-time side effects in config and platform client."""

from __future__ import annotations

import pathlib
import sys

import pytest


def _blocked_home(tmp_path: pathlib.Path) -> pathlib.Path:
    """Return a HOME path whose parent directory does not exist."""
    return tmp_path / "missing" / "home"


@pytest.fixture
def blocked_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> pathlib.Path:
    """Point HOME at a path whose parent cannot be created implicitly."""
    home = _blocked_home(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    return home


def _clear_deeporigin_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop cached deeporigin modules so imports observe the patched HOME."""
    for name in list(sys.modules):
        if name.startswith("deeporigin"):
            monkeypatch.delitem(sys.modules, name, raising=False)


def test_import_config_does_not_create_deeporigin_dir(
    blocked_home: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing deeporigin.config must not mkdir ~/.deeporigin."""
    _clear_deeporigin_modules(monkeypatch)

    import deeporigin.config as config_module

    assert (
        config_module.CONFIG_JSON_LOCATION
        == blocked_home / ".deeporigin" / "config.json"
    )
    assert not (blocked_home / ".deeporigin").exists()


def test_import_platform_client_does_not_create_deeporigin_dir(
    blocked_home: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing DeepOriginClient must not mkdir ~/.deeporigin."""
    _clear_deeporigin_modules(monkeypatch)

    from deeporigin.platform.client import DeepOriginClient

    assert DeepOriginClient is not None
    assert not (blocked_home / ".deeporigin").exists()
