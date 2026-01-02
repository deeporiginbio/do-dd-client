"""Tests for the JobList class."""

import pandas as pd
import pytest

from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.job import Job, JobList


@pytest.fixture
def client():
    """Create a DeepOriginClient for testing."""
    return DeepOriginClient()


def create_job_dto(**kwargs):
    """Create a job DTO with default values, allowing overrides.

    Args:
        **kwargs: Fields to override in the default DTO.

    Returns:
        A job DTO dictionary.
    """
    default_dto = {
        "executionId": "id-1",
        "status": "Succeeded",
        "createdAt": "2025-01-01T00:00:00.000Z",
        "updatedAt": "2025-01-01T01:00:00.000Z",
        "resourceId": "resource-1",
        "orgKey": "deeporigin",
        "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
    }
    default_dto.update(kwargs)
    return default_dto


@pytest.fixture
def job_dtos():
    """Create a list of execution DTOs for testing."""
    return [
        create_job_dto(
            executionId="job-0", status="Succeeded", resourceId="resource-0"
        ),
        create_job_dto(executionId="job-1", status="Running", resourceId="resource-1"),
        create_job_dto(
            executionId="job-2", status="Succeeded", resourceId="resource-2"
        ),
        create_job_dto(executionId="job-3", status="Failed", resourceId="resource-3"),
        create_job_dto(executionId="job-4", status="Running", resourceId="resource-4"),
    ]


@pytest.fixture
def mock_jobs(client, job_dtos):
    """Create a list of real Job objects from DTOs."""
    return [Job.from_dto(dto, client=client) for dto in job_dtos]


def test_job_list_initialization_lv0(mock_jobs):
    """Test JobList initialization."""
    job_list = JobList(mock_jobs)
    assert len(job_list) == 5
    assert job_list.jobs == mock_jobs


def test_job_list_iteration_lv0(mock_jobs):
    """Test iterating over JobList."""
    job_list = JobList(mock_jobs)
    for i, job in enumerate(job_list):
        assert job == mock_jobs[i]


def test_job_list_getitem_lv0(mock_jobs):
    """Test accessing jobs by index."""
    job_list = JobList(mock_jobs)
    assert job_list[0] == mock_jobs[0]
    assert job_list[-1] == mock_jobs[-1]
    # Test slice indexing
    assert job_list[0:2] == mock_jobs[0:2]


def test_job_list_repr_html_lv0(client):
    """Test HTML representation of JobList."""
    job1 = Job.from_dto(
        create_job_dto(executionId="id-1", status="Succeeded", resourceId="resource-1"),
        client=client,
    )
    job2 = Job.from_dto(
        create_job_dto(executionId="id-2", status="Running", resourceId="resource-2"),
        client=client,
    )
    job3 = Job.from_dto(
        create_job_dto(executionId="id-3", status="Succeeded", resourceId="resource-3"),
        client=client,
    )

    job_list = JobList([job1, job2, job3])
    html = job_list._repr_html_()

    # Check that HTML contains expected information
    assert "3" in html  # Number of jobs
    assert "Status breakdown:" in html
    assert (
        "Succeeded" in html and "2" in html
    )  # Status count (may be separated by HTML tags)
    assert (
        "Running" in html and "1" in html
    )  # Status count (may be separated by HTML tags)
    assert isinstance(html, str)


def test_job_list_repr_html_empty_lv0():
    """Test HTML representation of empty JobList."""
    job_list = JobList([])
    html = job_list._repr_html_()

    assert "0" in html  # Number of jobs
    assert "No status information" in html


def test_job_list_status_lv0(mock_jobs):
    """Test status property returns correct breakdown."""
    job_list = JobList(mock_jobs)
    status_counts = job_list.status

    assert status_counts["Succeeded"] == 2
    assert status_counts["Running"] == 2
    assert status_counts["Failed"] == 1
    assert "Queued" not in status_counts


def test_filter_by_status_lv0(client):
    """Test filtering jobs by status."""
    job1 = Job.from_dto(
        create_job_dto(executionId="id-1", status="Succeeded", resourceId="resource-1"),
        client=client,
    )
    job2 = Job.from_dto(
        create_job_dto(executionId="id-2", status="Running", resourceId="resource-2"),
        client=client,
    )
    job3 = Job.from_dto(
        create_job_dto(executionId="id-3", status="Succeeded", resourceId="resource-3"),
        client=client,
    )

    job_list = JobList([job1, job2, job3])

    # Filter by status
    succeeded = job_list.filter(status="Succeeded")
    assert len(succeeded) == 2
    assert all(job.status == "Succeeded" for job in succeeded)

    running = job_list.filter(status="Running")
    assert len(running) == 1
    assert running[0].status == "Running"

    failed = job_list.filter(status="Failed")
    assert len(failed) == 0


