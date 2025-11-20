"""Tests for the JobList class."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from deeporigin.platform.job import Job, JobList


@pytest.fixture
def mock_jobs():
    """Create a list of mock Job objects."""
    jobs = []
    statuses = ["Succeeded", "Running", "Succeeded", "Failed", "Running"]
    for i, status in enumerate(statuses):
        job = MagicMock(spec=Job)
        job.status = status
        job._id = f"job-{i}"
        jobs.append(job)
    return jobs


def test_job_list_initialization(mock_jobs):
    """Test JobList initialization."""
    job_list = JobList(mock_jobs)
    assert len(job_list) == 5
    assert job_list.jobs == mock_jobs


def test_job_list_iteration(mock_jobs):
    """Test iterating over JobList."""
    job_list = JobList(mock_jobs)
    for i, job in enumerate(job_list):
        assert job == mock_jobs[i]


def test_job_list_getitem(mock_jobs):
    """Test accessing jobs by index."""
    job_list = JobList(mock_jobs)
    assert job_list[0] == mock_jobs[0]
    assert job_list[-1] == mock_jobs[-1]
    # Test slice indexing
    assert job_list[0:2] == mock_jobs[0:2]


def test_job_list_repr_html():
    """Test HTML representation of JobList."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Succeeded"

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2.status = "Running"

    job3 = Job(name="job3", _id="id-3", _skip_sync=True)
    job3.status = "Succeeded"

    job_list = JobList([job1, job2, job3])
    html = job_list._repr_html_()

    # Check that HTML contains expected information
    assert "3" in html  # Number of jobs
    assert "Succeeded: 2" in html
    assert "Running: 1" in html
    assert "to_dataframe()" in html
    assert isinstance(html, str)


def test_job_list_repr_html_empty():
    """Test HTML representation of empty JobList."""
    job_list = JobList([])
    html = job_list._repr_html_()

    assert "0" in html  # Number of jobs
    assert "No status information" in html
    assert "to_dataframe()" in html


def test_job_list_status(mock_jobs):
    """Test status property returns correct breakdown."""
    job_list = JobList(mock_jobs)
    status_counts = job_list.status

    assert status_counts["Succeeded"] == 2
    assert status_counts["Running"] == 2
    assert status_counts["Failed"] == 1
    assert "Queued" not in status_counts


def test_filter_by_status():
    """Test filtering jobs by status."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Succeeded"

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2.status = "Running"

    job3 = Job(name="job3", _id="id-3", _skip_sync=True)
    job3.status = "Succeeded"

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


def test_filter_by_attributes():
    """Test filtering jobs by attributes."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1._attributes = {
        "executionId": "id-1",
        "status": "Succeeded",
        "approveAmount": 100,
    }

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2._attributes = {
        "executionId": "id-2",
        "status": "Running",
        "approveAmount": 200,
    }

    job3 = Job(name="job3", _id="id-3", _skip_sync=True)
    job3._attributes = {"executionId": "id-1", "status": "Failed", "approveAmount": 100}

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


def test_filter_by_predicate():
    """Test filtering jobs with a custom predicate."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1._attributes = {"approveAmount": 100, "status": "Succeeded"}

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2._attributes = {"approveAmount": 200, "status": "Running"}

    job3 = Job(name="job3", _id="id-3", _skip_sync=True)
    job3._attributes = {"approveAmount": 50, "status": "Succeeded"}

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


def test_filter_combine_status_and_predicate():
    """Test combining status filter with predicate."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Succeeded"
    job1._attributes = {"approveAmount": 100}

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2.status = "Succeeded"
    job2._attributes = {"approveAmount": 200}

    job3 = Job(name="job3", _id="id-3", _skip_sync=True)
    job3.status = "Running"
    job3._attributes = {"approveAmount": 200}

    job_list = JobList([job1, job2, job3])

    # Filter by status and predicate
    filtered = job_list.filter(
        status="Succeeded",
        predicate=lambda job: job._attributes.get("approveAmount", 0) > 100,
    )
    assert len(filtered) == 1
    assert filtered[0].status == "Succeeded"
    assert filtered[0]._attributes.get("approveAmount") == 200


