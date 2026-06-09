"""this module tests the tools API"""

import pytest

from deeporigin.platform.client import DeepOriginClient


def test_get_executions_lv1(client: DeepOriginClient):
    response = client.executions.list()
    jobs = response.get("data", [])
    assert isinstance(jobs, list), "Expected a list"
    assert len(jobs) > 0, "Expected at least one job"

    job = jobs[0]
    for expected_key in [
        "executionId",
        "status",
        "tool",
        "createdAt",
        "completedAt",
        "startedAt",
        "resourceId",
        "billingTransaction",
        "quotationResult",
        "cluster",
    ]:
        assert expected_key in job, f"Expected job to have key {expected_key}"


@pytest.mark.dependency()
def test_tools_api_health_lv1(client: DeepOriginClient):
    """test the health API"""
    data = client.get_json("/health")
    assert data["status"] == "ok"


@pytest.mark.dependency(depends=["test_tools_api_health_lv1"])
def test_get_all_tools_lv1(client: DeepOriginClient):
    """test the tools API"""
    tools = client.tools.list()
    assert isinstance(tools, list), "Expected a list"
    assert len(tools) > 0, "Expected at least one tool"

    # filter out test tool because they pollute the results and are missing fields
    tools = [tool for tool in tools if "test" not in tool["key"]]

    assert len(tools) > 0, "Expected at least one non-test tool after filtering"

    tool = tools[0]

    for key in [
        "key",
        "inputs",
        "version",
        "toolManifestVersion",
    ]:
        assert key in tool.keys(), f"Expected tool to have key {key}"


def test_job_status_logic_lv0(client: DeepOriginClient):
    """Test the simplified status logic for job rendering."""
    from deeporigin.platform.constants import TERMINAL_STATES

    # Test the status deduplication logic
    def get_unique_statuses(statuses):
        """Helper function to test the status deduplication logic."""
        return list(set(statuses)) if statuses else ["Unknown"]

    def should_auto_update(statuses):
        """Helper function to test the auto-update logic."""
        if not statuses:
            return True  # Empty status list should auto-update
        return not all(status in TERMINAL_STATES for status in statuses)

    # Test case 1: Empty status list
    statuses = []
    unique_statuses = get_unique_statuses(statuses)
    assert unique_statuses == ["Unknown"]
    assert should_auto_update(statuses) is True

    # Test case 2: Single status
    statuses = ["Running"]
    unique_statuses = get_unique_statuses(statuses)
    assert unique_statuses == ["Running"]
    assert should_auto_update(statuses) is True

    # Test case 3: Multiple same statuses (should deduplicate)
    statuses = ["Running", "Running", "Running"]
    unique_statuses = get_unique_statuses(statuses)
    assert unique_statuses == ["Running"]
    assert should_auto_update(statuses) is True

    # Test case 4: Mixed statuses
    statuses = ["Running", "Completed", "Failed"]
    unique_statuses = get_unique_statuses(statuses)
    assert set(unique_statuses) == {"Running", "Completed", "Failed"}
    assert should_auto_update(statuses) is True

    # Test case 5: All terminal states (should stop auto-update)
    statuses = ["Completed", "Failed", "Cancelled"]
    unique_statuses = get_unique_statuses(statuses)
    assert set(unique_statuses) == {"Completed", "Failed", "Cancelled"}
    assert should_auto_update(statuses) is False

    # Test case 6: FailedQuotation status
    statuses = ["FailedQuotation"]
    unique_statuses = get_unique_statuses(statuses)
    assert unique_statuses == ["FailedQuotation"]
    assert should_auto_update(statuses) is False

    # Test case 7: Mixed terminal and non-terminal states
    statuses = ["Running", "Completed", "Failed"]
    unique_statuses = get_unique_statuses(statuses)
    assert set(unique_statuses) == {"Running", "Completed", "Failed"}
    assert should_auto_update(statuses) is True

    # Test case 8: Verify TERMINAL_STATES constant includes all expected states
    expected_terminal_states = {
        "Failed",
        "FailedQuotation",
        "Completed",
        "Succeeded",
        "Cancelled",
        "Quoted",
        "InsufficientFunds",
    }
    assert set(TERMINAL_STATES) == expected_terminal_states
