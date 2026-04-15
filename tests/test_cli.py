"""Tests for the ``deeporigin`` Typer CLI."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from deeporigin.cli import app


@pytest.fixture
def cli_runner() -> CliRunner:
    """Return a Typer CLI test runner."""
    return CliRunner()


def test_results_get_poses_invokes_api_and_prints_json(cli_runner: CliRunner) -> None:
    """``results get-poses`` delegates to ``Results.get_poses`` and prints JSON."""
    mock_response = {"data": [{"id": "pose-1"}], "meta": {}}
    mock_client = MagicMock()
    mock_client.results.get_poses.return_value = mock_response

    with patch("deeporigin.cli.DeepOriginClient", return_value=mock_client):
        result = cli_runner.invoke(
            app,
            ["results", "get-poses", "--limit", "1", "--effort", "1"],
        )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == mock_response
    mock_client.results.get_poses.assert_called_once_with(
        protein_id=None,
        ligand_id=None,
        compute_job_id=None,
        tool_version=None,
        effort=1,
        best_pose=None,
        limit=1,
        select=None,
    )


def test_results_get_poses_repeatable_ligand_id(cli_runner: CliRunner) -> None:
    """Multiple ``--ligand-id`` values are passed as a list."""
    mock_client = MagicMock()
    mock_client.results.get_poses.return_value = {"data": [], "meta": {}}

    with patch("deeporigin.cli.DeepOriginClient", return_value=mock_client):
        result = cli_runner.invoke(
            app,
            [
                "results",
                "get-poses",
                "--ligand-id",
                "a",
                "--ligand-id",
                "b",
            ],
        )

    assert result.exit_code == 0
    call_kw = mock_client.results.get_poses.call_args.kwargs
    assert call_kw["ligand_id"] == ["a", "b"]


def test_results_get_pockets_invokes_api_and_prints_json(cli_runner: CliRunner) -> None:
    """``results get-pockets`` delegates to ``Results.get_pockets`` and prints JSON."""
    mock_response = {"data": [{"id": "pocket-1"}], "meta": {}}
    mock_client = MagicMock()
    mock_client.results.get_pockets.return_value = mock_response

    with patch("deeporigin.cli.DeepOriginClient", return_value=mock_client):
        result = cli_runner.invoke(
            app,
            [
                "results",
                "get-pockets",
                "--protein",
                "08BSPN61NYVE3",
                "--limit",
                "1",
                "--pocket-count",
                "1",
            ],
        )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == mock_response
    mock_client.results.get_pockets.assert_called_once_with(
        id=None,
        protein_id="08BSPN61NYVE3",
        compute_job_id=None,
        pocket_count=1,
        pocket_min_size=None,
        tool_version=None,
        limit=1,
        select=None,
    )


def test_entities_get_protein_invokes_api_and_prints_json(
    cli_runner: CliRunner,
) -> None:
    """``entities get-protein`` delegates to ``Entities.get_protein`` and prints JSON."""
    mock_response = {"id": "08BSPN61NYVE3", "name": "BRD4"}
    mock_client = MagicMock()
    mock_client.entities.get_protein.return_value = mock_response

    with patch("deeporigin.cli.DeepOriginClient", return_value=mock_client):
        result = cli_runner.invoke(
            app,
            ["entities", "get-protein", "--id", "08BSPN61NYVE3"],
        )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == mock_response
    mock_client.entities.get_protein.assert_called_once_with(id="08BSPN61NYVE3")


def test_entities_get_ligand_invokes_api_and_prints_json(cli_runner: CliRunner) -> None:
    """``entities get-ligand`` delegates to ``Entities.get_ligand`` and prints JSON."""
    mock_response = {"id": "LIG123", "smiles": "CCO"}
    mock_client = MagicMock()
    mock_client.entities.get_ligand.return_value = mock_response

    with patch("deeporigin.cli.DeepOriginClient", return_value=mock_client):
        result = cli_runner.invoke(
            app,
            ["entities", "get-ligand", "--id", "LIG123"],
        )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == mock_response
    mock_client.entities.get_ligand.assert_called_once_with(id="LIG123")
