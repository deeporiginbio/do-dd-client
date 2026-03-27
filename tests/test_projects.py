"""Tests for ``deeporigin.projects`` and project-scoped config."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from deeporigin.exceptions import DeepOriginException


def test_get_project_id_reads_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_project_id returns the value persisted on disk."""

    import deeporigin.config as cfg

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps({"env": "prod", "org_key": "", "project_id": "proj-abc"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg, "CONFIG_JSON_LOCATION", cfg_path)

    assert cfg.get_project_id() == "proj-abc"


def test_get_value_includes_project_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_value exposes project_id from the config file."""

    import deeporigin.config as cfg

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps({"env": "prod", "org_key": "org1", "project_id": "xyz"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg, "CONFIG_JSON_LOCATION", cfg_path)

    assert cfg.get_value()["project_id"] == "xyz"


def test_ligands_requires_current_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """ligands() raises when no project is selected."""

    monkeypatch.setattr("deeporigin.projects.get_project_id", lambda: None)
    from deeporigin.projects import ligands

    with pytest.raises(DeepOriginException, match="No current project"):
        ligands()


def test_projects_list_builds_dataframe(monkeypatch: pytest.MonkeyPatch) -> None:
    """list() returns a DataFrame with id, name, description columns."""

    import pandas as pd

    mock_projects = MagicMock()
    mock_projects.list.return_value = {
        "data": [
            {"id": "p1", "name": "Alpha", "description": "d1", "extra": 1},
        ],
        "count": 1,
    }
    mock_client = MagicMock()
    mock_client.projects = mock_projects

    monkeypatch.setattr(
        "deeporigin.projects.DeepOriginClient.get",
        lambda: mock_client,
    )

    from deeporigin.projects import list as projects_list

    df = projects_list()
    assert list(df.columns) == ["id", "name", "description"]
    assert df.iloc[0]["id"] == "p1"
    assert df.iloc[0]["name"] == "Alpha"
    assert isinstance(df, pd.DataFrame)


def test_projects_create_sets_config_when_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """create(..., load=True) writes the new project id to config."""

    import deeporigin.config as cfg

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps({"env": "prod", "org_key": "", "project_id": None}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg, "CONFIG_JSON_LOCATION", cfg_path)

    mock_projects = MagicMock()
    mock_projects.create.return_value = {"data": {"id": "new-id-1"}}
    mock_client = MagicMock()
    mock_client.projects = mock_projects

    monkeypatch.setattr(
        "deeporigin.projects.DeepOriginClient.get",
        lambda: mock_client,
    )

    from deeporigin.projects import create

    create("my-project", load=True)

    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert data["project_id"] == "new-id-1"


def test_projects_load_resolves_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """load() matches by project name."""

    mock_projects = MagicMock()
    mock_projects.list.return_value = {
        "data": [
            {"id": "id-99", "name": "Demo", "slug": "demo-x", "description": None},
        ],
    }
    mock_client = MagicMock()
    mock_client.projects = mock_projects

    monkeypatch.setattr(
        "deeporigin.projects.DeepOriginClient.get",
        lambda: mock_client,
    )
    mock_set = MagicMock()
    monkeypatch.setattr("deeporigin.projects.set_project_id", mock_set)

    from deeporigin.projects import load

    load("Demo")

    mock_set.assert_called_once_with("id-99")


def test_platform_projects_search_merges_deleted() -> None:
    """Projects.search sets deleted False when absent."""

    from deeporigin.platform.projects import Projects

    calls: list[dict[str, Any]] = []

    def fake_post_json(path: str, body: dict[str, Any], **kwargs: Any) -> dict:
        calls.append(body)
        return {"data": [], "count": 0}

    client = MagicMock()
    client.org_key = "org"
    client.post_json = fake_post_json

    p = Projects(client)
    p.search(filter_dict={"name": "x"})

    assert calls[0]["filter"]["deleted"] is False
    assert calls[0]["filter"]["name"] == "x"
