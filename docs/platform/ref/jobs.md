# Jobs API

The `Job` and `JobList` classes provide a high-level interface for working with tool executions (jobs) on Deep Origin.

## JobList

`JobList` represents a collection of jobs that can be monitored and managed together. It's especially useful for managing batch jobs like Docking, where a set of ligands can be batched into multiple executions on multiple resources.

### Creating a JobList

```python
from deeporigin.platform.job import JobList

# Fetch jobs from the API
jobs = JobList.list()

# Create from a list of job IDs
jobs = JobList.from_ids(["id-1", "id-2", "id-3"])

# Create from execution DTOs
jobs = JobList.from_dtos([dto1, dto2, dto3])
```

### Monitoring Jobs

The `watch()` method allows you to monitor multiple jobs in real-time. It will automatically stop when all jobs reach terminal states:

```python
# Start monitoring a list of jobs
jobs = JobList.from_ids(["id-1", "id-2", "id-3"])
jobs.watch()  # Updates every 5 seconds by default

# Custom update interval
jobs.watch(interval=10.0)  # Update every 10 seconds

# Stop monitoring manually
jobs.stop_watching()
```

The `watch()` method will:
- Display an initial status view
- Periodically sync all jobs and update the display
- Automatically stop when all jobs are in terminal states (Succeeded, Failed, Cancelled, etc.)
- Handle errors gracefully and continue monitoring

### Filtering Jobs

The `filter()` method allows you to filter jobs by status, attributes, or custom predicates:

**Filter by status:**

```python
# Get only succeeded jobs
succeeded_jobs = jobs.filter(status="Succeeded")

# Get only running jobs
running_jobs = jobs.filter(status="Running")
```

**Filter by tool attributes:**

```python
# Filter by tool key
docking_jobs = jobs.filter(tool_key="deeporigin.docking")

# Filter by tool version
v1_jobs = jobs.filter(tool_version="1.0.0")

# Filter by both tool key and version
specific_tool = jobs.filter(tool_key="deeporigin.abfe-end-to-end", tool_version="1.0.0")
```

**Filter by other attributes:**

```python
# Filter by execution ID
specific_job = jobs.filter(executionId="id-123")

# Filter by multiple attributes (AND logic)
filtered = jobs.filter(status="Running", executionId="id-123")
```

**Filter with custom predicate:**

```python
# Filter jobs with approveAmount > 100
expensive_jobs = jobs.filter(
    predicate=lambda job: job._attributes.get("approveAmount", 0) > 100
)

# Filter by nested attribute (tool.key)
tool_jobs = jobs.filter(
    predicate=lambda job: job._attributes.get("tool", {}).get("key") == "tool1"
)
```

**Combine filters:**

```python
# Status filter + tool filter + custom predicate
complex_filter = jobs.filter(
    status="Running",
    tool_key="deeporigin.docking",
    predicate=lambda job: "error" not in str(
        job._attributes.get("progressReport", "")
    )
)

# Status + tool key + tool version
specific_jobs = jobs.filter(
    status="Succeeded",
    tool_key="deeporigin.abfe-end-to-end",
    tool_version="1.0.0"
)
```

::: src.platform.job.JobList
    options:
      heading_level: 2
      docstring_style: google
      show_root_heading: true
      show_category_heading: true
      show_object_full_path: false
      show_root_toc_entry: false
      inherited_members: true
      members_order: alphabetical
      filters:
        - "!^_"  # Exclude private members (names starting with "_")
      show_signature: true
      show_signature_annotations: true
      show_if_no_docstring: true
      group_by_category: true

## Job

`Job` represents a single computational job that can be monitored and managed.

::: src.platform.job.Job
    options:
      heading_level: 2
      docstring_style: google
      show_root_heading: true
      show_category_heading: true
      show_object_full_path: false
      show_root_toc_entry: false
      inherited_members: true
      members_order: alphabetical
      filters:
        - "!^_"  # Exclude private members (names starting with "_")
      show_signature: true
      show_signature_annotations: true
      show_if_no_docstring: true
      group_by_category: true