def test_filter_by_attributes_lv0(client):
    """Test filtering jobs by attributes."""
    job1 = Job.from_dto(
        create_job_dto(
            executionId="id-1",
            status="Succeeded",
            resourceId="resource-1",
            approveAmount=100,
        ),
        client=client,
    )
    job2 = Job.from_dto(
        create_job_dto(
            executionId="id-2",
            status="Running",
            resourceId="resource-2",
            approveAmount=200,
        ),
        client=client,
    )
    job3 = Job.from_dto(
        create_job_dto(
            executionId="id-1",
            status="Failed",
            resourceId="resource-3",
            approveAmount=100,
        ),
        client=client,
    )

    job_list = JobList([job1, job2, job3])

    # Filter by executionId
    filtered = job_list.filter(executionId="id-1")
    assert len(filtered) == 2
    assert all(job._attributes.get("executionId") == "id-1" for job in filtered)

    # Filter by multiple attributes
    filtered = job_list.filter(executionId="id-1", approveAmount=100)
    assert len(filtered) == 2
    assert all(
        job._attributes.get("executionId") == "id-1"
        and job._attributes.get("approveAmount") == 100
        for job in filtered
    )


def test_filter_by_predicate_lv0(client):
    """Test filtering jobs with a custom predicate."""
    job1 = Job.from_dto(
        create_job_dto(
            executionId="id-1",
            status="Succeeded",
            resourceId="resource-1",
            approveAmount=100,
        ),
        client=client,
    )
    job2 = Job.from_dto(
        create_job_dto(
            executionId="id-2",
            status="Running",
            resourceId="resource-2",
            approveAmount=200,
        ),
        client=client,
    )
    job3 = Job.from_dto(
        create_job_dto(
            executionId="id-3",
            status="Succeeded",
            resourceId="resource-3",
            approveAmount=50,
        ),
        client=client,
    )

    job_list = JobList([job1, job2, job3])

    # Filter by predicate
    expensive_jobs = job_list.filter(
        predicate=lambda job: job._attributes.get("approveAmount", 0) > 100
    )
    assert len(expensive_jobs) == 1
    assert expensive_jobs[0]._attributes.get("approveAmount") == 200

    # Filter by nested attribute
    job1._attributes["tool"] = {"key": "tool1", "version": "1.0"}
    job2._attributes["tool"] = {"key": "tool2", "version": "2.0"}
    job3._attributes["tool"] = {"key": "tool1", "version": "1.5"}

    tool1_jobs = job_list.filter(
        predicate=lambda job: job._attributes.get("tool", {}).get("key") == "tool1"
    )
    assert len(tool1_jobs) == 2


def test_filter_combine_status_and_predicate_lv0(client):
    """Test combining status filter with predicate."""
    job1 = Job.from_dto(
        create_job_dto(
            executionId="id-1",
            status="Succeeded",
            resourceId="resource-1",
            approveAmount=100,
        ),
        client=client,
    )
    job2 = Job.from_dto(
        create_job_dto(
            executionId="id-2",
            status="Succeeded",
            resourceId="resource-2",
            approveAmount=200,
        ),
        client=client,
    )
    job3 = Job.from_dto(
        create_job_dto(
            executionId="id-3",
            status="Running",
            resourceId="resource-3",
            approveAmount=200,
        ),
        client=client,
    )

    job_list = JobList([job1, job2, job3])

    # Filter by status and predicate
    filtered = job_list.filter(
        status="Succeeded",
        predicate=lambda job: job._attributes.get("approveAmount", 0) > 100,
    )
    assert len(filtered) == 1
    assert filtered[0].status == "Succeeded"
    assert filtered[0]._attributes.get("approveAmount") == 200


def test_filter_combine_all_lv0(client):
    """Test combining status, attributes, and predicate."""
    job1 = Job.from_dto(
        create_job_dto(
            executionId="id-1",
            status="Succeeded",
            resourceId="resource-1",
            approveAmount=100,
        ),
        client=client,
    )
    job2 = Job.from_dto(
        create_job_dto(
            executionId="id-2",
            status="Succeeded",
            resourceId="resource-2",
            approveAmount=200,
        ),
        client=client,
    )
    job3 = Job.from_dto(
        create_job_dto(
            executionId="id-1",
            status="Running",
            resourceId="resource-3",
            approveAmount=100,
        ),
        client=client,
    )

    job_list = JobList([job1, job2, job3])

    # Combine all filter types
    filtered = job_list.filter(
        status="Succeeded",
        executionId="id-1",
        predicate=lambda job: job._attributes.get("approveAmount", 0) >= 100,
    )
    assert len(filtered) == 1
    assert filtered[0].id == "id-1"


def test_filter_empty_result_lv0(client):
    """Test filtering that returns empty JobList."""
    job1 = Job.from_dto(
        create_job_dto(executionId="id-1", status="Succeeded", resourceId="resource-1"),
        client=client,
    )

    job_list = JobList([job1])

    filtered = job_list.filter(status="Failed")
    assert len(filtered) == 0
    assert isinstance(filtered, JobList)


def test_filter_no_filters_lv0(client):
    """Test filtering with no filters returns original list."""
    job1 = Job.from_dto(
        create_job_dto(executionId="id-1", status="Succeeded", resourceId="resource-1"),
        client=client,
    )
    job2 = Job.from_dto(
        create_job_dto(executionId="id-2", status="Running", resourceId="resource-2"),
        client=client,
    )

    job_list = JobList([job1, job2])

    filtered = job_list.filter()
    assert len(filtered) == 2
    assert filtered.jobs == job_list.jobs