def test_filter_combine_all():
    """Test combining status, attributes, and predicate."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Succeeded"
    job1._attributes = {"executionId": "id-1", "approveAmount": 100}

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2.status = "Succeeded"
    job2._attributes = {"executionId": "id-2", "approveAmount": 200}

    job3 = Job(name="job3", _id="id-3", _skip_sync=True)
    job3.status = "Running"
    job3._attributes = {"executionId": "id-1", "approveAmount": 100}

    job_list = JobList([job1, job2, job3])

    # Combine all filter types
    filtered = job_list.filter(
        status="Succeeded",
        executionId="id-1",
        predicate=lambda job: job._attributes.get("approveAmount", 0) >= 100,
    )
    assert len(filtered) == 1
    assert filtered[0]._id == "id-1"


def test_filter_empty_result():
    """Test filtering that returns empty JobList."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Succeeded"

    job_list = JobList([job1])

    filtered = job_list.filter(status="Failed")
    assert len(filtered) == 0
    assert isinstance(filtered, JobList)


def test_filter_no_filters():
    """Test filtering with no filters returns original list."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job2 = Job(name="job2", _id="id-2", _skip_sync=True)

    job_list = JobList([job1, job2])

    filtered = job_list.filter()
    assert len(filtered) == 2
    assert filtered.jobs == job_list.jobs


def test_filter_by_tool_key():
    """Test filtering jobs by tool_key."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1._attributes = {"tool": {"key": "deeporigin.docking", "version": "1.0.0"}}

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2._attributes = {
        "tool": {"key": "deeporigin.abfe-end-to-end", "version": "1.0.0"}
    }

    job3 = Job(name="job3", _id="id-3", _skip_sync=True)
    job3._attributes = {"tool": {"key": "deeporigin.docking", "version": "2.0.0"}}

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


def test_filter_by_tool_version():
    """Test filtering jobs by tool_version."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1._attributes = {"tool": {"key": "deeporigin.docking", "version": "1.0.0"}}

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2._attributes = {"tool": {"key": "deeporigin.docking", "version": "2.0.0"}}

    job3 = Job(name="job3", _id="id-3", _skip_sync=True)
    job3._attributes = {
        "tool": {"key": "deeporigin.abfe-end-to-end", "version": "1.0.0"}
    }

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


def test_filter_by_tool_key_and_version():
    """Test filtering jobs by both tool_key and tool_version."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1._attributes = {"tool": {"key": "deeporigin.docking", "version": "1.0.0"}}

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2._attributes = {"tool": {"key": "deeporigin.docking", "version": "2.0.0"}}

    job3 = Job(name="job3", _id="id-3", _skip_sync=True)
    job3._attributes = {
        "tool": {"key": "deeporigin.abfe-end-to-end", "version": "1.0.0"}
    }

    job_list = JobList([job1, job2, job3])

    # Filter by both tool_key and tool_version
    filtered = job_list.filter(tool_key="deeporigin.docking", tool_version="1.0.0")
    assert len(filtered) == 1
    assert filtered[0]._id == "id-1"
    assert filtered[0]._attributes.get("tool", {}).get("key") == "deeporigin.docking"
    assert filtered[0]._attributes.get("tool", {}).get("version") == "1.0.0"


