"""this module contains the Job class"""

import asyncio
from collections import Counter
import concurrent.futures
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Dict, List, Optional, Protocol

try:
    from beartype.typing import Callable
except ImportError:
    from typing import Callable  # fallback for older beartype versions
import uuid

from beartype import beartype
from dateutil import parser
import humanize
from IPython.display import HTML, display, update_display
from jinja2 import Environment, FileSystemLoader
import pandas as pd

from deeporigin.drug_discovery.constants import tool_mapper
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform import job_viz_functions
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TERMINAL_STATES
from deeporigin.utils.core import elapsed_minutes

# Get the template directory
template_dir = Path(__file__).parent.parent / "templates"
# Create Jinja2 environment with auto-escaping disabled
# Note: Auto-escaping is disabled because the template needs to render HTML content
# from _viz_func and properly formatted JSON data. The |safe filter is used
# only for trusted content (JSON data and HTML from _viz_func).
# All other template variables are properly escaped by the template itself.
env = Environment(  # NOSONAR
    loader=FileSystemLoader(str(template_dir)),
    autoescape=False,
)


class JobFunc(Protocol):
    """A protocol for functions that can be used to visualize a job or render a name for a job."""

    def __call__(self, job: "Job") -> str: ...


@dataclass
class Job:
    """
    Represents a single computational job that can be monitored and managed.

    This class provides methods to track, visualize, and parse the status and progress of a job, with optional real-time updates (e.g., in Jupyter notebooks).

    Attributes:
        name (str): Name of the job.
    """

    name: str
    _id: str

    # functions
    _viz_func: Optional[JobFunc] = None
    _parse_func: Optional[JobFunc] = None
    _name_func: Optional[JobFunc] = field(default_factory=lambda: lambda job: "Job")

    _task = None
    _attributes: Optional[dict] = None
    status: Optional[str] = None
    _display_id: Optional[str] = None
    _last_html: Optional[str] = None
    _skip_sync: bool = False

    # clients
    client: Optional[DeepOriginClient] = None

    def __post_init__(self):
        if not self._skip_sync:
            self.sync()

            if self._viz_func is None:
                tool = self._attributes.get("tool") if self._attributes else None
                if isinstance(tool, dict) and "key" in tool:
                    if tool["key"] == tool_mapper["Docking"]:
                        self._viz_func = job_viz_functions._viz_func_docking
                        self._name_func = job_viz_functions._name_func_docking
                    elif tool["key"] == tool_mapper["ABFE"]:
                        self._viz_func = job_viz_functions._viz_func_abfe
                        self._name_func = job_viz_functions._name_func_abfe
                    elif tool["key"] == tool_mapper["RBFE"]:
                        self._viz_func = job_viz_functions._viz_func_rbfe
                        self._name_func = job_viz_functions._name_func_rbfe

    @classmethod
    def from_id(
        cls,
        id: str,
        *,
        client: Optional[DeepOriginClient] = None,
    ) -> "Job":
        """Create a Job instance from a single ID.

        Args:
            id: Job ID to track.
            client: Optional client for API calls.

        Returns:
            A new Job instance with the given ID.
        """
        return cls(
            name="job",
            _id=id,
            client=client,
        )

    @classmethod
    @beartype
    def from_dto(
        cls,
        dto: dict,
        *,
        client: Optional[DeepOriginClient] = None,
    ) -> "Job":
        """Create a Job instance from an execution DTO (Data Transfer Object).

        This method constructs a Job from the full execution description without
        making a network request. It is faster than from_id() when you already
        have the execution data.

        Args:
            dto: Dictionary containing the full execution description from the API.
                Must contain at least 'executionId' and 'status' fields.
            client: Optional client for API calls.

        Returns:
            A new Job instance constructed from the DTO.
        """
        execution_id = dto.get("executionId")
        if execution_id is None:
            raise ValueError("DTO must contain 'executionId' field")

        job = cls(
            name="job",
            _id=execution_id,
            client=client,
            _skip_sync=True,
        )

        # Set attributes and status directly from DTO
        job._attributes = dto
        job.status = dto.get("status")

        # Set up visualization functions based on tool
        if job._viz_func is None:
            tool = dto.get("tool")
            if isinstance(tool, dict) and "key" in tool:
                if tool["key"] == tool_mapper["Docking"]:
                    job._viz_func = job_viz_functions._viz_func_docking
                    job._name_func = job_viz_functions._name_func_docking
                elif tool["key"] == tool_mapper["ABFE"]:
                    job._viz_func = job_viz_functions._viz_func_abfe
                    job._name_func = job_viz_functions._name_func_abfe
                elif tool["key"] == tool_mapper["RBFE"]:
                    job._viz_func = job_viz_functions._viz_func_rbfe
                    job._name_func = job_viz_functions._name_func_rbfe

        return job

    def sync(self):
        """Synchronize the job status and progress report.

        This method updates the internal state by fetching the latest status
        and progress report for the job ID. It skips jobs that have already
        reached a terminal state (Succeeded or Failed).
        """

        if self.client is None:
            self.client = DeepOriginClient.get()

        # use
        result = self.client.executions.get_execution(execution_id=self._id)

        if result:
            self._attributes = result
            self.status = result.get("status")

    def _get_running_time(self) -> Optional[int]:
        """Get the running time of the job.

        Returns:
            The running time of the job in minutes, or None if not available.
        """
        if (
            self._attributes is None
            or self._attributes.get("completedAt") is None
            or self._attributes.get("startedAt") is None
        ):
            return None
        else:
            return elapsed_minutes(
                self._attributes["startedAt"], self._attributes["completedAt"]
            )

    def _render_json_viewer(self, obj: dict) -> str:
        """
        Create an interactive JSON viewer HTML snippet for the given dictionary.

        This method generates HTML and JavaScript code that renders the provided
        dictionary as an interactive JSON viewer in a web environment (e.g., Jupyter notebook).
        It uses the @textea/json-viewer library via CDN to display the JSON data.

        Args:
            obj (dict): The dictionary to display in the JSON viewer.

        Returns:
            str: HTML and JavaScript code to render the interactive JSON viewer.
        """
        import json
        import uuid

        uid = f"json_viewer_{uuid.uuid4().hex}"
        data = json.dumps(obj)

        html = f"""
        <div id="{uid}" style="padding:10px;border:1px solid #ddd;"></div>
        <script>
        (function() {{
        const mountSelector = "#{uid}";
        function render() {{
            new JsonViewer({{ value: {data}, showCopy: true, rootName: false }})
            .render(mountSelector);
        }}

        // If JsonViewer is already present, render immediately; otherwise load it then render.
        if (window.JsonViewer) {{
            render();
        }} else {{
            const s = document.createElement('script');
            s.src = "https://cdn.jsdelivr.net/npm/@textea/json-viewer@3";
            s.onload = render;
            document.head.appendChild(s);
        }}
        }})();
        </script>
        """

        return html

    @beartype
    def _render_job_view(
        self,
        *,
        will_auto_update: bool = False,
        notebook_environment: Optional[str] = None,
    ):
        """Display the current job status and progress report.

        This method renders and displays the current state of the job
        using the visualization function if set, or a default HTML representation.
        """

        from deeporigin.utils.notebook import get_notebook_environment

        if notebook_environment is None:
            notebook_environment = get_notebook_environment()

        if notebook_environment == "jupyter":
            # this template uses shadow DOM to avoid CSS/JS conflicts with jupyter
            # however, for reasons i don't understand, it doesn't work in marimo/browser
            template = env.get_template("job_jupyter.html")
        else:
            # this one is more straightforward, and works in marimo/browser
            template = env.get_template("job.html")

        # Handle "Quoted" status with custom message
        if self.status == "Quoted":
            quotation_result = (
                self._attributes.get("quotationResult") if self._attributes else None
            )
            try:
                estimated_cost = quotation_result["successfulQuotations"][0][
                    "priceTotal"
                ]
                status_html = (
                    "<h3>Job Quoted</h3>"
                    f"<p>This job has been quoted. It is estimated to cost <strong>${round(estimated_cost)}</strong>. "
                    "For details look at the Billing tab. To approve and start the run, call the "
                    "<code style='font-family: monospace; background-color: #f5f5f5; padding: 2px 4px; border-radius: 3px;'>confirm()</code> method.</p>"
                )
            except (AttributeError, IndexError, KeyError, TypeError):
                status_html = (
                    "<h3>Job Quoted</h3>"
                    "<p>This job has been quoted. For details look at the Billing tab. To approve and start the run, call the "
                    "<code style='font-family: monospace; background-color: #f5f5f5; padding: 2px 4px; border-radius: 3px;'>confirm()</code> method.</p>"
                )
        else:
            try:
                status_html = self._viz_func(self)
            except Exception as e:
                status_html = f"No visualization function provided, or there was an error. Error: {e}"

        try:
            card_title = self._name_func(self)
        except Exception:
            card_title = "No name function provided."

        started_at = None
        if (
            self._attributes is not None
            and self._attributes.get("startedAt") is not None
        ):
            dt = parser.isoparse(self._attributes["startedAt"]).astimezone(timezone.utc)
            # Compare to now (also in UTC)
            now = datetime.now(timezone.utc)
            started_at = humanize.naturaltime(now - dt)

        running_time = self._get_running_time()

        # Generate interactive JSON viewer HTML for inputs and outputs
        inputs = self._attributes.get("userInputs") if self._attributes else None
        outputs = self._attributes.get("userOutputs") if self._attributes else None
        inputs_fallback = inputs if inputs else {}
        inputs_json_viewer = self._render_json_viewer(
            inputs.to_dict()
            if hasattr(inputs, "to_dict") and inputs is not None
            else inputs_fallback
        )
        outputs_fallback = outputs if outputs else {}
        outputs_json_viewer = self._render_json_viewer(
            outputs.to_dict()
            if hasattr(outputs, "to_dict") and outputs is not None
            else outputs_fallback
        )
        combined_billing_data = {
            "billingTransaction": self._attributes.get("billingTransaction")
            if self._attributes
            else None,
            "quotationResult": self._attributes.get("quotationResult")
            if self._attributes
            else None,
        }
        billing_json_viewer = self._render_json_viewer(combined_billing_data)

        # Prepare template variables
        progress_report = (
            self._attributes.get("progressReport") if self._attributes else None
        )
        resource_id = self._attributes.get("resourceId") if self._attributes else None
        template_vars = {
            "status_html": status_html,
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "outputs_json": json.dumps(outputs, indent=2) if outputs else "{}",
            "inputs_json": json.dumps(inputs, indent=2) if inputs else "{}",
            "inputs_json_viewer": inputs_json_viewer,
            "outputs_json_viewer": outputs_json_viewer,
            "billing_json_viewer": billing_json_viewer,
            "job_id": self._id,
            "resource_id": resource_id,
            "status": self.status,
            "started_at": started_at,
            "running_time": running_time,
            "card_title": card_title,
            "unique_id": str(uuid.uuid4()),
            "will_auto_update": will_auto_update,
        }

        # Determine auto-update behavior based on terminal states
        if self.status and self.status in TERMINAL_STATES:
            template_vars["will_auto_update"] = False  # job in terminal state

        # Try to parse progress report as JSON, fall back to raw text if it fails
        try:
            if progress_report:
                parsed_report = json.loads(str(progress_report))
                template_vars["raw_progress_json"] = json.dumps(parsed_report, indent=2)
            else:
                template_vars["raw_progress_json"] = "{}"
        except Exception:
            # If something goes wrong with the parsing, fall back to raw text
            template_vars["raw_progress_json"] = (
                str(progress_report) if progress_report else "{}"
            )
            template_vars["raw_progress_json"].replace("\n", "<br>")

        # Render the template
        return template.render(**template_vars)

    @beartype
    def _compose_error_overlay_html(self, *, message: str) -> str:
        """Compose an error overlay banner HTML for transient failures.

        Args:
            message: Error message to display.

        Returns:
            HTML string for an overlay banner indicating a temporary issue.
        """
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        return (
            "<div style='background: #fff4f4; border: 1px solid #f0b5b5; color: #8a1f1f;"
            " padding: 8px 12px; margin-bottom: 8px; border-radius: 6px;'>"
            f"Network/update issue at {timestamp}. Will retry automatically. Error: {message}"
            "</div>"
        )

    def show(self):
        """Display the job view in a Jupyter notebook.

        This method renders the job view and displays it in a Jupyter notebook.
        """
        rendered_html = self._render_job_view()
        display(HTML(rendered_html))

    def watch(self, *, interval: float = 5.0):
        """Start monitoring job progress in real-time.

        This method initiates a background task that periodically updates
        and displays the job status. It will automatically stop when the
        job reaches a terminal state (Succeeded or Failed). If there is no
        active job to monitor, it will display a message and show the current
        state once.
        """

        # Enable nested event loops for Jupyter
        import nest_asyncio

        nest_asyncio.apply()

        # Check if there is any active job (not terminal state)
        if self.status and self.status in TERMINAL_STATES:
            display(
                HTML(
                    "<div style='color: gray;'>No active job to monitor. This display will not update.</div>"
                )
            )
            self.show()
            return

        # Stop any existing task before starting a new one
        self.stop_watching()

        # for reasons i don't understand, removing this breaks the display rendering
        # when we do job.watch()
        initial_html = HTML("<div style='color: gray;'>Initializing...</div>")
        display_id = str(uuid.uuid4())
        self._display_id = display_id
        display(initial_html, display_id=display_id)

        async def update_progress_report():
            """Update and display job progress at regular intervals.

            This coroutine runs in the background, updating the display
            with the latest job status and progress every `interval` seconds.
            It automatically stops when the job reaches a terminal state.
            """
            try:
                while True:
                    try:
                        # Run sync in a worker thread without timeout to avoid the timeout issue
                        await asyncio.to_thread(self.sync)

                        html = self._render_job_view(will_auto_update=True)
                        update_display(HTML(html), display_id=self._display_id)
                        self._last_html = html

                        # Check if job is in terminal state
                        if self.status and self.status in TERMINAL_STATES:
                            break

                    except Exception as e:
                        # Show a transient error banner, but keep the task alive
                        banner = self._compose_error_overlay_html(message=str(e))
                        fallback = (
                            self._last_html
                            or "<div style='color: gray;'>No data yet.</div>"
                        )
                        update_display(
                            HTML(banner + fallback), display_id=self._display_id
                        )

                    # Always sleep 5 seconds before next attempt
                    await asyncio.sleep(interval)
            finally:
                # Perform a final non-blocking refresh and render to clear spinner
                if self._display_id is not None:
                    try:
                        await asyncio.to_thread(self.sync)
                    except Exception:
                        pass
                    try:
                        final_html = self._render_job_view(will_auto_update=False)
                        update_display(HTML(final_html), display_id=self._display_id)
                    except Exception:
                        pass
                    self._display_id = None

        # Schedule the task using the current event loop
        try:
            loop = asyncio.get_event_loop()
            self._task = loop.create_task(update_progress_report())
        except RuntimeError:
            # If no event loop is running, create a new one
            self._task = asyncio.create_task(update_progress_report())

    def stop_watching(self):
        """Stop the background monitoring task.

        This method safely cancels and cleans up any running monitoring task.
        It is called automatically when all jobs reach a terminal state,
        or can be called manually to stop monitoring.
        """
        if self._task is not None:
            # Cancel the task; its finally block performs the final render and cleanup
            try:
                self._task.cancel()
            except Exception:
                pass
            finally:
                self._task = None

    def _repr_html_(self) -> str:
        """Return HTML representation for Jupyter notebooks.

        This method is called by Jupyter to display the job object in a notebook.
        It uses the visualization function if set, otherwise returns a basic
        HTML representation of the job's state.

        Returns:
            HTML string representing the job object.
        """

        return self._render_job_view()

    def cancel(self):
        """Cancel the job being tracked by this instance.

        This method sends a cancellation request for the job ID tracked by this instance
        using the utils.cancel_runs function.

        Returns:
            The result of the cancellation operation from utils.cancel_runs.
        """

        self.client.executions.cancel(
            execution_id=self._id,
        )

        self.sync()

    def confirm(self):
        """Confirm the job being tracked by this instance.

        This method confirms the job being tracked by this instance, and requests the job to be started.
        """

        if self.status != "Quoted":
            raise DeepOriginException(
                title="Job is not in the 'Quoted' state.",
                level="warning",
                message=f"Job is in the '{self.status}' state. Only Quoted jobs can be confirmed.",
            )
        else:
            self.client.executions.confirm(
                execution_id=self._id,
            )

            self.sync()