def test_filter_by_tool_key_lv0(client):
    """Test filtering jobs by tool_key."""
    job1 = Job.from_dto(
        create_job_dto(
            executionId="id-1",
            status="Succeeded",
            resourceId="resource-1",
            tool={"key": "deeporigin.docking", "version": "1.0.0"},
        ),
        client=client,
    )

    job2 = Job.from_dto(
        create_job_dto(
            executionId="id-2",
            status="Running",
            resourceId="resource-2",
            tool={"key": "deeporigin.abfe-end-to-end", "version": "1.0.0"},
        ),
        client=client,
    )

    job3 = Job.from_dto(
        create_job_dto(
            executionId="id-3",
            status="Succeeded",
            resourceId="resource-3",
            tool={"key": "deeporigin.docking", "version": "2.0.0"},
        ),
        client=client,
    )

    job_list = JobList([job1, job2, job3])

    # Filter by tool_key
    docking_jobs = job_list.filter(tool_key="deeporigin.docking")
    assert len(docking_jobs) == 2
    assert all(
        job._attributes.get("tool", {}).get("key") == "deeporigin.docking"
        for job in docking_jobs
    )

    abfe_jobs = job_list.filter(tool_key="deeporigin.abfe-end-to-end")
    assert len(abfe_jobs) == 1
    assert (
        abfe_jobs[0]._attributes.get("tool", {}).get("key")
        == "deeporigin.abfe-end-to-end"
    )


def test_filter_by_tool_version_lv0(client):
    """Test filtering jobs by tool_version."""
    job1 = Job.from_dto(
        create_job_dto(
            executionId="id-1",
            status="Succeeded",
            resourceId="resource-1",
            tool={"key": "deeporigin.docking", "version": "1.0.0"},
        ),
        client=client,
    )

    job2 = Job.from_dto(
        create_job_dto(
            executionId="id-2",
            status="Running",
            resourceId="resource-2",
            tool={"key": "deeporigin.docking", "version": "2.0.0"},
        ),
        client=client,
    )

    job3 = Job.from_dto(
        create_job_dto(
            executionId="id-3",
            status="Succeeded",
            resourceId="resource-3",
            tool={"key": "deeporigin.abfe-end-to-end", "version": "1.0.0"},
        ),
        client=client,
    )

    job_list = JobList([job1, job2, job3])

    # Filter by tool_version
    v1_jobs = job_list.filter(tool_version="1.0.0")
    assert len(v1_jobs) == 2
    assert all(
        job._attributes.get("tool", {}).get("version") == "1.0.0" for job in v1_jobs
    )

    v2_jobs = job_list.filter(tool_version="2.0.0")
    assert len(v2_jobs) == 1
    assert v2_jobs[0]._attributes.get("tool", {}).get("version") == "2.0.0"


def test_filter_by_tool_key_and_version_lv0(client):
    """Test filtering jobs by both tool_key and tool_version."""
    job1 = Job.from_dto(
        create_job_dto(
            executionId="id-1",
            status="Succeeded",
            resourceId="resource-1",
            tool={"key": "deeporigin.docking", "version": "1.0.0"},
        ),
        client=client,
    )

    job2 = Job.from_dto(
        create_job_dto(
            executionId="id-2",
            status="Running",
            resourceId="resource-2",
            tool={"key": "deeporigin.docking", "version": "2.0.0"},
        ),
        client=client,
    )

    job3 = Job.from_dto(
        create_job_dto(
            executionId="id-3",
            status="Succeeded",
            resourceId="resource-3",
            tool={"key": "deeporigin.abfe-end-to-end", "version": "1.0.0"},
        ),
        client=client,
    )

    job_list = JobList([job1, job2, job3])

    # Filter by both tool_key and tool_version
    filtered = job_list.filter(tool_key="deeporigin.docking", tool_version="1.0.0")
    assert len(filtered) == 1
    assert filtered[0].id == "id-1"
    assert filtered[0]._attributes.get("tool", {}).get("key") == "deeporigin.docking"
    assert filtered[0]._attributes.get("tool", {}).get("version") == "1.0.0"


def test_filter_combine_tool_with_status_lv0(client):
    """Test combining tool filters with status filter."""
    job1 = Job.from_dto(
        create_job_dto(
            executionId="id-1",
            status="Succeeded",
            resourceId="resource-1",
            tool={"key": "deeporigin.docking", "version": "1.0.0"},
        ),
        client=client,
    )

    job2 = Job.from_dto(
        create_job_dto(
            executionId="id-2",
            status="Running",
            resourceId="resource-2",
            tool={"key": "deeporigin.docking", "version": "1.0.0"},
        ),
        client=client,
    )

    job3 = Job.from_dto(
        create_job_dto(
            executionId="id-3",
            status="Succeeded",
            resourceId="resource-3",
            tool={"key": "deeporigin.abfe-end-to-end", "version": "1.0.0"},
        ),
        client=client,
    )

    job_list = JobList([job1, job2, job3])

    # Combine status and tool_key
    filtered = job_list.filter(status="Succeeded", tool_key="deeporigin.docking")
    assert len(filtered) == 1
    assert filtered[0].status == "Succeeded"
    assert filtered[0]._attributes.get("tool", {}).get("key") == "deeporigin.docking"