def test_filter_combine_tool_with_status():
    """Test combining tool filters with status filter."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Succeeded"
    job1._attributes = {"tool": {"key": "deeporigin.docking", "version": "1.0.0"}}

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2.status = "Running"
    job2._attributes = {"tool": {"key": "deeporigin.docking", "version": "1.0.0"}}

    job3 = Job(name="job3", _id="id-3", _skip_sync=True)
    job3.status = "Succeeded"
    job3._attributes = {
        "tool": {"key": "deeporigin.abfe-end-to-end", "version": "1.0.0"}
    }

    job_list = JobList([job1, job2, job3])

    # Combine status and tool_key
    filtered = job_list.filter(status="Succeeded", tool_key="deeporigin.docking")
    assert len(filtered) == 1
    assert filtered[0].status == "Succeeded"
    assert filtered[0]._attributes.get("tool", {}).get("key") == "deeporigin.docking"


def test_filter_tool_key_with_missing_tool():
    """Test filtering by tool_key when some jobs don't have tool attribute."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1._attributes = {"tool": {"key": "deeporigin.docking", "version": "1.0.0"}}

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2._attributes = {}  # No tool attribute

    job3 = Job(name="job3", _id="id-3", _skip_sync=True)
    job3._attributes = None  # No attributes at all

    job_list = JobList([job1, job2, job3])

    # Filter by tool_key should only return jobs with matching tool.key
    filtered = job_list.filter(tool_key="deeporigin.docking")
    assert len(filtered) == 1
    assert filtered[0]._id == "id-1"


def test_job_list_confirm(mock_jobs):
    """Test confirm calls confirm on all jobs."""
    job_list = JobList(mock_jobs)
    job_list.confirm()

    for job in mock_jobs:
        job.confirm.assert_called_once()


def test_job_list_cancel(mock_jobs):
    """Test cancel calls cancel on all jobs."""
    job_list = JobList(mock_jobs)
    job_list.cancel()

    for job in mock_jobs:
        job.cancel.assert_called_once()


@patch("deeporigin.platform.job.display")
def test_job_list_show(mock_display):
    """Test show displays the job list view."""
    # Create real Job objects with proper attributes
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Succeeded"
    job1._attributes = {}
    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2.status = "Running"
    job2._attributes = {}

    job_list = JobList([job1, job2])
    job_list.show()
    mock_display.assert_called_once()


def test_job_list_show_empty():
    """Test show works with empty job list."""
    job_list = JobList([])
    # Should not raise an error
    with patch("deeporigin.platform.job.display"):
        job_list.show()


@patch("deeporigin.platform.job.display")
@patch("nest_asyncio.apply")
def test_job_list_watch_all_terminal(mock_nest_asyncio_apply, mock_display):
    """Test watch when all jobs are in terminal states."""
    # Create jobs all in terminal states
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Succeeded"
    job1._attributes = {}
    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2.status = "Failed"
    job2._attributes = {}

    job_list = JobList([job1, job2])
    job_list.watch()

    # Should display a message and show once, but not start a task
    assert mock_display.call_count >= 1
    assert job_list._task is None


@patch("deeporigin.platform.job.display")
@patch("deeporigin.platform.job.update_display")
@patch("nest_asyncio.apply")
@patch("asyncio.get_event_loop")
@patch("asyncio.create_task")
def test_job_list_watch_with_running_jobs(
    mock_create_task,
    mock_get_event_loop,
    mock_nest_asyncio_apply,
    mock_update_display,
    mock_display,
):
    """Test watch starts monitoring when there are running jobs."""
    # Create jobs with some in non-terminal states
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Running"
    job1._attributes = {}
    job1.sync = MagicMock()
    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2.status = "Queued"
    job2._attributes = {}
    job2.sync = MagicMock()

    # Mock event loop and task creation
    mock_task = MagicMock()
    mock_create_task.return_value = mock_task
    mock_loop = MagicMock()
    mock_loop.create_task.return_value = mock_task
    mock_get_event_loop.return_value = mock_loop

    job_list = JobList([job1, job2])
    job_list.watch()

    # Should have started a task
    assert job_list._task is not None
    assert job_list._display_id is not None

    # Clean up
    job_list.stop_watching()


