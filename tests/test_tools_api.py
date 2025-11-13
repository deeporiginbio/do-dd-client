"""this module tests the tools API"""

import time

import pytest

from deeporigin.drug_discovery import (
    BRD_DATA_DIR,
    Complex,
)
from deeporigin.drug_discovery.constants import tool_mapper
from deeporigin.platform.job import Job, get_dataframe
from tests.utils import client  # noqa: F401


def test_get_tool_executions(client):  # noqa: F811
    response = client.executions.list(filter=None)
    jobs = response.get("data", [])

    assert isinstance(jobs, list), "Expected a list"
    assert len(jobs) > 0, "Expected at least one job"


def test_get_executions(client):  # noqa: F811
    response = client.executions.list()
    jobs = response.get("data", [])
    assert isinstance(jobs, list), "Expected a list"
    assert len(jobs) > 0, "Expected at least one job"


@pytest.mark.dependency()
def test_tools_api_health(client):  # noqa: F811
    """test the health API"""

    data = client.get_json("/health")
    assert data["status"] == "ok"


@pytest.mark.dependency(depends=["test_tools_api_health"])
def test_get_all_tools(client):  # noqa: F811
    """test the tools API"""

    response = client.tools.get_all()
    tools = response.get("data", [])
    assert len(tools) > 0, "Expected at least one tool"

    print(f"Found {len(tools)} tools")


@pytest.mark.dependency(depends=["test_tools_api_health"])
def test_get_all_executions(client):  # noqa: F811
    """test the executions API"""

    response = client.executions.list()
    executions = response.get("data", [])

    print(f"Found {len(executions)} executions")


def test_job(client):  # noqa: F811
    response = client.executions.list()
    jobs = response.get("data", [])
    execution_id = jobs[0]["executionId"]
    job = Job.from_id(execution_id, client=client)

    assert execution_id == job._id


def test_job_from_dto(client):  # noqa: F811
    """Test Job.from_dto() creates a Job without making a network request."""
    response = client.executions.list()
    jobs = response.get("data", [])
    execution_dto = jobs[0]

    # Create job from DTO (should not make network request)
    job = Job.from_dto(execution_dto, client=client)

    assert execution_dto["executionId"] == job._id
    assert execution_dto["status"] == job.status
    assert job._attributes == execution_dto
    # Verify that _skip_sync was set (though it's a private field)
    assert job._skip_sync is True


def test_job_df(client):  # noqa: F811
    _ = get_dataframe(client=client)


@pytest.mark.dependency()
def test_job_df_filtering(client):  # noqa: F811
    tool_key = tool_mapper["Docking"]

    df = get_dataframe(
        tool_key=tool_key,
        client=client,
    )

    assert len(df["tool_key"].unique()) == 1, (
        f"should only be one tool key. Instead there were {len(df['tool_key'].unique())}"
    )

    assert df["tool_key"].unique()[0] == tool_key, (
        f"Expected to get back jobs for {tool_key}. Instead got {df['tool_key'].unique()[0]}"
    )


def test_run_docking_and_cancel(client, pytestconfig):  # noqa: F811
    """Test running a docking job and canceling it.

    Note: This test is skipped when using --mock flag as the mock server
    doesn't implement job execution endpoints yet.
    """
    use_mock = pytestconfig.getoption("--mock", default=False)
    if use_mock:
        pytest.skip(
            "Skipping docking run/cancel test with --mock (not yet implemented)"
        )

    sim = Complex.from_dir(BRD_DATA_DIR, client=client)
    sim.client = client

    job = sim.docking.run(
        box_size=(14.094597464129786, 14.094597464129786, 14.094597464129786),
        pocket_center=(-13.215283393859863, -6.083978652954102, 14.214159965515137),
        re_run=True,
        use_parallel=False,
    )

    # wait for a bit to start
    time.sleep(10)

    # check that it's running
    job.sync()
    assert "Running" in job._status, f"Job with ID {job._ids} is not running"

    # now cancel it
    job.cancel()

    # wait for a bit to cancel
    time.sleep(10)

    # check that it's cancelled
    job.sync()
    assert "Cancelled" in job._status, f"Job with ID {job._ids} is not cancelled"


def test_job_status_logic():
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
