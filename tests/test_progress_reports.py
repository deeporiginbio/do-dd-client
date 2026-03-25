"""Tests for the ProgressReports API wrapper."""

from deeporigin.platform.client import DeepOriginClient


def test_get_progress_reports():
    """Test fetching progress reports for a known execution ID."""
    client = DeepOriginClient()
    execution_id = "docking-test-execution-12345"

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