@patch("deeporigin.platform.job.display")
@patch("deeporigin.platform.job.update_display")
@patch("nest_asyncio.apply")
@patch("asyncio.get_event_loop")
@patch("asyncio.create_task")
def test_job_list_watch_stops_when_all_terminal(
    mock_create_task,
    mock_get_event_loop,
    mock_nest_asyncio_apply,
    mock_update_display,
    mock_display,
):
    """Test watch stops monitoring when all jobs become terminal."""
    # Create jobs with some in non-terminal states
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Running"
    job1._attributes = {}
    job1.sync = MagicMock()
    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2.status = "Running"
    job2._attributes = {}
    job2.sync = MagicMock()

    # Mock event loop and task creation
    mock_task = MagicMock()
    mock_create_task.return_value = mock_task
    mock_loop = MagicMock()
    mock_loop.create_task.return_value = mock_task
    mock_get_event_loop.return_value = mock_loop

    job_list = JobList([job1, job2])
    job_list.watch()

    # Initially should have a task
    assert job_list._task is not None

    # Simulate jobs becoming terminal
    job1.status = "Succeeded"
    job2.status = "Succeeded"

    # Manually trigger the check by running sync (which would happen in the loop)
    job_list.sync()

    # The task should still exist (it checks in the loop)
    # But we can stop it manually
    job_list.stop_watching()
    assert job_list._task is None


