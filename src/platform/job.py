"""this module contains the Job class"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Optional, Protocol
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

            # Quick and dirty logging for analysis - append progressReport to file
            try:
                progress_data = json.loads(result["progressReport"])
            except Exception:
                progress_data = result["progressReport"]

            log_file = Path(f"{self._id}.txt")
            with open(log_file, "a") as f:
                f.write(json.dumps(progress_data, indent=2))
                f.write("\n\n")

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

    def watch(self):
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
            with the latest job status and progress every 5 seconds.
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
                    await asyncio.sleep(5)
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
