"""this module tests the tools API"""

import pytest

from deeporigin.drug_discovery.constants import tool_mapper
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.job import Job, JobList


def test_get_tool_executions_lv1():
    client = DeepOriginClient()
    response = client.executions.list(filter=None)
    jobs = response.get("data", [])

    assert isinstance(jobs, list), "Expected a list"
    assert len(jobs) > 0, "Expected at least one job"


def test_get_executions_lv1():
    client = DeepOriginClient()
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
def test_tools_api_health_lv1():
    """test the health API"""
    client = DeepOriginClient()
    data = client.get_json("/health")
    assert data["status"] == "ok"


@pytest.mark.dependency(depends=["test_tools_api_health_lv1"])
def test_get_all_tools_lv1():
    """test the tools API"""
    client = DeepOriginClient()
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
        "executors",
        "billingParser",
        "toolManifestVersion",
    ]:
        assert key in tool.keys(), f"Expected tool to have key {key}"


@pytest.mark.dependency(depends=["test_tools_api_health_lv1"])
def test_get_all_function_lv1():
    """Test the functions API list method."""
    client = DeepOriginClient()
    functions = client.functions.list()
    assert isinstance(functions, list), "Expected a list"
    assert len(functions) > 0, "Expected at least one function"

    function = functions[0]

    for key in [
        "id",
        "createdAt",
        "updatedAt",
        "functionManifest",
        "version",
        "enabled",
        "manifestBody",
        "billingCode",
        "resourceId",
    ]:
        assert key in function.keys(), f"Expected function to have key {key}"


def test_job_lv1():
    client = DeepOriginClient()
    response = client.executions.list()
    jobs = response.get("data", [])
    execution_id = jobs[0]["executionId"]
    job = Job.from_id(execution_id, client=client)

    assert execution_id == job.id


def test_job_from_dto_lv1():
    """Test Job.from_dto() creates a Job without making a network request."""
    client = DeepOriginClient()
    response = client.executions.list()
    jobs = response.get("data", [])
    execution_dto = jobs[0]

    # Create job from DTO (should not make network request)
    job = Job.from_dto(execution_dto, client=client)

    assert execution_dto["executionId"] == job.id
    assert execution_dto["status"] == job.status
    assert job._attributes == execution_dto
    # Verify that _skip_sync was set (though it's a private field)
    assert job._skip_sync is True


def test_job_df_lv1():
    client = DeepOriginClient()
    jobs = JobList.list(client=client)
    _ = jobs.to_dataframe(client=client)


@pytest.mark.dependency()
def test_job_df_filtering_lv1():
    client = DeepOriginClient()
    tool_key = tool_mapper["Docking"]

    jobs = JobList.list(client=client)
    df = jobs.filter(tool_key=tool_key).to_dataframe(client=client)

    assert len(df["tool_key"].unique()) <= 1, (
        f"should at most be one tool key. Instead there were {len(df['tool_key'].unique())}"
    )


def test_job_status_logic_lv0():
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
    statuses = ["Running", "Succeeded", "Failed"]
    unique_statuses = get_unique_statuses(statuses)
    assert set(unique_statuses) == {"Running", "Succeeded", "Failed"}
    assert should_auto_update(statuses) is True

    # Test case 5: All terminal states (should stop auto-update)
    statuses = ["Succeeded", "Failed", "Cancelled"]
    unique_statuses = get_unique_statuses(statuses)
    assert set(unique_statuses) == {"Succeeded", "Failed", "Cancelled"}
    assert should_auto_update(statuses) is False

    # Test case 6: FailedQuotation status
    statuses = ["FailedQuotation"]
    unique_statuses = get_unique_statuses(statuses)
    assert unique_statuses == ["FailedQuotation"]
    assert should_auto_update(statuses) is False

    # Test case 7: Mixed terminal and non-terminal states
    statuses = ["Running", "Succeeded", "Failed"]
    unique_statuses = get_unique_statuses(statuses)
    assert set(unique_statuses) == {"Running", "Succeeded", "Failed"}
    assert should_auto_update(statuses) is True

    # Test case 8: Verify TERMINAL_STATES constant includes all expected states
    expected_terminal_states = {
        "Failed",
        "FailedQuotation",
        "Succeeded",
        "Cancelled",
        "Quoted",
        "InsufficientFunds",
    }
    assert set(TERMINAL_STATES) == expected_terminal_states