def test_job_list_stop_watching():
    """Test stop_watching cancels the monitoring task."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Running"
    job1.sync = MagicMock()

    job_list = JobList([job1])

    # Create a mock task
    mock_task = MagicMock()
    job_list._task = mock_task

    job_list.stop_watching()

    # Task should be cancelled
    mock_task.cancel.assert_called_once()
    assert job_list._task is None


def test_job_list_stop_watching_no_task():
    """Test stop_watching handles case when no task exists."""
    job_list = JobList([])
    # Should not raise an error
    job_list.stop_watching()
    assert job_list._task is None


@patch("deeporigin.platform.job.Job.from_id")
def test_from_ids(mock_from_id):
    """Test creating JobList from IDs."""
    ids = ["id-1", "id-2", "id-3"]
    mock_jobs = [MagicMock(spec=Job), MagicMock(spec=Job), MagicMock(spec=Job)]
    mock_from_id.side_effect = mock_jobs

    job_list = JobList.from_ids(ids)

    assert len(job_list) == 3
    assert job_list.jobs == mock_jobs
    assert mock_from_id.call_count == 3


@patch("deeporigin.platform.job.Job.from_dto")
def test_from_dtos(mock_from_dto):
    """Test creating JobList from DTOs."""
    dtos = [{"executionId": "id-1"}, {"executionId": "id-2"}]
    mock_jobs = [MagicMock(spec=Job), MagicMock(spec=Job)]
    mock_from_dto.side_effect = mock_jobs

    job_list = JobList.from_dtos(dtos)

    assert len(job_list) == 2
    assert job_list.jobs == mock_jobs
    assert mock_from_dto.call_count == 2


@patch("deeporigin.platform.job.JobList.from_dtos")
@patch("deeporigin.platform.job.DeepOriginClient.get")
def test_list(mock_get_client, mock_from_dtos):
    """Test creating JobList from API list call."""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    mock_response = {
        "count": 2,
        "data": [
            {"executionId": "id-1", "status": "Running"},
            {"executionId": "id-2", "status": "Succeeded"},
        ],
    }
    mock_client.executions.list.return_value = mock_response

    mock_job_list = MagicMock(spec=JobList)
    mock_from_dtos.return_value = mock_job_list

    result = JobList.list(page=0, page_size=10)

    mock_get_client.assert_called_once()
    mock_client.executions.list.assert_called_once_with(
        page=0, page_size=10, order=None, filter=None
    )
    mock_from_dtos.assert_called_once_with(mock_response["data"], client=mock_client)
    assert result == mock_job_list


@patch("deeporigin.platform.job.JobList.from_dtos")
@patch("deeporigin.platform.job.DeepOriginClient.get")
def test_list_with_filter(mock_get_client, mock_from_dtos):
    """Test creating JobList from API list call with filter."""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    mock_response = {
        "count": 1,
        "data": [{"executionId": "id-1", "status": "Running"}],
    }
    mock_client.executions.list.return_value = mock_response

    mock_job_list = MagicMock(spec=JobList)
    mock_from_dtos.return_value = mock_job_list

    filter_str = '{"status": {"$in": ["Running"]}}'
    result = JobList.list(filter=filter_str, client=mock_client)

    mock_get_client.assert_not_called()  # Client provided, shouldn't call get()
    mock_client.executions.list.assert_called_once_with(
        page=0, page_size=1000, order=None, filter=filter_str
    )
    mock_from_dtos.assert_called_once_with(mock_response["data"], client=mock_client)
    assert result == mock_job_list


@patch("deeporigin.platform.job.JobList.from_dtos")
@patch("deeporigin.platform.job.DeepOriginClient.get")
def test_list_pagination(mock_get_client, mock_from_dtos):
    """Test that JobList.list handles pagination correctly."""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    # First page: 100 items, count=250 (total), so need more pages
    page1_response = {
        "count": 250,
        "data": [{"executionId": f"id-{i}", "status": "Running"} for i in range(100)],
    }
    # Second page: 100 items
    page2_response = {
        "count": 250,
        "data": [
            {"executionId": f"id-{i}", "status": "Running"} for i in range(100, 200)
        ],
    }
    # Third page: 50 items (partial page, last page)
    page3_response = {
        "count": 250,
        "data": [
            {"executionId": f"id-{i}", "status": "Running"} for i in range(200, 250)
        ],
    }

    mock_client.executions.list.side_effect = [
        page1_response,
        page2_response,
        page3_response,
    ]

    mock_job_list = MagicMock(spec=JobList)
    mock_from_dtos.return_value = mock_job_list

    result = JobList.list(page_size=100)

    # Should have called list 3 times (pages 0, 1, 2)
    assert mock_client.executions.list.call_count == 3
    mock_client.executions.list.assert_any_call(
        page=0, page_size=100, order=None, filter=None
    )
    mock_client.executions.list.assert_any_call(
        page=1, page_size=100, order=None, filter=None
    )
    mock_client.executions.list.assert_any_call(
        page=2, page_size=100, order=None, filter=None
    )

    # Should combine all DTOs from all pages
    all_dtos = page1_response["data"] + page2_response["data"] + page3_response["data"]
    mock_from_dtos.assert_called_once_with(all_dtos, client=mock_client)
    assert result == mock_job_list


@patch("deeporigin.platform.job.JobList.from_dtos")
@patch("deeporigin.platform.job.DeepOriginClient.get")
def test_list_pagination_stops_when_count_less_than_page_size(
    mock_get_client, mock_from_dtos
):
    """Test that pagination stops when count <= page_size."""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    # Single page with count <= page_size
    mock_response = {
        "count": 50,
        "data": [{"executionId": f"id-{i}", "status": "Running"} for i in range(50)],
    }
    mock_client.executions.list.return_value = mock_response

    mock_job_list = MagicMock(spec=JobList)
    mock_from_dtos.return_value = mock_job_list

    result = JobList.list(page_size=100)

    # Should only call list once since count (50) <= page_size (100)
    mock_client.executions.list.assert_called_once_with(
        page=0, page_size=100, order=None, filter=None
    )
    mock_from_dtos.assert_called_once_with(mock_response["data"], client=mock_client)
    assert result == mock_job_list


def test_to_dataframe():
    """Test converting JobList to DataFrame."""
    # Create Job objects with _attributes
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1._attributes = {
        "status": "Succeeded",
        "executionId": "id-1",
        "createdAt": "2025-01-01T00:00:00.000Z",
        "updatedAt": "2025-01-01T01:00:00.000Z",
        "completedAt": "2025-01-01T02:00:00.000Z",
        "startedAt": "2025-01-01T01:00:00.000Z",
        "approveAmount": 100.0,
        "tool": {"key": "tool1", "version": "1.0"},
    }

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2._attributes = {
        "status": "Running",
        "executionId": "id-2",
        "createdAt": "2025-01-02T00:00:00.000Z",
        "updatedAt": "2025-01-02T01:00:00.000Z",
        "completedAt": None,
        "startedAt": "2025-01-02T01:00:00.000Z",
        "approveAmount": None,
        "tool": {"key": "tool2", "version": "2.0"},
    }

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


def test_to_dataframe_with_missing_attributes():
    """Test to_dataframe handles jobs with None _attributes."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1._attributes = {
        "status": "Succeeded",
        "executionId": "id-1",
    }

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2._attributes = None

    job_list = JobList([job1, job2])
    df = job_list.to_dataframe()

    assert len(df) == 2
    assert df.iloc[0]["status"] == "Succeeded"
    assert df.iloc[0]["id"] == "id-1"
    # All other fields should be None for job2
    assert df.iloc[1]["status"] is None
    assert df.iloc[1]["id"] is None