def test_filter_tool_key_with_missing_tool_lv0(client):
    """Test filtering by tool_key when some jobs don't have tool attribute."""
    job1 = Job.from_dto(
        create_job_dto(
            executionId="id-1",
            status="Succeeded",
            resourceId="resource-1",
            tool={"key": "deeporigin.docking", "version": "1.0.0"},
        ),
        client=client,
    )

    # Create DTOs without tool attribute
    dto2 = create_job_dto(executionId="id-2", status="Running", resourceId="resource-2")
    dto2.pop("tool", None)
    job2 = Job.from_dto(dto2, client=client)

    dto3 = create_job_dto(
        executionId="id-3", status="Succeeded", resourceId="resource-3"
    )
    dto3.pop("tool", None)
    job3 = Job.from_dto(dto3, client=client)

    job_list = JobList([job1, job2, job3])

    # Filter by tool_key should only return jobs with matching tool.key
    filtered = job_list.filter(tool_key="deeporigin.docking")
    assert len(filtered) == 1
    assert filtered[0].id == "id-1"


def test_job_list_confirm_lv0(client, test_server):
    """Test confirm calls confirm on all jobs."""
    if test_server is None:
        pytest.skip("Mock server not available")

    # Create executions in the mock server
    execution1 = {
        "executionId": "confirm-job-1",
        "status": "Quoted",
        "createdAt": "2025-01-01T00:00:00.000Z",
        "updatedAt": "2025-01-01T01:00:00.000Z",
        "resourceId": "resource-1",
        "orgKey": "deeporigin",
        "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
    }
    execution2 = {
        "executionId": "confirm-job-2",
        "status": "Quoted",
        "createdAt": "2025-01-01T00:00:00.000Z",
        "updatedAt": "2025-01-01T01:00:00.000Z",
        "resourceId": "resource-2",
        "orgKey": "deeporigin",
        "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
    }

    test_server._executions["confirm-job-1"] = execution1
    test_server._executions["confirm-job-2"] = execution2

    job1 = Job.from_id("confirm-job-1", client=client)
    job2 = Job.from_id("confirm-job-2", client=client)
    job_list = JobList([job1, job2])

    job_list.confirm()

    # Verify jobs were confirmed (status changed to Running)
    job1.sync()
    job2.sync()
    assert job1.status == "Running"
    assert job2.status == "Running"


def test_job_list_cancel(client, test_server):
    """Test cancel calls cancel on all jobs."""
    if test_server is None:
        pytest.skip("Mock server not available")

    # Create executions in the mock server
    execution1 = {
        "executionId": "cancel-job-1",
        "status": "Running",
        "createdAt": "2025-01-01T00:00:00.000Z",
        "updatedAt": "2025-01-01T01:00:00.000Z",
        "resourceId": "resource-1",
        "orgKey": "deeporigin",
        "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
    }
    execution2 = {
        "executionId": "cancel-job-2",
        "status": "Running",
        "createdAt": "2025-01-01T00:00:00.000Z",
        "updatedAt": "2025-01-01T01:00:00.000Z",
        "resourceId": "resource-2",
        "orgKey": "deeporigin",
        "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
    }

    test_server._executions["cancel-job-1"] = execution1
    test_server._executions["cancel-job-2"] = execution2

    job1 = Job.from_id("cancel-job-1", client=client)
    job2 = Job.from_id("cancel-job-2", client=client)
    job_list = JobList([job1, job2])

    job_list.cancel()

    # Verify jobs were cancelled (status changed to Cancelled)
    job1.sync()
    job2.sync()
    assert job1.status == "Cancelled"
    assert job2.status == "Cancelled"


def test_job_list_show(client):
    """Test show displays the job list view."""
    # Create real Job objects with proper attributes
    job1 = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Succeeded",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
        },
        client=client,
    )
    job2 = Job.from_dto(
        {
            "executionId": "id-2",
            "status": "Running",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": "resource-2",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
        },
        client=client,
    )

    job_list = JobList([job1, job2])
    # Should not raise an error
    job_list.show()


def test_job_list_show_empty():
    """Test show works with empty job list."""
    job_list = JobList([])
    # Should not raise an error
    job_list.show()


def test_job_list_watch_all_terminal(client):
    """Test watch when all jobs are in terminal states."""
    # Create jobs all in terminal states
    job1 = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Succeeded",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
        },
        client=client,
    )
    job2 = Job.from_dto(
        {
            "executionId": "id-2",
            "status": "Failed",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": "resource-2",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
        },
        client=client,
    )

    job_list = JobList([job1, job2])
    job_list.watch()

    # Should display a message and show once, but not start a task
    assert job_list._task is None


def test_job_list_stop_watching():
    """Test stop_watching cancels the monitoring task."""
    job_list = JobList([])
    # Should not raise an error
    job_list.stop_watching()
    assert job_list._task is None


def test_job_list_stop_watching_no_task():
    """Test stop_watching handles case when no task exists."""
    job_list = JobList([])
    # Should not raise an error
    job_list.stop_watching()
    assert job_list._task is None