class JobList:
    """
    Represents a collection of Jobs that can be monitored and managed together.

    This class provides methods to track, visualize, and manage multiple jobs as a single unit, and is especially useful for
    managing batch jobs like Docking, where a set of ligands can be batched into multiple executions on multiple resources.
    """

    def __init__(self, jobs: List[Job]):
        """Initialize a JobList with a list of Job objects.

        Args:
            jobs: A list of Job objects.
        """
        self.jobs = jobs

    def __iter__(self):
        """Iterate over the jobs in the list."""
        return iter(self.jobs)

    def __len__(self):
        """Return the number of jobs in the list."""
        return len(self.jobs)

    def __getitem__(self, index):
        """Get a job by index."""
        return self.jobs[index]

    def _repr_html_(self) -> str:
        """Return HTML representation for Jupyter notebooks.

        Displays a summary of the JobList including the number of jobs and their status breakdown.
        """
        num_jobs = len(self.jobs)
        status_breakdown = self.status

        # Format status breakdown
        status_items = []
        for status, count in sorted(status_breakdown.items()):
            status_items.append(f"{status}: {count}")
        status_str = (
            ", ".join(status_items) if status_items else "No status information"
        )

        html = (
            f"<div style='padding: 10px; border: 1px solid #ddd; border-radius: 5px;'>"
            f"<p><strong>{num_jobs}</strong> job(s)</p>"
            f"<p>Statuses: {status_str}</p>"
            f"<p style='color: #666; font-size: 0.9em;'>Use <code>to_dataframe()</code> to view full details</p>"
            f"</div>"
        )
        return html

    @property
    def status(self) -> Dict[str, int]:
        """Get a breakdown of the statuses of all jobs in the list.

        Returns:
            A dictionary mapping status strings to counts.
        """
        statuses = [job.status for job in self.jobs if job.status is not None]
        return dict(Counter(statuses))

    def confirm(self, max_workers: int = 4):
        """Confirm all jobs in the list in parallel.

        Args:
            max_workers: The maximum number of threads to use for parallel execution.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(job.confirm) for job in self.jobs]
            concurrent.futures.wait(futures)

    def cancel(self, max_workers: int = 4):
        """Cancel all jobs in the list in parallel.

        Args:
            max_workers: The maximum number of threads to use for parallel execution.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(job.cancel) for job in self.jobs]
            concurrent.futures.wait(futures)

    def show(self):
        """Display the job list view. (Placeholder)"""
        raise NotImplementedError("Visualization for JobList is not yet implemented.")

    def watch(self):
        """Start monitoring job list progress. (Placeholder)"""
        raise NotImplementedError("Monitoring for JobList is not yet implemented.")

    @beartype
    def filter(
        self,
        *,
        status: Optional[str] = None,
        tool_key: Optional[str] = None,
        tool_version: Optional[str] = None,
        predicate: Optional[Callable[[Job], bool]] = None,
        **kwargs,
    ) -> "JobList":
        """Filter jobs by status, tool attributes, other attributes, or custom predicate.

        This method returns a new JobList containing only jobs that match the specified
        criteria. Multiple filters can be combined - keyword arguments are applied
        first (with AND logic), then the predicate function is applied if provided.

        Args:
            status: Filter by job status (e.g., "Succeeded", "Running", "Failed").
                Checks against job.status property.
            tool_key: Filter by tool key (e.g., "deeporigin.docking", "deeporigin.abfe-end-to-end").
                Checks against job._attributes["tool"]["key"].
            tool_version: Filter by tool version (e.g., "1.0.0").
                Checks against job._attributes["tool"]["version"].
            predicate: Optional callable that takes a Job and returns True/False.
                Applied after keyword filters. Useful for complex conditions or
                accessing nested attributes.
            **kwargs: Additional filters on job._attributes keys. Each keyword
                argument is treated as a key in _attributes, and the value must
                match exactly (equality check).

        Returns:
            A new JobList instance containing only matching jobs.

        Examples:
            Filter by status::

                succeeded_jobs = jobs.filter(status="Succeeded")
                running_jobs = jobs.filter(status="Running")

            Filter by tool attributes::

                docking_jobs = jobs.filter(tool_key="deeporigin.docking")
                specific_version = jobs.filter(tool_key="deeporigin.abfe-end-to-end", tool_version="1.0.0")

            Filter by multiple attributes::

                specific_job = jobs.filter(status="Running", executionId="id-123")

            Filter with custom predicate::

                expensive_jobs = jobs.filter(
                    predicate=lambda job: job._attributes.get("approveAmount", 0) > 100
                )

            Combine filters::

                # Status filter + tool filter + custom predicate
                complex_filter = jobs.filter(
                    status="Running",
                    tool_key="deeporigin.docking",
                    predicate=lambda job: "error" not in str(
                        job._attributes.get("progressReport", "")
                    )
                )
        """
        filtered = self.jobs

        # Apply status filter
        if status is not None:
            filtered = [job for job in filtered if job.status == status]

        # Apply tool_key filter
        if tool_key is not None:
            filtered = [
                job
                for job in filtered
                if job._attributes
                and job._attributes.get("tool", {}).get("key") == tool_key
            ]

        # Apply tool_version filter
        if tool_version is not None:
            filtered = [
                job
                for job in filtered
                if job._attributes
                and job._attributes.get("tool", {}).get("version") == tool_version
            ]

        # Apply attribute filters
        for key, value in kwargs.items():
            filtered = [
                job
                for job in filtered
                if job._attributes and job._attributes.get(key) == value
            ]

        # Apply custom predicate if provided
        if predicate is not None:
            filtered = [job for job in filtered if predicate(job)]

        return JobList(filtered)

    def to_dataframe(self) -> pd.DataFrame:
        """Convert the JobList to a pandas DataFrame.

        Extracts data from each job's _attributes dictionary and creates a DataFrame
        with the default columns: status, executionId, createdAt, updatedAt,
        completedAt, startedAt, approveAmount, tool.key, and tool.version.

        Returns:
            A pandas DataFrame with one row per job.
        """
        # Initialize lists to store data
        data = {
            "status": [],
            "executionId": [],
            "createdAt": [],
            "updatedAt": [],
            "completedAt": [],
            "startedAt": [],
            "approveAmount": [],
            "tool.key": [],
            "tool.version": [],
        }

        for job in self.jobs:
            attributes = job._attributes if job._attributes else {}

            data["status"].append(attributes.get("status"))
            data["executionId"].append(attributes.get("executionId"))
            data["createdAt"].append(attributes.get("createdAt"))
            data["updatedAt"].append(attributes.get("updatedAt"))
            data["completedAt"].append(attributes.get("completedAt"))
            data["startedAt"].append(attributes.get("startedAt"))
            data["approveAmount"].append(attributes.get("approveAmount"))

            # Extract tool.key and tool.version from tool dict
            tool = attributes.get("tool")
            if isinstance(tool, dict):
                data["tool.key"].append(tool.get("key"))
                data["tool.version"].append(tool.get("version"))
            else:
                data["tool.key"].append(None)
                data["tool.version"].append(None)

        # Create DataFrame
        df = pd.DataFrame(data)

        # Convert datetime columns
        datetime_cols = ["createdAt", "updatedAt", "completedAt", "startedAt"]
        for col in datetime_cols:
            if col in df.columns:
                df[col] = (
                    pd.to_datetime(
                        df[col], errors="coerce", utc=True
                    )  # parse → tz-aware
                    .dt.tz_localize(None)  # drop the UTC tz-info
                    .astype("datetime64[us]")  # truncate to microseconds
                )

        return df

    @classmethod
    def list(
        cls,
        *,
        page: Optional[int] = None,
        page_size: int = 1000,
        order: Optional[str] = None,
        filter: Optional[str] = None,
        client: Optional[DeepOriginClient] = None,
    ) -> "JobList":
        """Fetch executions from the API and return a JobList.

        This method automatically handles pagination, fetching all pages if necessary
        and combining them into a single JobList.

        Args:
            page: Page number to start from (default 0). If None, starts from page 0.
            page_size: Page size of the pagination (max 10,000).
            order: Order of the pagination, e.g., "executionId? asc", "completedAt? desc".
            filter: Filter applied to the data set Execution Model.
            client: Optional client for API calls.

        Returns:
            A new JobList instance containing the fetched jobs.
        """
        if client is None:
            client = DeepOriginClient.get()

        # Start from page 0 if not specified
        current_page = page if page is not None else 0
        all_dtos: List[dict] = []

        while True:
            response = client.executions.list(
                page=current_page,
                page_size=page_size,
                order=order,
                filter=filter,
            )

            if not isinstance(response, dict):
                # If response is not a dict, treat it as a list of DTOs
                all_dtos.extend(response if isinstance(response, list) else [])
                break

            page_dtos = response.get("data", [])
            all_dtos.extend(page_dtos)

            # Check if there are more pages to fetch
            count = response.get("count", 0)

            # If count > page_size, there are more items than fit in one page
            # Continue fetching until we've got all items
            if count > page_size:
                # Check if we got a partial page (indicating last page)
                if len(page_dtos) < page_size:
                    # Partial page means we're done
                    break
                # Check if we've fetched all items (if count represents total)
                if len(all_dtos) >= count:
                    # We've fetched all items
                    break
                # Move to next page
                current_page += 1
            else:
                # count <= page_size means we've got everything in this page
                break

        return cls.from_dtos(all_dtos, client=client)

    @classmethod
    def from_ids(
        cls,
        ids: List[str],
        *,
        client: Optional[DeepOriginClient] = None,
    ) -> "JobList":
        """Create a JobList from a list of job IDs.

        Args:
            ids: A list of job IDs.
            client: Optional client for API calls.

        Returns:
            A new JobList instance.
        """
        jobs = [Job.from_id(id, client=client) for id in ids]
        return cls(jobs)

    @classmethod
    def from_dtos(
        cls,
        dtos: List[dict],
        *,
        client: Optional[DeepOriginClient] = None,
    ) -> "JobList":
        """Create a JobList from a list of execution DTOs.

        Args:
            dtos: A list of execution DTOs.
            client: Optional client for API calls.

        Returns:
            A new JobList instance.
        """
        jobs = [Job.from_dto(dto, client=client) for dto in dtos]
        return cls(jobs)


