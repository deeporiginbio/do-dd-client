"""Tests for the Results API wrapper."""

import os

from deeporigin.platform.client import DeepOriginClient


def _get_result_explorer_ids() -> tuple[str, str, str | None]:
    """Return (tool_id, protein_id, tool_version) for result-explorer tests.

    For local env, returns hardcoded values matching the fixture data.
    For remote envs, uses the same known protein but leaves tool_version
    as None so the test doesn't assert on a specific version.

    Returns:
        Tuple of (tool_id, protein_id, tool_version).
    """
    tool_id = "deeporigin.bulk-docking"
    protein_id = "08BSPN61NYVE3"
    if os.environ.get("DO_ENV") == "local":
        return tool_id, protein_id, "0.6.6"
    return tool_id, protein_id, None


def test_get_results_lv1():
    """Test searching result-explorer records filtered by tool and protein."""
    client = DeepOriginClient()
    tool_id, protein_id, _ = _get_result_explorer_ids()

    response = client.results.get(
        tool_id=tool_id,
        protein_id=protein_id,
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"
    assert len(response["data"]) > 0, "Expected at least one result"

    for record in response["data"]:
        for field in ("id", "tool_id", "tool_version", "data", "execution_id"):
            assert field in record, f"Expected '{field}' key in record"


def test_get_results_with_tool_version_lv1():
    """Test results.get with an explicit tool_version filter."""
    client = DeepOriginClient()
    tool_id, protein_id, tool_version = _get_result_explorer_ids()

    response = client.results.get(
        tool_id=tool_id,
        protein_id=protein_id,
        tool_version=tool_version,
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"

    if tool_version is not None:
        for record in response["data"]:
            assert record.get("tool_version") == tool_version, (
                "Expected all records to match the requested tool_version"
            )