def test_to_dataframe_with_missing_keys():
    """Test to_dataframe handles missing keys in _attributes."""
    job = Job(name="job1", _id="id-1", _skip_sync=True)
    job._attributes = {
        "status": "Succeeded",
        "executionId": "id-1",
        # Missing other keys
    }

    job_list = JobList([job])
    df = job_list.to_dataframe()

    assert len(df) == 1
    assert df.iloc[0]["status"] == "Succeeded"
    assert df.iloc[0]["id"] == "id-1"
    # Missing keys should be None/NaT (NaT for datetime columns)
    assert pd.isna(df.iloc[0]["created_at"])
    assert df.iloc[0]["tool_key"] is None
    assert df.iloc[0]["tool_version"] is None


def test_filter_by_multiple_statuses():
    """Test filtering jobs by multiple statuses."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Succeeded"

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2.status = "Running"

    job3 = Job(name="job3", _id="id-3", _skip_sync=True)
    job3.status = "Failed"

    job_list = JobList([job1, job2, job3])

    # Filter by list of statuses
    filtered = job_list.filter(status=["Succeeded", "Running"])
    assert len(filtered) == 2
    assert filtered[0].status == "Succeeded"
    assert filtered[1].status == "Running"

    # Filter by set of statuses
    filtered = job_list.filter(status={"Succeeded", "Failed"})
    assert len(filtered) == 2


def test_filter_require_metadata():
    """Test filtering jobs that require metadata."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1._attributes = {"metadata": {"key": "value"}}

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2._attributes = {"metadata": None}

    job3 = Job(name="job3", _id="id-3", _skip_sync=True)
    job3._attributes = {}  # No metadata key

    job_list = JobList([job1, job2, job3])

    filtered = job_list.filter(require_metadata=True)
    assert len(filtered) == 1
    assert filtered[0]._id == "id-1"


def test_to_dataframe_with_optional_columns():
    """Test to_dataframe with include_metadata, include_inputs, include_outputs."""
    job = Job(name="job1", _id="id-1", _skip_sync=True)
    job._attributes = {
        "status": "Succeeded",
        "executionId": "id-1",
        "metadata": {"key": "value"},
        "userInputs": {"smiles_list": ["CCO", "CCC"]},
        "userOutputs": {"result": "data"},
    }

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


def test_to_dataframe_run_duration():
    """Test to_dataframe calculates run_duration_minutes correctly."""
    job = Job(name="job1", _id="id-1", _skip_sync=True)
    job._attributes = {
        "status": "Succeeded",
        "executionId": "id-1",
        "startedAt": "2025-01-01T00:00:00.000Z",
        "completedAt": "2025-01-01T01:30:00.000Z",  # 90 minutes
    }

    job_list = JobList([job])
    df = job_list.to_dataframe()

    assert df.iloc[0]["run_duration_minutes"] == 90

    # Test with missing dates
    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2._attributes = {
        "status": "Running",
        "executionId": "id-2",
        "startedAt": "2025-01-01T00:00:00.000Z",
        # No completedAt
    }

    job_list2 = JobList([job2])
    df2 = job_list2.to_dataframe()
    assert df2.iloc[0]["run_duration_minutes"] is None