def test_from_ids(client, test_server):
    """Test creating JobList from IDs."""
    if test_server is None:
        pytest.skip("Mock server not available")

    # Create executions in the mock server
    execution1 = {
        "executionId": "from-ids-1",
        "status": "Succeeded",
        "createdAt": "2025-01-01T00:00:00.000Z",
        "updatedAt": "2025-01-01T01:00:00.000Z",
        "resourceId": "resource-1",
        "orgKey": "deeporigin",
        "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
    }
    execution2 = {
        "executionId": "from-ids-2",
        "status": "Running",
        "createdAt": "2025-01-01T00:00:00.000Z",
        "updatedAt": "2025-01-01T01:00:00.000Z",
        "resourceId": "resource-2",
        "orgKey": "deeporigin",
        "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
    }
    execution3 = {
        "executionId": "from-ids-3",
        "status": "Succeeded",
        "createdAt": "2025-01-01T00:00:00.000Z",
        "updatedAt": "2025-01-01T01:00:00.000Z",
        "resourceId": "resource-3",
        "orgKey": "deeporigin",
        "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
    }

    test_server._executions["from-ids-1"] = execution1
    test_server._executions["from-ids-2"] = execution2
    test_server._executions["from-ids-3"] = execution3

    ids = ["from-ids-1", "from-ids-2", "from-ids-3"]
    job_list = JobList.from_ids(ids, client=client)

    assert len(job_list) == 3
    assert job_list[0].id == "from-ids-1"
    assert job_list[1].id == "from-ids-2"
    assert job_list[2].id == "from-ids-3"


def test_from_dtos(client):
    """Test creating JobList from DTOs."""
    dtos = [
        {
            "executionId": "id-1",
            "status": "Succeeded",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
        },
        {
            "executionId": "id-2",
            "status": "Running",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": "resource-2",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
        },
    ]

    job_list = JobList.from_dtos(dtos, client=client)

    assert len(job_list) == 2
    assert job_list[0].id == "id-1"
    assert job_list[1].id == "id-2"


def test_list(client, test_server):
    """Test creating JobList from API list call."""
    if test_server is None:
        pytest.skip("Mock server not available")

    # Create executions in the mock server
    execution1 = {
        "executionId": "list-job-1",
        "status": "Running",
        "createdAt": "2025-01-01T00:00:00.000Z",
        "updatedAt": "2025-01-01T01:00:00.000Z",
        "resourceId": "resource-1",
        "orgKey": "deeporigin",
        "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
    }
    execution2 = {
        "executionId": "list-job-2",
        "status": "Succeeded",
        "createdAt": "2025-01-01T00:00:00.000Z",
        "updatedAt": "2025-01-01T01:00:00.000Z",
        "resourceId": "resource-2",
        "orgKey": "deeporigin",
        "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
    }

    test_server._executions["list-job-1"] = execution1
    test_server._executions["list-job-2"] = execution2

    result = JobList.list(page=0, page_size=10, client=client)

    assert len(result) >= 2  # May have other executions from fixtures
    assert any(job.id == "list-job-1" for job in result)
    assert any(job.id == "list-job-2" for job in result)


def test_list_pagination(client, test_server):
    """Test that JobList.list handles pagination correctly."""
    if test_server is None:
        pytest.skip("Mock server not available")

    # Create 250 executions in the mock server
    for i in range(250):
        execution = {
            "executionId": f"pagination-job-{i}",
            "status": "Running",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": f"resource-{i}",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
        }
        test_server._executions[f"pagination-job-{i}"] = execution

    result = JobList.list(page_size=100, client=client)

    # Should have fetched all pages (250 items total)
    assert len(result) >= 250
    # Verify we got the expected jobs
    assert any(job.id == "pagination-job-0" for job in result)
    assert any(job.id == "pagination-job-249" for job in result)


def test_list_pagination_stops_when_count_less_than_page_size(client, test_server):
    """Test that pagination stops when count <= page_size."""
    if test_server is None:
        pytest.skip("Mock server not available")

    # Create 50 executions in the mock server
    for i in range(50):
        execution = {
            "executionId": f"small-pagination-job-{i}",
            "status": "Running",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": f"resource-{i}",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
        }
        test_server._executions[f"small-pagination-job-{i}"] = execution

    result = JobList.list(page_size=100, client=client)

    # Should have fetched all items (50 items total, fits in one page)
    assert len(result) >= 50
    assert any(job.id == "small-pagination-job-0" for job in result)
    assert any(job.id == "small-pagination-job-49" for job in result)


def test_to_dataframe(client):
    """Test converting JobList to DataFrame."""
    # Create Job objects with _attributes
    job1 = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Succeeded",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "completedAt": "2025-01-01T02:00:00.000Z",
            "startedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": "tool1", "version": "1.0"},
        },
        client=client,
    )

    job2 = Job.from_dto(
        {
            "executionId": "id-2",
            "status": "Running",
            "createdAt": "2025-01-02T00:00:00.000Z",
            "updatedAt": "2025-01-02T01:00:00.000Z",
            "completedAt": None,
            "startedAt": "2025-01-02T01:00:00.000Z",
            "resourceId": "resource-2",
            "orgKey": "deeporigin",
            "tool": {"key": "tool2", "version": "2.0"},
        },
        client=client,
    )

    job_list = JobList([job1, job2])
    df = job_list.to_dataframe()

    # Check DataFrame structure
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    expected_columns = [
        "id",
        "created_at",
        "resource_id",
        "completed_at",
        "started_at",
        "status",
        "tool_key",
        "tool_version",
        "user_name",
        "run_duration_minutes",
    ]
    for col in expected_columns:
        assert col in df.columns

    # Check data
    assert df.iloc[0]["status"] == "Succeeded"
    assert df.iloc[0]["id"] == "id-1"
    assert df.iloc[0]["tool_key"] == "tool1"
    assert df.iloc[0]["tool_version"] == "1.0"
    assert df.iloc[1]["status"] == "Running"
    assert df.iloc[1]["id"] == "id-2"
    assert df.iloc[1]["tool_key"] == "tool2"
    assert df.iloc[1]["tool_version"] == "2.0"

    # Check datetime columns are converted
    assert pd.api.types.is_datetime64_any_dtype(df["created_at"])
    assert pd.api.types.is_datetime64_any_dtype(df["started_at"])


