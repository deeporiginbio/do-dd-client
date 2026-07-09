"""Tests for on-disk configuration management."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Generator

import pandas as pd
import pytest

import deeporigin.config as config_module
from deeporigin.config import (
    _ensure_config_file_exists,
    get_env,
    get_org,
    get_value,
    set_env,
    set_org,
)
from deeporigin.exceptions import DeepOriginException
from deeporigin.utils.constants import ENV_VARIABLES


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect config.json to a temporary path."""
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "CONFIG_JSON_LOCATION", path)
    return path


@pytest.fixture(autouse=True)
def clear_config_env() -> Generator[None, None, None]:
    """Clear config-related environment variables between tests."""
    keys = [ENV_VARIABLES["env"], ENV_VARIABLES["org_key"]]
    old = {key: os.environ.get(key) for key in keys}
    for key in keys:
        os.environ.pop(key, None)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_ensure_config_file_exists_creates_defaults(config_path: Path) -> None:
    """_ensure_config_file_exists writes default env and org_key."""
    _ensure_config_file_exists()

    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data == {"env": "prod", "org_key": ""}


def test_get_value_reads_file(config_path: Path) -> None:
    """get_value returns values from config.json."""
    config_path.write_text(
        json.dumps({"env": "staging", "org_key": "my-org"}),
        encoding="utf-8",
    )

    assert get_value() == {"env": "staging", "org_key": "my-org"}


def test_get_value_env_overrides(
    config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Environment variables override config file values."""
    config_path.write_text(
        json.dumps({"env": "prod", "org_key": "file-org"}),
        encoding="utf-8",
    )
    monkeypatch.setenv(ENV_VARIABLES["env"], "dev")
    monkeypatch.setenv(ENV_VARIABLES["org_key"], "env-org")

    assert get_value() == {"env": "dev", "org_key": "env-org"}


def test_get_env_and_get_org(config_path: Path) -> None:
    """get_env and get_org are thin wrappers over get_value."""
    config_path.write_text(
        json.dumps({"env": "dev", "org_key": "org-1"}),
        encoding="utf-8",
    )

    assert get_env() == "dev"
    assert get_org() == "org-1"


def test_set_env_writes_file(
    config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """set_env persists the environment and prints confirmation."""
    monkeypatch.setattr(
        "deeporigin.config._supports_unicode_output",
        lambda: False,
    )

    set_env("staging")

    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["env"] == "staging"
    assert "OK env -> staging" in capsys.readouterr().out


def test_set_org_valid_key(
    config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """set_org updates org_key when the key exists in list_orgs."""
    _ensure_config_file_exists()
    orgs = pd.DataFrame(
        {
            "name": ["Org A"],
            "key": ["org-a"],
            "autoApproveMaxAmount": [100],
            "threshold": [10],
        }
    )
    monkeypatch.setattr(config_module, "list_orgs", lambda: orgs)
    monkeypatch.setattr(
        "deeporigin.config._supports_unicode_output",
        lambda: False,
    )

    set_org("org-a")

    assert get_org() == "org-a"


def test_set_org_invalid_key_raises(
    config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """set_org raises DeepOriginException for unknown organization keys."""
    _ensure_config_file_exists()
    orgs = pd.DataFrame(
        {
            "name": ["Org A"],
            "key": ["org-a"],
            "autoApproveMaxAmount": [100],
            "threshold": [10],
        }
    )
    monkeypatch.setattr(config_module, "list_orgs", lambda: orgs)

    with pytest.raises(DeepOriginException, match="Invalid organization key"):
        set_org("missing-org")
