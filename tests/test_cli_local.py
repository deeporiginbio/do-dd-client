"""Local integration tests for the ``deeporigin`` Typer CLI (--env local)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from deeporigin.cli import app
from tests.mock_server.routers.data_platform import MOCK_CANONICAL_PROTEIN_ID


@pytest.fixture
def cli_runner() -> CliRunner:
    """Return a Typer CLI test runner."""
    return CliRunner()


def test_entities_get_protein_local(cli_runner: CliRunner) -> None:
    """``entities get-protein`` returns the canonical mock protein as JSON."""
    result = cli_runner.invoke(
        app,
        ["entities", "get-protein", "--id", MOCK_CANONICAL_PROTEIN_ID],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    body = json.loads(result.stdout)
    assert body["id"] == MOCK_CANONICAL_PROTEIN_ID
    assert body["protein_name"] == "brd"


def test_results_get_poses_local(cli_runner: CliRunner) -> None:
    """``results get-poses`` hits the mock result-explorer and prints JSON."""
    result = cli_runner.invoke(
        app,
        ["results", "get-poses", "--limit", "1"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    body = json.loads(result.stdout)
    assert "data" in body
    assert isinstance(body["data"], list)