def test_to_dataframe_with_missing_attributes(client):
    """Test to_dataframe handles jobs with None _attributes."""
    job1 = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Succeeded",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
        },
        client=client,
    )

    job2 = Job.from_dto(
        {
            "executionId": "id-2",
            "status": "Running",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": "resource-2",
            "orgKey": "deeporigin",
        },
        client=client,
    )

    job_list = JobList([job1, job2])
    df = job_list.to_dataframe()

    assert len(df) == 2
    assert df.iloc[0]["status"] == "Succeeded"
    assert df.iloc[0]["id"] == "id-1"
    # job2 may have missing fields
    assert df.iloc[1]["id"] == "id-2"


def test_to_dataframe_with_missing_keys(client):
    """Test to_dataframe handles missing keys in _attributes."""
    job = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Succeeded",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
        },
        client=client,
    )

    job_list = JobList([job])
    df = job_list.to_dataframe()

    assert len(df) == 1
    assert df.iloc[0]["status"] == "Succeeded"
    assert df.iloc[0]["id"] == "id-1"
    # Missing keys should be None/NaT (NaT for datetime columns)
    assert pd.isna(df.iloc[0]["completed_at"])
    assert df.iloc[0]["tool_key"] == "deeporigin.docking"
    assert df.iloc[0]["tool_version"] == "1.0.0"


def test_filter_by_multiple_statuses(client):
    """Test filtering jobs by multiple statuses."""
    job1 = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Succeeded",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
        },
        client=client,
    )

    job2 = Job.from_dto(
        {
            "executionId": "id-2",
            "status": "Running",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": "resource-2",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
        },
        client=client,
    )

    job3 = Job.from_dto(
        {
            "executionId": "id-3",
            "status": "Failed",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": "resource-3",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
        },
        client=client,
    )

    job_list = JobList([job1, job2, job3])

    # Filter by list of statuses
    filtered = job_list.filter(status=["Succeeded", "Running"])
    assert len(filtered) == 2
    assert filtered[0].status == "Succeeded"
    assert filtered[1].status == "Running"

    # Filter by set of statuses
    filtered = job_list.filter(status={"Succeeded", "Failed"})
    assert len(filtered) == 2


def test_filter_require_metadata(client):
    """Test filtering jobs that require metadata."""
    job1 = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Succeeded",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
            "metadata": {"key": "value"},
        },
        client=client,
    )

    job2 = Job.from_dto(
        {
            "executionId": "id-2",
            "status": "Running",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": "resource-2",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
            "metadata": None,
        },
        client=client,
    )

    job3 = Job.from_dto(
        {
            "executionId": "id-3",
            "status": "Succeeded",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": "resource-3",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
        },
        client=client,
    )

    job_list = JobList([job1, job2, job3])

    filtered = job_list.filter(require_metadata=True)
    assert len(filtered) == 1
    assert filtered[0].id == "id-1"


def test_to_dataframe_with_optional_columns(client):
    """Test to_dataframe with include_metadata, include_inputs, include_outputs."""
    job = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Succeeded",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
            "metadata": {"key": "value"},
            "userInputs": {"smiles_list": ["CCO", "CCC"]},
            "userOutputs": {"result": "data"},
        },
        client=client,
    )

    job_list = JobList([job])

    # Test with all optional columns
    df = job_list.to_dataframe(
        include_metadata=True, include_inputs=True, include_outputs=True
    )
    assert "metadata" in df.columns
    assert "user_inputs" in df.columns
    assert "user_outputs" in df.columns
    assert df.iloc[0]["metadata"] == {"key": "value"}
    assert df.iloc[0]["user_inputs"] == {"smiles_list": ["CCO", "CCC"]}
    assert df.iloc[0]["user_outputs"] == {"result": "data"}

    # Test without optional columns
    df = job_list.to_dataframe()
    assert "metadata" not in df.columns
    assert "user_inputs" not in df.columns
    assert "user_outputs" not in df.columns


def test_to_dataframe_run_duration(client):
    """Test to_dataframe calculates run_duration_minutes correctly."""
    job = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Succeeded",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "startedAt": "2025-01-01T00:00:00.000Z",
            "completedAt": "2025-01-01T01:30:00.000Z",  # 90 minutes
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
        },
        client=client,
    )

    job_list = JobList([job])
    df = job_list.to_dataframe()

    assert df.iloc[0]["run_duration_minutes"] == 90

    # Test with missing dates
    job2 = Job.from_dto(
        {
            "executionId": "id-2",
            "status": "Running",
            "createdAt": "2025-01-01T00:00:00.000Z",
            "updatedAt": "2025-01-01T01:00:00.000Z",
            "startedAt": "2025-01-01T00:00:00.000Z",
            "resourceId": "resource-2",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
        },
        client=client,
    )

    job_list2 = JobList([job2])
    df2 = job_list2.to_dataframe()
    assert df2.iloc[0]["run_duration_minutes"] is None


