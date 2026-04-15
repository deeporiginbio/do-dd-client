# Jobs API

> **Removed:** The `Job` and `JobList` helper types are no longer part of the SDK. This page keeps the **previous** documentation for that API (behavior, methods, and examples) so you can interpret older notebooks and migrations. It does not describe a supported import path in current releases.

What follows describes how `Job` and `JobList` worked when they were available: a high-level interface for tool executions (jobs) on Deep Origin.

## JobList

`JobList` represents a collection of jobs that can be monitored and managed together. It's especially useful for managing batch jobs like Docking, where a set of ligands can be batched into multiple executions on multiple resources.

### Creating a JobList

```{.python notest}
# Historical SDKs only (module and classes removed).
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

```{.python notest}
# Start monitoring a list of jobs
jobs = JobList.from_ids(["id-1", "id-2", "id-3"])
jobs.watch()  # Updates every 5 seconds by default

# Custom update interval
jobs.watch(interval=10)  # Update every 10 seconds

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

```{.python notest}
# Get only succeeded jobs
succeeded_jobs = jobs.filter(status="Succeeded")

# Get only running jobs
running_jobs = jobs.filter(status="Running")
```

**Filter by tool attributes:**

```{.python notest}
# Filter by tool key
docking_jobs = jobs.filter(tool_key="deeporigin.bulk-docking")

# Filter by tool version
v1_jobs = jobs.filter(tool_version="1.0.0")

# Filter by both tool key and version
specific_tool = jobs.filter(tool_key="deeporigin.abfe-end-to-end", tool_version="1.0.0")
```

**Filter by other attributes:**

```{.python notest}
# Filter by execution ID
specific_job = jobs.filter(executionId="id-123")

# Filter by multiple attributes (AND logic)
filtered = jobs.filter(status="Running", executionId="id-123")
```

**Filter with custom predicate:**

```{.python notest}
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

```{.python notest}
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

## Job

`Job` represents a single computational job that can be monitored and managed.

### Duplicating a Job

The `duplicate()` method allows you to create a new job with the same parameters as an existing job:

```{.python notest}
# Historical SDKs only (module and classes removed).
from deeporigin.platform.job import Job

# Get an existing job
job = Job.from_id("existing-job-id")

# Create a duplicate with the same parameters
new_job = job.duplicate()
```

The `duplicate()` method extracts the necessary fields from the original job (userInputs, userOutputs, orgKey, tag, and tool) and submits them as a new execution. The platform will fill in all other fields (executionId, status, timestamps, etc.).
