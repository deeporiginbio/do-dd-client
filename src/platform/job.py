"""this module contains the Job class"""

from __future__ import annotations

import asyncio
from collections import Counter
import concurrent.futures
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Optional, Protocol

try:
    from beartype.typing import Callable
except ImportError:
    from typing import Callable  # fallback for older versions
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

# Mapping from tool_key to (viz_func_name, name_func_name) tuples
_TOOL_FUNC_MAP = {
    "deeporigin.bulk-docking": ("_viz_func_docking", "_name_func_docking"),
    "deeporigin.abfe-end-to-end": ("_viz_func_abfe", "_name_func_abfe"),
    "deeporigin.rbfe-end-to-end": ("_viz_func_rbfe", "_name_func_rbfe"),
}


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
    _parse_func: Optional[JobFunc] = None

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

    @beartype
    def _extract_display_data(
        self,
    ) -> dict[str, str | Optional[str] | Optional[int]]:
        """Extract display data from a job for rendering.

        This method extracts common display fields from a job including job ID,
        resource ID, status, humanized started_at time, and running time.

        Returns:
            Dictionary containing:
                - job_id: The job's execution ID (str)
                - resource_id: The resource ID if available, None otherwise
                - status: The job status if available, None otherwise
                - started_at: Humanized time string (e.g., "2 hours ago") if available, None otherwise
                - running_time: Running time in minutes if available, None otherwise
        """
        resource_id = None
        if self._attributes is not None:
            resource_id = self._attributes.get("resourceId")

        started_at = None
        if (
            self._attributes is not None
            and self._attributes.get("startedAt") is not None
        ):
            dt = parser.isoparse(self._attributes["startedAt"]).astimezone(timezone.utc)
            now = datetime.now(timezone.utc)
            started_at = humanize.naturaltime(now - dt)

        running_time = self._get_running_time()

        return {
            "job_id": self._id,
            "resource_id": resource_id,
            "status": self.status,
            "started_at": started_at,
            "running_time": running_time,
        }

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
    def _get_status_html(self) -> str:
        """Get status HTML based on job status and tool.

        Returns:
            HTML string for the status visualization.
        """
        # Handle "Quoted" status with custom message
        if self.status == "Quoted":
            return job_viz_functions._viz_func_quoted(self)

        # Determine visualization function based on tool key
        tool = self._attributes.get("tool") if self._attributes else None
        tool_key = tool.get("key") if isinstance(tool, dict) and "key" in tool else None

        if not tool_key:
            return "No visualization function available for this tool."

        # Look up function in mapping
        func_names = _TOOL_FUNC_MAP.get(tool_key)
        if not func_names:
            return f"No visualization function available for tool '{tool_key}'."

        viz_func_name, _ = func_names

        try:
            viz_func = getattr(job_viz_functions, viz_func_name)
            return viz_func(self)
        except Exception as e:
            return f"Error rendering visualization for tool '{tool_key}': {e}"

    @beartype
    def _get_card_title(self) -> str:
        """Get card title based on job status and tool.

        Returns:
            Card title string.
        """
        try:
            # Determine name function based on tool key
            tool = self._attributes.get("tool") if self._attributes else None
            tool_key = (
                tool.get("key") if isinstance(tool, dict) and "key" in tool else None
            )

            # Look up function in mapping
            func_names = _TOOL_FUNC_MAP.get(tool_key)

            _, name_func_name = func_names
            name_func = getattr(job_viz_functions, name_func_name)
            return name_func(self)
        except Exception:
            # Fallback to generic title if name function fails
            return "Job"

    def _render_view(
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

        status_html = self._get_status_html()
        card_title = self._get_card_title()

        display_data = self._extract_display_data()

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
        template_vars = {
            "status_html": status_html,
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "outputs_json": json.dumps(outputs, indent=2) if outputs else "{}",
            "inputs_json": json.dumps(inputs, indent=2) if inputs else "{}",
            "inputs_json_viewer": inputs_json_viewer,
            "outputs_json_viewer": outputs_json_viewer,
            "billing_json_viewer": billing_json_viewer,
            "job_id": display_data["job_id"],
            "resource_id": display_data["resource_id"],
            "status": display_data["status"],
            "started_at": display_data["started_at"],
            "running_time": display_data["running_time"],
            "card_title": card_title,
            "unique_id": str(uuid.uuid4()),
            "will_auto_update": will_auto_update,
            "is_multiple": False,  # Single job mode
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
        rendered_html = self._render_view()
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

                        html = self._render_view(will_auto_update=True)
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
                        final_html = self._render_view(will_auto_update=False)
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

        return self._render_view()

    def cancel(self) -> None:
        """Cancel the job being tracked by this instance.

        This method sends a cancellation request for the job ID tracked by this instance
        using the utils.cancel_runs function.

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

    def __init__(self, jobs: list[Job]):
        """Initialize a JobList with a list of Job objects.

        Args:
            jobs: A list of Job objects.
        """
        self.jobs = jobs
        self._task = None
        self._display_id: Optional[str] = None
        self._last_html: Optional[str] = None

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
        return self._render_view(will_auto_update=False)

    @property
    def status(self) -> dict[str, int]:
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

    def sync(self, max_workers: int = 4):
        """Synchronize all jobs in the list in parallel.

        This method updates the internal state of all jobs by fetching the latest
        status and progress report for each job ID in parallel.

        Args:
            max_workers: The maximum number of threads to use for parallel execution.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(job.sync) for job in self.jobs]
            concurrent.futures.wait(futures)

    def show(self):
        """Display the job list view in a Jupyter notebook.

        This method renders the job list view and displays it in a Jupyter notebook.
        """
        rendered_html = self._render_view()
        display(HTML(rendered_html))

    def watch(self, *, interval: float = 5.0):
        """Start monitoring job list progress in real-time.

        This method initiates a background task that periodically updates
        and displays the status of all jobs in the list. It will automatically
        stop when all jobs reach a terminal state (Succeeded, Failed, etc.).
        If all jobs are already in terminal states, it will display a message
        and show the current state once.
        """
        # Enable nested event loops for Jupyter
        import nest_asyncio

        nest_asyncio.apply()

        # Check if all jobs are in terminal states
        all_terminal = all(
            job.status in TERMINAL_STATES if job.status else False for job in self.jobs
        )
        if all_terminal:
            display(
                HTML(
                    "<div style='color: gray;'>All jobs are in terminal states. This display will not update.</div>"
                )
            )
            self.show()
            return

        # Stop any existing task before starting a new one
        self.stop_watching()

        # for reasons i don't understand, removing this breaks the display rendering
        # when we do job_list.watch()
        initial_html = HTML("<div style='color: gray;'>Initializing...</div>")
        display_id = str(uuid.uuid4())
        self._display_id = display_id
        display(initial_html, display_id=display_id)

        async def update_progress_report():
            """Update and display job list progress at regular intervals.

            This coroutine runs in the background, updating the display
            with the latest status of all jobs every `interval` seconds.
            It automatically stops when all jobs reach terminal states.
            """
            try:
                while True:
                    try:
                        # Run sync in a worker thread without timeout to avoid the timeout issue
                        await asyncio.to_thread(self.sync)

                        html = self._render_view(will_auto_update=True)
                        update_display(HTML(html), display_id=self._display_id)
                        self._last_html = html

                        # Check if all jobs are in terminal states
                        all_terminal = all(
                            job.status in TERMINAL_STATES if job.status else False
                            for job in self.jobs
                        )
                        if all_terminal:
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

                    # Always sleep before next attempt
                    await asyncio.sleep(interval)
            finally:
                # Perform a final non-blocking refresh and render to clear spinner
                if self._display_id is not None:
                    try:
                        await asyncio.to_thread(self.sync)
                    except Exception:
                        pass
                    try:
                        final_html = self._render_view(will_auto_update=False)
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
        It is called automatically when all jobs reach terminal states,
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

    @beartype
    def _render_view(
        self,
        *,
        will_auto_update: bool = False,
        notebook_environment: Optional[str] = None,
    ) -> str:
        """Render a widget view for the JobList showing all jobs in a table.

        This method renders and displays the current state of all jobs in the list
        using the job_jupyter.html template with multiple rows in the details table.

        Args:
            will_auto_update: Whether the widget should auto-update.
            notebook_environment: The notebook environment (jupyter, marimo, etc.).

        Returns:
            HTML string for the job list widget.
        """
        from deeporigin.utils.notebook import get_notebook_environment

        if notebook_environment is None:
            notebook_environment = get_notebook_environment()

        if notebook_environment == "jupyter":
            template = env.get_template("job_jupyter.html")
        else:
            template = env.get_template("job.html")

        # Collect data from all jobs
        job_ids: list[str] = []
        resource_ids: list[Optional[str]] = []
        statuses: list[Optional[str]] = []
        started_ats: list[Optional[str]] = []
        running_times: list[Optional[str]] = []

        for job in self.jobs:
            display_data = job._extract_display_data()
            job_ids.append(display_data["job_id"])
            resource_ids.append(display_data["resource_id"])
            statuses.append(display_data["status"])
            started_ats.append(display_data["started_at"])
            running_time = display_data["running_time"]
            running_times.append(
                f"{running_time} minutes" if running_time is not None else None
            )

        # Check if all jobs are in "Quoted" state
        num_jobs = len(self.jobs)
        all_quoted = (
            all(job.status == "Quoted" for job in self.jobs if job.status is not None)
            and num_jobs > 0
        )

        # Check if all jobs have the same tool key (extract this early for use in card title)
        tool_keys = []
        for job in self.jobs:
            tool = job._attributes.get("tool") if job._attributes else None
            tool_key = (
                tool.get("key") if isinstance(tool, dict) and "key" in tool else None
            )
            tool_keys.append(tool_key)

        # Check if all jobs have the same tool key (and it's not None)
        unique_tool_keys = {key for key in tool_keys if key is not None}
        all_same_tool = len(unique_tool_keys) == 1 and None not in tool_keys
        common_tool_key = unique_tool_keys.pop() if all_same_tool else None

        if all_quoted:
            # Use quoted status visualization
            status_html = job_viz_functions._viz_func_quoted(self)
        else:
            if all_same_tool:
                tool_key = common_tool_key
                # Use tool-specific viz function for bulk-docking
                if tool_key == tool_mapper["Docking"]:
                    try:
                        status_html = job_viz_functions._viz_func_docking(self)
                    except Exception as e:
                        # Fall back to generic status HTML if viz function fails
                        status_breakdown = self.status
                        status_items = []
                        for status, count in sorted(status_breakdown.items()):
                            status_items.append(f"<strong>{status}</strong>: {count}")
                        status_str = (
                            ", ".join(status_items)
                            if status_items
                            else "No status information"
                        )
                        status_html = (
                            f"<p><strong>{num_jobs}</strong> job(s) in this list</p>"
                            f"<p>Status breakdown: {status_str}</p>"
                            f"<p>See the Details tab for individual job information.</p>"
                            f"<p>Error rendering tool-specific visualization: {e}</p>"
                        )
                else:
                    # For other tools, use generic status HTML
                    status_breakdown = self.status
                    status_items = []
                    for status, count in sorted(status_breakdown.items()):
                        status_items.append(f"<strong>{status}</strong>: {count}")
                    status_str = (
                        ", ".join(status_items)
                        if status_items
                        else "No status information"
                    )
                    status_html = (
                        f"<p><strong>{num_jobs}</strong> job(s) in this list</p>"
                        f"<p>Status breakdown: {status_str}</p>"
                        f"<p>See the Details tab for individual job information.</p>"
                    )
            else:
                # Jobs have different tool keys, use generic status HTML
                status_breakdown = self.status
                status_items = []
                for status, count in sorted(status_breakdown.items()):
                    status_items.append(f"<strong>{status}</strong>: {count}")
                status_str = (
                    ", ".join(status_items) if status_items else "No status information"
                )
                status_html = (
                    f"<p><strong>{num_jobs}</strong> job(s) in this list</p>"
                    f"<p>Status breakdown: {status_str}</p>"
                    f"<p>See the Details tab for individual job information.</p>"
                )

        # Get unique statuses for badge display (filter out None)
        unique_statuses = list({s for s in statuses if s is not None})

        # Card title - use tool-specific name function if all jobs have the same tool key
        if all_same_tool and common_tool_key:
            try:
                # Look up name function in mapping
                func_names = _TOOL_FUNC_MAP.get(common_tool_key)
                if func_names:
                    _, name_func_name = func_names
                    name_func = getattr(job_viz_functions, name_func_name)
                    # Pass JobList to name function so it can aggregate across all jobs
                    tool_specific_name = name_func(self)
                    card_title = f"{tool_specific_name} ({num_jobs} jobs)"
                else:
                    card_title = f"Job List ({num_jobs} jobs)"
            except Exception:
                # Fallback to generic title if name function fails
                card_title = f"Job List ({num_jobs} jobs)"
        else:
            card_title = f"Job List ({num_jobs} jobs)"

        # For inputs/outputs/billing, create combined JSON viewers
        # Collect all inputs/outputs/billing data
        all_inputs = {}
        all_outputs = {}
        all_billing = {}

        for job in self.jobs:
            job_id = job._id
            if job._attributes:
                inputs = job._attributes.get("userInputs")
                if inputs:
                    all_inputs[job_id] = (
                        inputs.to_dict() if hasattr(inputs, "to_dict") else inputs
                    )

                outputs = job._attributes.get("userOutputs")
                if outputs:
                    all_outputs[job_id] = (
                        outputs.to_dict() if hasattr(outputs, "to_dict") else outputs
                    )

                # Organize billing data by job ID
                billing_transaction = job._attributes.get("billingTransaction")
                quotation_result = job._attributes.get("quotationResult")
                if billing_transaction or quotation_result:
                    all_billing[job_id] = {
                        "billingTransaction": billing_transaction,
                        "quotationResult": quotation_result,
                    }

        # Generate JSON viewers
        inputs_json_viewer = self._render_json_viewer(all_inputs)
        outputs_json_viewer = self._render_json_viewer(all_outputs)
        billing_json_viewer = self._render_json_viewer(all_billing)

        # Prepare template variables
        template_vars = {
            "status_html": status_html,
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "outputs_json": json.dumps(all_outputs, indent=2) if all_outputs else "{}",
            "inputs_json": json.dumps(all_inputs, indent=2) if all_inputs else "{}",
            "inputs_json_viewer": inputs_json_viewer,
            "outputs_json_viewer": outputs_json_viewer,
            "billing_json_viewer": billing_json_viewer,
            "job_id": job_ids,  # List of job IDs
            "resource_id": resource_ids,  # List of resource IDs
            "status": statuses,  # List of statuses
            "started_at": started_ats,  # List of started_at strings
            "running_time": running_times,  # List of running_time strings
            "card_title": card_title,
            "unique_id": str(uuid.uuid4()),
            "will_auto_update": will_auto_update,
            "is_multiple": True,  # Multiple jobs mode
            "unique_statuses": unique_statuses,  # Unique statuses for badge display
        }

        # Determine auto-update behavior - only auto-update if any job is not in terminal state
        all_terminal = all(
            job.status in TERMINAL_STATES if job.status else False for job in self.jobs
        )
        if all_terminal:
            template_vars["will_auto_update"] = False

        # For progress reports, combine all
        all_progress_reports = []
        for job in self.jobs:
            progress_report = (
                job._attributes.get("progressReport") if job._attributes else None
            )
            if progress_report:
                all_progress_reports.append(progress_report)

        try:
            if all_progress_reports:
                # Try to parse each as JSON
                parsed_reports = []
                for report in all_progress_reports:
                    try:
                        parsed_reports.append(json.loads(str(report)))
                    except Exception:
                        parsed_reports.append(str(report))
                template_vars["raw_progress_json"] = json.dumps(
                    parsed_reports, indent=2
                )
            else:
                template_vars["raw_progress_json"] = "[]"
        except Exception:
            template_vars["raw_progress_json"] = (
                json.dumps([str(r) for r in all_progress_reports], indent=2)
                if all_progress_reports
                else "[]"
            )

        # Render the template
        return template.render(**template_vars)

    @beartype
    def _render_json_viewer(self, obj: dict) -> str:
        """Create an interactive JSON viewer HTML snippet for the given dictionary.

        This method generates HTML and JavaScript code that renders the provided
        dictionary as an interactive JSON viewer in a web environment (e.g., Jupyter notebook).
        It uses the @textea/json-viewer library via CDN to display the JSON data.

        Args:
            obj: The dictionary to display in the JSON viewer.

        Returns:
            HTML and JavaScript code to render the interactive JSON viewer.
        """
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
    def filter(
        self,
        *,
        status: Optional[str | list[str] | set[str]] = None,
        tool_key: Optional[str] = None,
        tool_version: Optional[str] = None,
        require_metadata: bool = False,
        predicate: Optional[Callable[[Job], bool]] = None,
        **kwargs: Any,
    ) -> "JobList":
        """Filter jobs by status, tool attributes, other attributes, or custom predicate.

        This method returns a new JobList containing only jobs that match the specified
        criteria. Multiple filters can be combined - keyword arguments are applied
        first (with AND logic), then the predicate function is applied if provided.

        Args:
            status: Filter by job status. Can be a single status string (e.g., "Succeeded"),
                or a list/set of statuses (e.g., ["Succeeded", "Running", "Queued"]).
                Checks against job.status property.
            tool_key: Filter by tool key (e.g., "deeporigin.docking", "deeporigin.abfe-end-to-end").
                Checks against ``job._attributes["tool"]["key"]``.
            tool_version: Filter by tool version (e.g., "1.0.0").
                Checks against ``job._attributes["tool"]["version"]``.
            require_metadata: If True, only include jobs that have metadata that exists and is not None.
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
                multiple_statuses = jobs.filter(status=["Succeeded", "Running", "Queued"])

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
            if isinstance(status, str):
                filtered = [job for job in filtered if job.status == status]
            else:
                # Convert set to list for consistent handling
                status_list = list(status) if isinstance(status, set) else status
                filtered = [job for job in filtered if job.status in status_list]

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

        # Apply metadata requirement filter
        if require_metadata:
            filtered = [
                job
                for job in filtered
                if job._attributes and job._attributes.get("metadata") is not None
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

    def to_dataframe(
        self,
        *,
        include_metadata: bool = False,
        include_inputs: bool = False,
        include_outputs: bool = False,
        resolve_user_names: bool = False,
        client: Optional[DeepOriginClient] = None,
    ) -> pd.DataFrame:
        """Convert the JobList to a pandas DataFrame.

        Extracts data from each job's _attributes dictionary and creates a DataFrame
        with the default columns: id, created_at, resource_id, completed_at, started_at,
        status, tool_key, tool_version, user_name, and run_duration_minutes.

        Args:
            include_metadata: If True, include metadata column in the DataFrame.
            include_inputs: If True, include user_inputs column in the DataFrame.
            include_outputs: If True, include user_outputs column in the DataFrame.
            resolve_user_names: If True, resolve user IDs to user names. Requires
                fetching users from the API.
            client: Optional client for API calls. Required if resolve_user_names is True.

        Returns:
            A pandas DataFrame with one row per job.
        """
        # Resolve user names if requested
        user_id_to_name: Optional[dict[str, str]] = None
        if resolve_user_names:
            if client is None:
                client = DeepOriginClient.get()
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
            "created_at": [],
            "resource_id": [],
            "completed_at": [],
            "started_at": [],
            "status": [],
            "tool_key": [],
            "tool_version": [],
            "user_name": [],
            "run_duration_minutes": [],
        }

        if include_metadata:
            data["metadata"] = []

        if include_inputs:
            data["user_inputs"] = []

        if include_outputs:
            data["user_outputs"] = []

        for job in self.jobs:
            attributes = job._attributes if job._attributes else {}

            # Add basic fields
            data["id"].append(attributes.get("executionId"))
            data["created_at"].append(attributes.get("createdAt"))
            data["resource_id"].append(attributes.get("resourceId"))
            data["completed_at"].append(attributes.get("completedAt"))
            data["started_at"].append(attributes.get("startedAt"))
            data["status"].append(attributes.get("status"))

            # Extract tool.key and tool.version from tool dict
            tool = attributes.get("tool")
            if isinstance(tool, dict):
                data["tool_key"].append(tool.get("key"))
                data["tool_version"].append(tool.get("version"))
            else:
                data["tool_key"].append(None)
                data["tool_version"].append(None)

            # Handle user name
            user_id = attributes.get("createdBy", "Unknown")
            if resolve_user_names and user_id_to_name is not None:
                data["user_name"].append(user_id_to_name.get(user_id, "Unknown"))
            else:
                data["user_name"].append(user_id)

            # Calculate run duration in minutes
            completed_at = attributes.get("completedAt")
            started_at = attributes.get("startedAt")
            if completed_at and started_at:
                start = parser.isoparse(started_at)
                end = parser.isoparse(completed_at)
                duration = round((end - start).total_seconds() / 60)
                data["run_duration_minutes"].append(duration)
            else:
                data["run_duration_minutes"].append(None)

            if include_metadata:
                data["metadata"].append(attributes.get("metadata"))

            if include_inputs:
                user_inputs = attributes.get("userInputs", {})
                data["user_inputs"].append(user_inputs)

            if include_outputs:
                data["user_outputs"].append(attributes.get("userOutputs", {}))

        # Create DataFrame
        df = pd.DataFrame(data)

        # Convert datetime columns
        datetime_cols = ["created_at", "completed_at", "started_at"]
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
        all_dtos: list[dict] = []

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
        ids: list[str],
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
        dtos: list[dict],
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