def test_job_list_render_view_with_docking_tool(client):
    """Test that JobList._render_view uses tool-specific viz function for bulk-docking."""
    from deeporigin.drug_discovery.constants import tool_mapper

    # Create jobs with docking tool
    job1 = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Running",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "startedAt": "2024-01-01T00:00:00.000Z",
            "completedAt": "2024-01-01T00:10:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": tool_mapper["Docking"], "version": "1.0.0"},
            "userInputs": {"smiles_list": ["CCO", "CCN"]},
            "progressReport": "ligand docked ligand docked",
        },
        client=client,
    )

    job2 = Job.from_dto(
        {
            "executionId": "id-2",
            "status": "Running",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "startedAt": "2024-01-01T00:00:00.000Z",
            "completedAt": "2024-01-01T00:05:00.000Z",
            "resourceId": "resource-2",
            "orgKey": "deeporigin",
            "tool": {"key": tool_mapper["Docking"], "version": "1.0.0"},
            "userInputs": {"smiles_list": ["CCC"]},
            "progressReport": "ligand docked ligand failed",
        },
        client=client,
    )

    job_list = JobList([job1, job2])
    html = job_list._render_view()

    # Should use docking-specific visualization (check for speed text)
    assert "dockings/minute" in html
    assert isinstance(html, str)


def test_job_list_render_view_card_title_with_same_tool(client):
    """Test that JobList._render_view uses tool-specific card title when all jobs have same tool key."""
    from deeporigin.drug_discovery.constants import tool_mapper

    # Create jobs with docking tool and metadata
    job1 = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Running",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": tool_mapper["Docking"], "version": "1.0.0"},
            "userInputs": {"smiles_list": ["CCO", "CCN"]},
            "metadata": {"protein_file": "test_protein.pdb"},
        },
        client=client,
    )

    job2 = Job.from_dto(
        {
            "executionId": "id-2",
            "status": "Running",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "resourceId": "resource-2",
            "orgKey": "deeporigin",
            "tool": {"key": tool_mapper["Docking"], "version": "1.0.0"},
            "userInputs": {"smiles_list": ["CCC"]},
            "metadata": {"protein_file": "test_protein.pdb"},
        },
        client=client,
    )

    job_list = JobList([job1, job2])
    html = job_list._render_view()

    # Should use tool-specific card title (docking name function)
    # Should aggregate unique SMILES across all jobs (CCO, CCN, CCC = 3 unique ligands)
    assert "Docking" in html
    assert "test_protein.pdb" in html
    assert "3 ligands" in html  # Should show 3 unique ligands, not 2+1
    assert "2 jobs" in html
    assert (
        "Job List" not in html or html.count("Job List") == 0
    )  # Should not use generic title
    assert isinstance(html, str)


def test_name_func_docking_with_job_list(client):
    """Test that _name_func_docking aggregates unique SMILES across all jobs in a JobList."""
    from deeporigin.platform import job_viz_functions

    # Create jobs with overlapping SMILES
    job1 = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Succeeded",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
            "userInputs": {"smiles_list": ["CCO", "CCN"]},
            "metadata": {"protein_file": "test_protein.pdb"},
        },
        client=client,
    )

    job2 = Job.from_dto(
        {
            "executionId": "id-2",
            "status": "Succeeded",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "resourceId": "resource-2",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
            "userInputs": {"smiles_list": ["CCC", "CCO"]},  # CCO overlaps with job1
            "metadata": {"protein_file": "test_protein.pdb"},
        },
        client=client,
    )

    job_list = JobList([job1, job2])
    name = job_viz_functions._name_func_docking(job_list)

    # Should aggregate unique SMILES: CCO, CCN, CCC = 3 unique ligands
    assert "Docking" in name
    assert "test_protein.pdb" in name
    assert "3 ligands" in name
    assert isinstance(name, str)


def test_name_func_docking_with_single_job(client):
    """Test that _name_func_docking works with a single Job."""
    from deeporigin.platform import job_viz_functions

    job = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Succeeded",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
            "userInputs": {"smiles_list": ["CCO", "CCN", "CCC"]},
            "metadata": {"protein_file": "test_protein.pdb"},
        },
        client=client,
    )

    name = job_viz_functions._name_func_docking(job)

    assert "Docking" in name
    assert "test_protein.pdb" in name
    assert "3 ligands" in name
    assert isinstance(name, str)


def test_job_list_render_view_card_title_with_mixed_tools(client):
    """Test that JobList._render_view uses generic card title when jobs have different tool keys."""
    from deeporigin.drug_discovery.constants import tool_mapper

    job1 = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Running",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": tool_mapper["Docking"], "version": "1.0.0"},
        },
        client=client,
    )

    job2 = Job.from_dto(
        {
            "executionId": "id-2",
            "status": "Succeeded",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "resourceId": "resource-2",
            "orgKey": "deeporigin",
            "tool": {"key": tool_mapper["ABFE"], "version": "1.0.0"},
        },
        client=client,
    )

    job_list = JobList([job1, job2])
    html = job_list._render_view()

    # Should use generic card title when tools differ
    assert "Job List" in html
    assert "2 jobs" in html
    assert isinstance(html, str)