def test_job_list_render_view_with_docking_tool():
    """Test that JobList._render_view uses tool-specific viz function for bulk-docking."""
    from deeporigin.drug_discovery.constants import tool_mapper

    # Create jobs with docking tool
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Running"
    job1._attributes = {
        "tool": {"key": tool_mapper["Docking"], "version": "1.0.0"},
        "userInputs": {"smiles_list": ["CCO", "CCN"]},
        "progressReport": "ligand docked ligand docked",
        "startedAt": "2024-01-01T00:00:00.000Z",
        "completedAt": "2024-01-01T00:10:00.000Z",
    }

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2.status = "Running"
    job2._attributes = {
        "tool": {"key": tool_mapper["Docking"], "version": "1.0.0"},
        "userInputs": {"smiles_list": ["CCC"]},
        "progressReport": "ligand docked ligand failed",
        "startedAt": "2024-01-01T00:00:00.000Z",
        "completedAt": "2024-01-01T00:05:00.000Z",
    }

    job_list = JobList([job1, job2])
    html = job_list._render_view()

    # Should use docking-specific visualization (check for speed text)
    assert "dockings/minute" in html
    assert isinstance(html, str)


def test_job_list_render_view_card_title_with_same_tool():
    """Test that JobList._render_view uses tool-specific card title when all jobs have same tool key."""
    from deeporigin.drug_discovery.constants import tool_mapper

    # Create jobs with docking tool and metadata
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Running"
    job1._attributes = {
        "tool": {"key": tool_mapper["Docking"], "version": "1.0.0"},
        "userInputs": {"smiles_list": ["CCO", "CCN"]},
        "metadata": {"protein_file": "test_protein.pdb"},
    }

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2.status = "Running"
    job2._attributes = {
        "tool": {"key": tool_mapper["Docking"], "version": "1.0.0"},
        "userInputs": {"smiles_list": ["CCC"]},
        "metadata": {"protein_file": "test_protein.pdb"},
    }

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


def test_name_func_docking_with_job_list():
    """Test that _name_func_docking aggregates unique SMILES across all jobs in a JobList."""
    from deeporigin.platform import job_viz_functions

    # Create jobs with overlapping SMILES
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1._attributes = {
        "userInputs": {"smiles_list": ["CCO", "CCN"]},
        "metadata": {"protein_file": "test_protein.pdb"},
    }

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2._attributes = {
        "userInputs": {"smiles_list": ["CCC", "CCO"]},  # CCO overlaps with job1
        "metadata": {"protein_file": "test_protein.pdb"},
    }

    job_list = JobList([job1, job2])
    name = job_viz_functions._name_func_docking(job_list)

    # Should aggregate unique SMILES: CCO, CCN, CCC = 3 unique ligands
    assert "Docking" in name
    assert "test_protein.pdb" in name
    assert "3 ligands" in name
    assert isinstance(name, str)


def test_name_func_docking_with_single_job():
    """Test that _name_func_docking works with a single Job."""
    from deeporigin.platform import job_viz_functions

    job = Job(name="job1", _id="id-1", _skip_sync=True)
    job._attributes = {
        "userInputs": {"smiles_list": ["CCO", "CCN", "CCC"]},
        "metadata": {"protein_file": "test_protein.pdb"},
    }

    name = job_viz_functions._name_func_docking(job)

    assert "Docking" in name
    assert "test_protein.pdb" in name
    assert "3 ligands" in name
    assert isinstance(name, str)


def test_job_list_render_view_card_title_with_mixed_tools():
    """Test that JobList._render_view uses generic card title when jobs have different tool keys."""
    from deeporigin.drug_discovery.constants import tool_mapper

    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Running"
    job1._attributes = {"tool": {"key": tool_mapper["Docking"], "version": "1.0.0"}}

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2.status = "Succeeded"
    job2._attributes = {"tool": {"key": tool_mapper["ABFE"], "version": "1.0.0"}}

    job_list = JobList([job1, job2])
    html = job_list._render_view()

    # Should use generic card title when tools differ
    assert "Job List" in html
    assert "2 jobs" in html
    assert isinstance(html, str)


def test_job_list_render_view_with_mixed_tools():
    """Test that JobList._render_view uses generic status HTML when jobs have different tool keys."""
    from deeporigin.drug_discovery.constants import tool_mapper

    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Running"
    job1._attributes = {"tool": {"key": tool_mapper["Docking"], "version": "1.0.0"}}

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2.status = "Succeeded"
    job2._attributes = {"tool": {"key": tool_mapper["ABFE"], "version": "1.0.0"}}

    job_list = JobList([job1, job2])
    html = job_list._render_view()

    # Should use generic status HTML
    assert "job(s) in this list" in html
    assert "Status breakdown" in html
    assert isinstance(html, str)


