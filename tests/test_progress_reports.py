"""Tests for the ProgressReports API wrapper."""

import json
from pathlib import Path

from deeporigin.platform.client import DeepOriginClient


def _docking_test_execution_id() -> str:
    """``executionId`` from ``fixtures/executions/docking-test-execution.json``."""
    path = Path(__file__).parent / "fixtures/executions/docking-test-execution.json"
    with path.open(encoding="utf-8") as f:
        return str(json.load(f)["executionId"])


def test_get_progress_reports():
    """Test fetching progress reports for a known execution ID (docking fixture)."""
    client = DeepOriginClient()
    execution_id = _docking_test_execution_id()

    response = client.progress_reports.get(execution_id)

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"
    assert len(response["data"]) > 0, "Expected at least one execution record"

    record = response["data"][0]
    assert record["executionId"] == execution_id


def test_get_progress_reports_not_found():
    """Test fetching progress reports for a non-existent execution ID returns empty."""
    client = DeepOriginClient()

    response = client.progress_reports.get(
        execution_id="non-existent-execution-id",
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"
    assert len(response["data"]) == 0, "Expected no results for non-existent ID"