def test_job_list_render_view_with_mixed_tools(client):
    """Test that JobList._render_view uses generic status HTML when jobs have different tool keys."""
    from deeporigin.drug_discovery.constants import tool_mapper

    job1 = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Running",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": tool_mapper["Docking"], "version": "1.0.0"},
        },
        client=client,
    )

    job2 = Job.from_dto(
        {
            "executionId": "id-2",
            "status": "Succeeded",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "resourceId": "resource-2",
            "orgKey": "deeporigin",
            "tool": {"key": tool_mapper["ABFE"], "version": "1.0.0"},
        },
        client=client,
    )

    job_list = JobList([job1, job2])
    html = job_list._render_view()

    # Should use generic status HTML
    assert "job(s) in this list" in html
    assert "Status breakdown" in html
    assert isinstance(html, str)


def test_viz_func_docking_with_job_list(client):
    """Test that _viz_func_docking works with JobList."""
    from deeporigin.platform import job_viz_functions

    job1 = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Succeeded",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "startedAt": "2024-01-01T00:00:00.000Z",
            "completedAt": "2024-01-01T00:10:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
            "userInputs": {"smiles_list": ["CCO", "CCN"]},
            "progressReport": "ligand docked ligand docked",
        },
        client=client,
    )

    job2 = Job.from_dto(
        {
            "executionId": "id-2",
            "status": "Succeeded",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "startedAt": "2024-01-01T00:00:00.000Z",
            "completedAt": "2024-01-01T00:05:00.000Z",
            "resourceId": "resource-2",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
            "userInputs": {"smiles_list": ["CCC"]},
            "progressReport": "ligand docked ligand failed",
        },
        client=client,
    )

    job_list = JobList([job1, job2])
    html = job_viz_functions._viz_func_docking(job_list)

    # Should render progress bar with summed values
    # Total ligands should be 3 (2 + 1)
    # Total docked should be 3 (2 + 1)
    # Total failed should be 1 (0 + 1)
    assert isinstance(html, str)


def test_viz_func_quoted_with_single_job(client):
    """Test that _viz_func_quoted works with a single Job."""
    from deeporigin.platform import job_viz_functions

    job = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Quoted",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
            "quotationResult": {"successfulQuotations": [{"priceTotal": 100.50}]},
        },
        client=client,
    )

    html = job_viz_functions._viz_func_quoted(job)

    assert "Job Quoted" in html
    assert "$101" in html or "$100" in html  # rounded cost
    assert "confirm()" in html
    assert isinstance(html, str)


def test_viz_func_quoted_with_job_list(client):
    """Test that _viz_func_quoted works with JobList and sums costs."""
    from deeporigin.platform import job_viz_functions

    job1 = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Quoted",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
            "quotationResult": {"successfulQuotations": [{"priceTotal": 50.25}]},
        },
        client=client,
    )

    job2 = Job.from_dto(
        {
            "executionId": "id-2",
            "status": "Quoted",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "resourceId": "resource-2",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
            "quotationResult": {"successfulQuotations": [{"priceTotal": 75.75}]},
        },
        client=client,
    )

    job_list = JobList([job1, job2])
    html = job_viz_functions._viz_func_quoted(job_list)

    assert "Jobs Quoted" in html
    assert "2" in html  # number of jobs
    assert "$126" in html or "$125" in html  # rounded total (50.25 + 75.75 = 126)
    assert "confirm()" in html
    assert isinstance(html, str)


def test_job_list_render_view_with_all_quoted(client):
    """Test that JobList._render_view uses quoted visualization when all jobs are Quoted."""
    job1 = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Quoted",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
            "quotationResult": {"successfulQuotations": [{"priceTotal": 100.0}]},
        },
        client=client,
    )

    job2 = Job.from_dto(
        {
            "executionId": "id-2",
            "status": "Quoted",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "resourceId": "resource-2",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
            "quotationResult": {"successfulQuotations": [{"priceTotal": 200.0}]},
        },
        client=client,
    )

    job_list = JobList([job1, job2])
    html = job_list._render_view()

    # Should use quoted-specific visualization
    assert "Jobs Quoted" in html
    assert "2" in html  # number of jobs
    assert "$300" in html  # total cost (100 + 200)
    assert isinstance(html, str)


def test_job_list_render_view_with_mixed_status(client):
    """Test that JobList._render_view uses generic HTML when not all jobs are Quoted."""
    job1 = Job.from_dto(
        {
            "executionId": "id-1",
            "status": "Quoted",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "resourceId": "resource-1",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
            "quotationResult": {"successfulQuotations": [{"priceTotal": 100.0}]},
        },
        client=client,
    )

    job2 = Job.from_dto(
        {
            "executionId": "id-2",
            "status": "Running",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T01:00:00.000Z",
            "resourceId": "resource-2",
            "orgKey": "deeporigin",
            "tool": {"key": "deeporigin.docking", "version": "1.0.0"},
        },
        client=client,
    )

    job_list = JobList([job1, job2])
    html = job_list._render_view()

    # Should use generic status HTML, not quoted visualization
    assert "Jobs Quoted" not in html
    assert "job(s) in this list" in html
    assert "Status breakdown" in html
    assert isinstance(html, str)