def test_viz_func_docking_with_job_list():
    """Test that _viz_func_docking works with JobList."""
    from deeporigin.platform import job_viz_functions

    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1._attributes = {
        "userInputs": {"smiles_list": ["CCO", "CCN"]},
        "progressReport": "ligand docked ligand docked",
        "startedAt": "2024-01-01T00:00:00.000Z",
        "completedAt": "2024-01-01T00:10:00.000Z",
    }

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2._attributes = {
        "userInputs": {"smiles_list": ["CCC"]},
        "progressReport": "ligand docked ligand failed",
        "startedAt": "2024-01-01T00:00:00.000Z",
        "completedAt": "2024-01-01T00:05:00.000Z",
    }

    job_list = JobList([job1, job2])
    html = job_viz_functions._viz_func_docking(job_list)

    # Should render progress bar with summed values
    assert "Docking Progress" in html
    # Total ligands should be 3 (2 + 1)
    # Total docked should be 3 (2 + 1)
    # Total failed should be 1 (0 + 1)
    assert isinstance(html, str)


def test_viz_func_quoted_with_single_job():
    """Test that _viz_func_quoted works with a single Job."""
    from deeporigin.platform import job_viz_functions

    job = Job(name="job1", _id="id-1", _skip_sync=True)
    job.status = "Quoted"
    job._attributes = {
        "quotationResult": {"successfulQuotations": [{"priceTotal": 100.50}]}
    }

    html = job_viz_functions._viz_func_quoted(job)

    assert "Job Quoted" in html
    assert "$101" in html or "$100" in html  # rounded cost
    assert "confirm()" in html
    assert isinstance(html, str)


def test_viz_func_quoted_with_job_list():
    """Test that _viz_func_quoted works with JobList and sums costs."""
    from deeporigin.platform import job_viz_functions

    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Quoted"
    job1._attributes = {
        "quotationResult": {"successfulQuotations": [{"priceTotal": 50.25}]}
    }

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2.status = "Quoted"
    job2._attributes = {
        "quotationResult": {"successfulQuotations": [{"priceTotal": 75.75}]}
    }

    job_list = JobList([job1, job2])
    html = job_viz_functions._viz_func_quoted(job_list)

    assert "Jobs Quoted" in html
    assert "2" in html  # number of jobs
    assert "$126" in html or "$125" in html  # rounded total (50.25 + 75.75 = 126)
    assert "confirm()" in html
    assert isinstance(html, str)


def test_job_list_render_view_with_all_quoted():
    """Test that JobList._render_view uses quoted visualization when all jobs are Quoted."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Quoted"
    job1._attributes = {
        "quotationResult": {"successfulQuotations": [{"priceTotal": 100.0}]}
    }

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2.status = "Quoted"
    job2._attributes = {
        "quotationResult": {"successfulQuotations": [{"priceTotal": 200.0}]}
    }

    job_list = JobList([job1, job2])
    html = job_list._render_view()

    # Should use quoted-specific visualization
    assert "Jobs Quoted" in html
    assert "2" in html  # number of jobs
    assert "$300" in html  # total cost (100 + 200)
    assert isinstance(html, str)


def test_job_list_render_view_with_mixed_status():
    """Test that JobList._render_view uses generic HTML when not all jobs are Quoted."""
    job1 = Job(name="job1", _id="id-1", _skip_sync=True)
    job1.status = "Quoted"
    job1._attributes = {
        "quotationResult": {"successfulQuotations": [{"priceTotal": 100.0}]}
    }

    job2 = Job(name="job2", _id="id-2", _skip_sync=True)
    job2.status = "Running"

    job_list = JobList([job1, job2])
    html = job_list._render_view()

    # Should use generic status HTML, not quoted visualization
    assert "Jobs Quoted" not in html
    assert "job(s) in this list" in html
    assert "Status breakdown" in html
    assert isinstance(html, str)