# @beartype
def get_dataframe(  #
    *,
    tool_key: Optional[str] = None,
    only_with_status: Optional[list[str] | set[str]] = None,
    include_metadata: bool = False,
    include_inputs: bool = False,
    include_outputs: bool = False,
    resolve_user_names: bool = False,
    client: Optional[DeepOriginClient] = None,
) -> pd.DataFrame:
    """Get a dataframe of the job statuses and progress reports.

    Returns:
        A dataframe of the job statuses and progress reports.
    """

    if only_with_status is None:
        only_with_status = [
            "Succeeded",
            "Running",
            "Queued",
            "Failed",
            "Created",
            "Cancelled",
        ]

    if isinstance(only_with_status, set):
        only_with_status = list(only_with_status)

    _filter = {
        "status": {"$in": only_with_status},
        "metadata": {
            "$exists": True,
            "$ne": None,
        },
    }

    if tool_key is not None:
        _filter["tool"] = {
            "toolManifest": {
                "key": tool_key,
            },
        }

    if client is None:
        from deeporigin.platform.client import DeepOriginClient

        client = DeepOriginClient.get()

    # Serialize filter dict to JSON string
    filter_str = json.dumps(_filter) if _filter else None
    result = client.executions.list(
        filter=filter_str,
        page_size=10000,
    )
    # Extract jobs list from paginated response
    jobs = result.get("data", []) if isinstance(result, dict) else result

    if resolve_user_names:
        from deeporigin.platform import entities_api

        users = entities_api.get_organization_users(
            client=client,
        )

        # Create a mapping of user IDs to user names
        user_id_to_name = {
            user["id"]: user["firstName"] + " " + user["lastName"] for user in users
        }

    # Initialize lists to store data
    data = {
        "id": [],
        "created_at": [],  # converting some fields to snake_case
        "resource_id": [],
        "completed_at": [],
        "started_at": [],
        "status": [],
        "tool_key": [],
        "tool_version": [],
        "user_name": [],
        "run_duration_minutes": [],
        "n_ligands": [],
    }

    if include_metadata:
        data["metadata"] = []

    if include_inputs:
        data["user_inputs"] = []

    if include_outputs:
        data["user_outputs"] = []

    for job in jobs:
        # Add basic fields
        data["id"].append(job["executionId"])
        data["created_at"].append(job["createdAt"])
        data["resource_id"].append(job["resourceId"])
        data["completed_at"].append(job["completedAt"])
        data["started_at"].append(job["startedAt"])
        data["status"].append(job["status"])
        data["tool_key"].append(job["tool"]["key"])
        data["tool_version"].append(job["tool"]["version"])

        user_id = job.get("createdBy", "Unknown")

        if resolve_user_names:
            data["user_name"].append(user_id_to_name.get(user_id, "Unknown"))
        else:
            data["user_name"].append(user_id)

        user_inputs = job.get("userInputs", {})

        if include_inputs:
            data["user_inputs"].append(user_inputs)

        if "smiles_list" in user_inputs:
            data["n_ligands"].append(len(user_inputs["smiles_list"]))
        else:
            data["n_ligands"].append(1)

        # Handle protein_id (may not exist or metadata may be None)
        metadata = job.get("metadata")

        # Calculate run duration in minutes and round to nearest integer
        if job["completedAt"] and job["startedAt"]:
            start = parser.isoparse(job["startedAt"])
            end = parser.isoparse(job["completedAt"])
            duration = round((end - start).total_seconds() / 60)
            data["run_duration_minutes"].append(duration)
        else:
            data["run_duration_minutes"].append(None)

        if include_metadata:
            data["metadata"].append(metadata)

        if include_outputs:
            data["user_outputs"].append(job.get("userOutputs", {}))

    # Create DataFrame
    df = pd.DataFrame(data)

    # Convert datetime columns
    datetime_cols = ["created_at", "completed_at", "started_at"]
    for col in datetime_cols:
        df[col] = (
            pd.to_datetime(df[col], errors="coerce", utc=True)  # parse → tz-aware
            .dt.tz_localize(None)  # drop the UTC tz-info
            .astype("datetime64[us]")  # truncate to microseconds
        )

    return df
