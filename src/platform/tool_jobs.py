"""Tool execution job tracking: ``Job`` and ``JobList`` for the platform tools API."""

from __future__ import annotations

import asyncio
from collections import Counter
import concurrent.futures
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Optional, Protocol, Self
import uuid

from beartype import beartype
from beartype.typing import Callable
from dateutil import parser
import humanize
from IPython.display import HTML, display, update_display
from jinja2 import Environment, FileSystemLoader
import pandas as pd

from deeporigin.drug_discovery.constants import tool_mapper
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TERMINAL_STATES
from deeporigin.utils.env import elapsed_minutes, get_bool_env
from deeporigin.utils.notebook import render_progress_bar

# Job visualization helpers (inlined from former job_viz_functions module)


def _viz_func_quoted(job_or_jobs) -> str:
    """Render HTML for jobs in Quoted state.

    Args:
        job_or_jobs: Either a single Job instance, a JobList instance, or a list of Job instances.
            If multiple jobs, all must be in "Quoted" state.

    Returns:
        HTML string for the quoted status visualization.
    """
    # Convert to a list of jobs
    if hasattr(job_or_jobs, "jobs"):
        jobs_list = job_or_jobs.jobs
    elif isinstance(job_or_jobs, list):
        jobs_list = job_or_jobs
    else:
        jobs_list = [job_or_jobs]

    # Sum estimated costs across all jobs
    total_cost = 0.0
    costs_found = False

    for job in jobs_list:
        quotation_result = (
            job._attributes.get("quotationResult") if job._attributes else None
        )
        if quotation_result:
            try:
                estimated_cost = quotation_result["successfulQuotations"][0][
                    "priceTotal"
                ]
                total_cost += estimated_cost
                costs_found = True
            except (AttributeError, IndexError, KeyError, TypeError):
                pass

    # Generate HTML
    if costs_found:
        num_jobs = len(jobs_list)
        if num_jobs == 1:
            status_html = (
                "<h3>Job Quoted</h3>"
                f"<p>This job has been quoted. It is estimated to cost <strong>${round(total_cost)}</strong>. "
                "For details look at the Billing tab. To approve and start the run, call the "
                "<code style='font-family: monospace; background-color: #f5f5f5; padding: 2px 4px; border-radius: 3px;'>confirm()</code> method.</p>"
            )
        else:
            status_html = (
                "<h3>Jobs Quoted</h3>"
                f"<p>All {num_jobs} jobs have been quoted. The total estimated cost is <strong>${round(total_cost)}</strong>. "
                "For details look at the Billing tab. To approve and start the runs, call the "
                "<code style='font-family: monospace; background-color: #f5f5f5; padding: 2px 4px; border-radius: 3px;'>confirm()</code> method.</p>"
            )
    else:
        num_jobs = len(jobs_list)
        if num_jobs == 1:
            status_html = (
                "<h3>Job Quoted</h3>"
                "<p>This job has been quoted. For details look at the Billing tab. To approve and start the run, call the "
                "<code style='font-family: monospace; background-color: #f5f5f5; padding: 2px 4px; border-radius: 3px;'>confirm()</code> method.</p>"
            )
        else:
            status_html = (
                "<h3>Jobs Quoted</h3>"
                f"<p>All {num_jobs} jobs have been quoted. For details look at the Billing tab. To approve and start the runs, call the "
                "<code style='font-family: monospace; background-color: #f5f5f5; padding: 2px 4px; border-radius: 3px;'>confirm()</code> method.</p>"
            )

    return status_html


def _abfe_parse_progress(job) -> dict:
    """parse progress from a ABFE job"""

    steps = [
        "init",
        "complex",
        "ligand",
        "simple_md",
        "solvation",
        "binding",
        "delta_g",
    ]

    progress_report = job._attributes.get("progressReport") if job._attributes else None
    if progress_report is None:
        return dict.fromkeys(steps, "NotStarted")

    try:
        data = progress_report

        if data is None:
            progress = dict.fromkeys(steps, "NotStarted")
            progress["init"] = "Running"
            return progress
        else:
            data = json.loads(data)

        if "cmd" in data and data["cmd"] == "FEP Results":
            return dict.fromkeys(steps, "Succeeded")

        if "status" in data and data["status"] == "Initiating":
            progress = dict.fromkeys(steps, "NotStarted")
            progress["init"] = "Running"
            return progress

        status_value = job.status

        # If the overall status is Succeeded, return a dictionary with every key set to "Succeeded".
        if status_value == "Succeeded":
            return dict.fromkeys(steps, "Succeeded")

        current_step = data["run_name"]

        # Validate the input step
        if current_step not in steps:
            raise ValueError(
                f"Invalid process step provided: {current_step}. "
                f"Valid steps are: {', '.join(steps)}."
            )

        progress = {}
        for step in steps:
            if step == current_step:
                progress[step] = "Running"
                # Once we hit the current step, stop processing further steps.
                break
            else:
                progress[step] = "Succeeded"

        # if the job failed, mark the step that is running as failed
        if job.status == "Failed":
            progress[current_step] = "Failed"

    except Exception:
        progress = dict.fromkeys(steps, "Indeterminate")
        progress["init"] = "Indeterminate"

    return progress


@beartype
def _viz_func_rbfe(job) -> str:
    """
    Render HTML for a Mermaid diagram where each node is drawn as a rounded rectangle
    with a color indicating its status.
    """
    import json

    # For single job, we have single metadata and progress report
    metadata = job._attributes.get("metadata") if job._attributes else None
    report = job._attributes.get("progressReport") if job._attributes else None

    ligand1 = (
        metadata.get("ligand1_file", "Unknown ligand") if metadata else "Unknown ligand"
    )
    ligand2 = (
        metadata.get("ligand2_file", "Unknown ligand") if metadata else "Unknown ligand"
    )

    if report is None:
        step = ""
        sub_step = ""
    else:
        data = json.loads(report)
        step = data.get("cmd", "")
        sub_step = data.get("sub_step", "")

    import pandas as pd

    df = pd.DataFrame(
        {
            "ligand1": [ligand1],
            "ligand2": [ligand2],
            "steps": [step],
            "sub_steps": [sub_step],
        }
    )
    return df.to_html()


@beartype
def _viz_func_abfe(job) -> str:
    """
    Render HTML for ABFE job progress visualization.

    Shows a simple text flowchart with three high-level steps:
    - Initializing
    - Solvation FEP
    - Binding FEP

    For Solvation FEP and Binding FEP, shows sub-step details and a Bootstrap progress bar.
    When the job completes successfully (cmd == "FEP Results"), shows a success message
    and the final delta G result.
    """

    # Parse the progress report
    progress_data = None
    progress_report = job._attributes.get("progressReport") if job._attributes else None
    if progress_report:
        try:
            progress_data = json.loads(progress_report)
        except (json.JSONDecodeError, TypeError):
            progress_data = None

    # Check if job is complete with FEP Results
    if progress_data and progress_data.get("cmd") == "FEP Results":
        total = progress_data.get("Total", "N/A")
        unit = progress_data.get("unit", "kcal/mol")
        success_html = f"""
        <div style="font-family: sans-serif; font-size: 18px; margin: 20px 0;">
            <div style="background-color: #90ee90; color: black; padding: 15px; border-radius: 4px; margin-bottom: 15px;">
                <strong>Job completed successfully.</strong>
            </div>
            <div style="padding: 15px; background-color: #f8f9fa; border-radius: 4px;">
                ΔG = {total} {unit}
            </div>
        </div>
        """
        return success_html

    # Determine current high-level step
    current_step = "initializing"
    if progress_data:
        cmd = progress_data.get("cmd", "")
        if cmd == "Solvation FEP":
            current_step = "solvation"
        elif cmd == "Binding FEP":
            current_step = "binding"
        elif cmd == "ABFE E2E" and progress_data.get("status") == "Initiating":
            current_step = "initializing"

    # Build the flowchart HTML
    flowchart_html = (
        '<div style="font-family: sans-serif; font-size: 18px; margin: 20px 0;">'
    )

    # Helper function to style a step
    def style_step(step_name: str, step_key: str) -> str:
        if current_step == step_key:
            return f'<span style="background-color: #87CEFA; color: black; padding: 8px 16px; border-radius: 4px; font-weight: bold;">{step_name}</span>'
        elif current_step == "solvation" and step_key == "initializing":
            return f'<span style="background-color: #90ee90; color: black; padding: 8px 16px; border-radius: 4px;">{step_name}</span>'
        elif current_step == "binding" and step_key in ["initializing", "solvation"]:
            return f'<span style="background-color: #90ee90; color: black; padding: 8px 16px; border-radius: 4px;">{step_name}</span>'
        else:
            return f'<span style="background-color: #cccccc; color: black; padding: 8px 16px; border-radius: 4px;">{step_name}</span>'

    flowchart_html += style_step("Initializing", "initializing")
    flowchart_html += ' <span style="margin: 0 10px;">→</span> '
    flowchart_html += style_step("Solvation FEP", "solvation")
    flowchart_html += ' <span style="margin: 0 10px;">→</span> '
    flowchart_html += style_step("Binding FEP", "binding")
    flowchart_html += "</div>"

    # Build details section for Solvation FEP or Binding FEP
    details_html = ""
    if current_step in ["solvation", "binding"] and progress_data:
        sub_step = progress_data.get("sub_step", "")
        if not sub_step:
            sub_step = "Initializing..."

        current_avg_step = progress_data.get("current_avg_step", -1.0)
        target_step = progress_data.get("target_step", -1)

        # Determine if we're initializing (no valid step data)
        is_initializing = current_avg_step < 0 or target_step < 0

        # Calculate progress percentage
        if not is_initializing and target_step > 0:
            progress_pct = min(100.0, max(0.0, (current_avg_step / target_step) * 100))
        else:
            progress_pct = 0.0

        # Build progress bar HTML
        progress_bar_class = (
            "progress-bar progress-bar-striped progress-bar-animated"
            if is_initializing
            else "progress-bar"
        )
        progress_bar_style = f"width: {progress_pct:.1f}%"

        step_info = ""
        if not is_initializing:
            step_info = f'<div style="margin-top: 5px; font-size: 14px; color: #666;">Step {current_avg_step:.0f} / {target_step:.0f}</div>'

        details_html = f"""
        <div style="margin-top: 20px; padding: 15px; background-color: #f8f9fa; border-radius: 4px;">
            <div style="margin-bottom: 10px;">
                <strong>Sub-step:</strong> {sub_step}
            </div>
            <div class="progress" style="height: 25px;">
                <div class="{progress_bar_class} bg-primary" role="progressbar"
                     style="{progress_bar_style}"
                     aria-valuenow="{progress_pct:.1f}"
                     aria-valuemin="0"
                     aria-valuemax="100">
                    {progress_pct:.1f}%
                </div>
            </div>
            {step_info}
        </div>
        """

    # Handle failed status
    if job.status == "Failed" and progress_data:
        error_msg = progress_data.get("error_msg", "")
        details_html += f"""
        <div style="margin-top: 15px; padding: 10px; background-color: #ff7f7f; border-radius: 4px; color: black;">
            <strong>Error:</strong> {error_msg if error_msg else "Job failed"}
        </div>
        """

    return flowchart_html + details_html


def _viz_func_docking(job) -> str:
    """Render progress visualization for a docking job or JobList.

    Args:
        job: Either a Job instance or a JobList instance. If JobList, sums
            total_docked and total_failed across all jobs.

    Returns:
        HTML string for the progress visualization.
    """
    # Convert to a list of jobs (works for both JobList and single Job)
    jobs_list = job.jobs if hasattr(job, "jobs") else [job]

    # Sum across all jobs
    total_ligands = 0
    total_docked = 0
    total_failed = 0
    total_running_time = 0

    for single_job in jobs_list:
        attrs = getattr(single_job, "_attributes", None) or {}
        user_inputs = attrs.get("userInputs") or {}
        ligands = user_inputs.get("ligands")
        if isinstance(ligands, list):
            total_ligands += len(ligands)
        else:
            smiles_list = user_inputs.get("smiles_list")
            if isinstance(smiles_list, list):
                total_ligands += len(smiles_list)

        data = (
            single_job._attributes.get("progressReport")
            if single_job._attributes
            else None
        )

        if data is None:
            continue

        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                continue

        if isinstance(data, dict):
            total_docked += len(data.get("docked", []))
            total_failed += len(data.get("failed", []))

        running_time = single_job._get_running_time()
        if running_time is not None:
            total_running_time += running_time

    speed = total_docked / total_running_time if total_running_time > 0 else 0

    return render_progress_bar(
        completed=total_docked,
        total=total_ligands,
        failed=total_failed,
        body_text=f"Average speed: {speed:.2f} dockings/minute",
    )


def _name_func_docking(job: "Job | JobList") -> str:
    """Generate a name for a docking job or JobList.

    Args:
        job: Either a Job instance or a JobList instance. If JobList, collects
            unique SMILES across all jobs.

    Returns:
        Name string for the docking job(s).
    """
    # Convert to a list of jobs (works for both JobList and single Job)
    jobs_list = job.jobs if hasattr(job, "jobs") else [job]

    # Collect unique SMILES across all jobs
    unique_smiles = set()
    for job in jobs_list:
        attrs = getattr(job, "_attributes", None) or {}
        user_inputs = attrs.get("userInputs") or {}
        ligands = user_inputs.get("ligands")
        if isinstance(ligands, list):
            unique_smiles.update(lig["smiles"] for lig in ligands if "smiles" in lig)
        else:
            smiles_list = user_inputs.get("smiles_list")
            if isinstance(smiles_list, list):
                unique_smiles.update(smiles_list)
    num_ligands = len(unique_smiles)

    # Get protein file from first job (should be the same across all jobs)
    first_job = jobs_list[0]
    metadata = first_job._attributes.get("metadata") if first_job._attributes else None
    protein_file = (
        os.path.basename(metadata["protein_file"])
        if metadata and "protein_file" in metadata
        else "Unknown protein"
    )

    return f"Docking <code>{protein_file}</code> to {num_ligands} ligands."


def _name_func_abfe(job: "Job | JobList") -> str:
    """Generate a name for an ABFE job or JobList.

    Args:
        job: Either a Job instance or a JobList instance. If JobList with a single job,
            uses that job's metadata. If JobList with multiple jobs, mentions the
            protein name and number of ligands.

    Returns:
        Name string for the ABFE job(s).
    """
    # Convert to a list of jobs (works for both JobList and single Job)
    jobs_list = job.jobs if hasattr(job, "jobs") else [job]

    # If single job, use existing logic
    if len(jobs_list) == 1:
        single_job = jobs_list[0]
        try:
            metadata = (
                single_job._attributes.get("metadata")
                if single_job._attributes
                else None
            )
            if metadata and "protein_name" in metadata and "ligand_name" in metadata:
                return f"ABFE run using <code>{metadata['protein_name']}</code> and <code>{metadata['ligand_name']}</code>"
            return "ABFE run"
        except Exception:
            return "ABFE run"

    # Multiple jobs: get protein name from first job and count ligands
    try:
        first_job = jobs_list[0]
        metadata = (
            first_job._attributes.get("metadata") if first_job._attributes else None
        )
        protein_name = (
            metadata.get("protein_name")
            if metadata and "protein_name" in metadata
            else "Unknown protein"
        )
        num_ligands = len(jobs_list)
        return f"ABFE run using <code>{protein_name}</code> for {num_ligands} ligands"
    except Exception:
        return f"ABFE run ({len(jobs_list)} jobs)"


@beartype
def _name_func_rbfe(job) -> str:
    """utility function to name a job using inputs to that job"""

    try:
        # For single job, we always have single ligand pair
        metadata = job._attributes.get("metadata") if job._attributes else None
        if metadata and "protein_file" in metadata and "ligand_file" in metadata:
            return f"RBFE run using <code>{metadata['protein_file']}</code> and <code>{metadata['ligand_file']}</code>"
        return "RBFE run"
    except Exception:
        return "RBFE run"


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


def _watch_blocking_impl(
    instance: "Job | JobList",
    *,
    interval: float,
    is_terminal: Callable[[], bool],
) -> None:
    """Shared blocking watch implementation.

    This function contains the common blocking loop logic used by both Job and
    JobList classes. It is separated from the class methods to avoid code
    duplication while allowing each class to define its own termination condition
    via the is_terminal callable.

    The core blocking loop logic (display initialization, polling loop, status syncing,
    HTML rendering, and cleanup) is identical for both Job and JobList. The only
    difference is how each class determines when monitoring should stop (single
    job terminal state vs. all jobs terminal states).

    Error handling: Transient errors during sync() or _render_view() are caught
    and displayed as error banners. The loop continues retrying until either:
    - The job(s) reach a terminal state (success)
    - Too many consecutive errors occur (default: 10), at which point monitoring
      stops to prevent infinite loops

    Args:
        instance: Job or JobList instance with sync(), _render_view(), etc. methods.
        interval: Polling interval in seconds.
        is_terminal: Callable that returns True when monitoring should stop.
            This allows each class (Job vs. JobList) to define its own
            termination logic without the shared implementation needing to know
            about class-specific internals.
    """
    # Stop any existing task before starting a new one
    instance.stop_watching()

    # Initialize display
    initial_html = HTML("<div style='color: gray;'>Initializing...</div>")
    display_id = str(uuid.uuid4())
    instance._display_id = display_id
    display(initial_html, display_id=display_id)

    consecutive_errors = 0
    max_consecutive_errors = 10

    try:
        while True:
            try:
                # Sync status synchronously
                instance.sync()

                html = instance._render_view(will_auto_update=False)
                update_display(HTML(html), display_id=instance._display_id)
                instance._last_html = html
                consecutive_errors = 0  # Reset error counter on success

                # Check if in terminal state
                if is_terminal():
                    break

            except Exception as e:
                consecutive_errors += 1
                # Show a transient error banner, but keep the loop alive
                banner = instance._compose_error_overlay_html(message=str(e))
                fallback = (
                    instance._last_html
                    or "<div style='color: gray;'>No data yet.</div>"
                )
                update_display(HTML(banner + fallback), display_id=instance._display_id)

                # Stop after too many consecutive errors to prevent infinite loops
                if consecutive_errors >= max_consecutive_errors:
                    error_msg = (
                        f"Stopped monitoring after {max_consecutive_errors} "
                        f"consecutive errors. Last error: {str(e)}"
                    )
                    final_banner = instance._compose_error_overlay_html(
                        message=error_msg
                    )
                    update_display(
                        HTML(final_banner + fallback),
                        display_id=instance._display_id,
                    )
                    break

            # Always sleep before next attempt
            time.sleep(interval)
    finally:
        # Perform a final refresh and render to clear spinner
        if instance._display_id is not None:
            try:
                instance.sync()
            except Exception:
                pass
            try:
                final_html = instance._render_view(will_auto_update=False)
                update_display(HTML(final_html), display_id=instance._display_id)
            except Exception:
                pass
            instance._display_id = None


def _watch_async_impl(
    instance: "Job | JobList",
    *,
    interval: float,
    is_terminal: Callable[[], bool],
) -> None:
    """Shared async watch implementation.

    Args:
        instance: Job or JobList instance with sync(), _render_view(), etc. methods.
        interval: Polling interval in seconds.
        is_terminal: Callable that returns True when monitoring should stop.
    """
    # Enable nested event loops for Jupyter
    import nest_asyncio

    nest_asyncio.apply()

    # Stop any existing task before starting a new one
    instance.stop_watching()

    # for reasons i don't understand, removing this breaks the display rendering
    # when we do job.watch() or job_list.watch()
    initial_html = HTML("<div style='color: gray;'>Initializing...</div>")
    display_id = str(uuid.uuid4())
    instance._display_id = display_id
    display(initial_html, display_id=display_id)

    async def update_progress_report():
        """Update and display progress at regular intervals.

        This coroutine runs in the background, updating the display
        with the latest status every `interval` seconds.
        It automatically stops when terminal state is reached.
        Stops after 10 consecutive errors to prevent infinite loops.
        """
        consecutive_errors = 0
        max_consecutive_errors = 10
        try:
            while True:
                try:
                    # Run sync in a worker thread without timeout to avoid the timeout issue
                    await asyncio.to_thread(instance.sync)

                    html = instance._render_view(will_auto_update=True)
                    update_display(HTML(html), display_id=instance._display_id)
                    instance._last_html = html
                    consecutive_errors = 0  # Reset error counter on success

                    # Check if in terminal state
                    if is_terminal():
                        break

                except Exception as e:
                    consecutive_errors += 1
                    # Show a transient error banner, but keep the task alive
                    banner = instance._compose_error_overlay_html(message=str(e))
                    fallback = (
                        instance._last_html
                        or "<div style='color: gray;'>No data yet.</div>"
                    )
                    update_display(
                        HTML(banner + fallback), display_id=instance._display_id
                    )

                    # Stop after too many consecutive errors to prevent infinite loops
                    if consecutive_errors >= max_consecutive_errors:
                        error_msg = f"Stopped monitoring after {max_consecutive_errors} consecutive errors. Last error: {str(e)}"
                        final_banner = instance._compose_error_overlay_html(
                            message=error_msg
                        )
                        update_display(
                            HTML(final_banner + fallback),
                            display_id=instance._display_id,
                        )
                        break

                # Always sleep before next attempt
                await asyncio.sleep(interval)
        finally:
            # Perform a final non-blocking refresh and render to clear spinner
            if instance._display_id is not None:
                try:
                    await asyncio.to_thread(instance.sync)
                except Exception:
                    pass
                try:
                    final_html = instance._render_view(will_auto_update=False)
                    update_display(HTML(final_html), display_id=instance._display_id)
                except Exception:
                    pass
                instance._display_id = None

    # Schedule the task using the current event loop
    try:
        loop = asyncio.get_event_loop()
        instance._task = loop.create_task(update_progress_report())
    except RuntimeError:
        # If no event loop is running, create a new one
        instance._task = asyncio.create_task(update_progress_report())


@dataclass
@beartype
class Job:
    """
    Represents a single computational job that can be monitored and managed.

    This class provides methods to track, visualize, and parse the status and progress of a job, with optional real-time updates (e.g., in Jupyter notebooks).

    Attributes:
        name (str): Name of the job.
    """

    name: str
    id: str

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
    ) -> Self:
        """Create a Job instance from a single ID.

        Args:
            id: Job ID to track.
            client: Optional client for API calls.

        Returns:
            A new Job instance with the given ID.
        """
        return cls(
            name="job",
            id=id,
            client=client,
        )

    @classmethod
    def from_dto(
        cls,
        dto: dict,
        *,
        client: Optional[DeepOriginClient] = None,
    ) -> Self:
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
            id=execution_id,
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
            self.client = DeepOriginClient()

        # use
        execution = self.client.executions.get(self.id)

        if execution:
            self._attributes = execution
            self.status = execution.get("status")

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

    def logs(self):
        """print the logs of the job, if any are available"""
        try:
            data = json.loads(self._attributes.get("progressReport"))
            logs = data.get("logs", [])
            logs = logs.split("\n")
            for log in logs:
                print(log)
        except Exception:
            print("No logs available")

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
            "job_id": self.id,
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

    def _get_status_html(self) -> str:
        """Get status HTML based on job status and tool.

        Returns:
            HTML string for the status visualization.
        """
        # Handle "Quoted" status with custom message
        if self.status == "Quoted":
            return _viz_func_quoted(self)

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
            viz_func = globals()[viz_func_name]
            return viz_func(self)
        except Exception as e:
            return f"Error rendering visualization for tool '{tool_key}': {e}"

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
            name_func = globals()[name_func_name]
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
        if self._is_terminal():
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

        If the JOB_WATCH_BLOCK environment variable is set to a truthy value,
        this method will block until the job reaches a terminal state.
        Otherwise, it returns immediately after starting the background task.
        """
        # Check if blocking mode is enabled
        should_block = get_bool_env("JOB_WATCH_BLOCK", default=False)

        # Check if there is any active job (not terminal state)
        if self._is_terminal():
            display(
                HTML(
                    "<div style='color: gray;'>No active job to monitor. This display will not update.</div>"
                )
            )
            self.show()
            return

        if should_block:
            # Blocking mode: use synchronous polling loop
            self._watch_blocking(interval=interval)
        else:
            # Non-blocking mode: use async background task
            self._watch_async(interval=interval)

    def _is_terminal(self) -> bool:
        """Check if the job is in a terminal state.

        Returns:
            True if the job status is in TERMINAL_STATES, False otherwise.
        """
        return self.status is not None and self.status in TERMINAL_STATES

    def _watch_blocking(self, *, interval: float = 5.0):
        """Blocking watch implementation using synchronous polling.

        This method blocks until the job reaches a terminal state, updating
        the display at regular intervals. Used when JOB_WATCH_BLOCK is set.

        Error handling: Transient errors during sync() or _render_view() are
        caught and displayed as error banners. The monitoring continues retrying
        until either the job reaches a terminal state or too many consecutive
        errors occur (default: 10), at which point monitoring stops to prevent
        infinite loops. This ensures robust behavior even when network issues or
        transient server problems occur.

        This is a thin wrapper around _watch_blocking_impl that provides
        Job-specific termination logic. The wrapper pattern allows us to:
        1. Share the common blocking loop implementation with JobList
        2. Keep termination logic explicit and close to the class definition
        3. Maintain encapsulation (the shared function doesn't need to know
           about Job-specific attributes like self.status)

        Args:
            interval: Polling interval in seconds. Defaults to 5.0.
        """
        _watch_blocking_impl(
            self,
            interval=interval,
            is_terminal=self._is_terminal,
        )

    def _watch_async(self, *, interval: float = 5.0):
        """Non-blocking watch implementation using async background task.

        This method starts a background task and returns immediately.
        Used for interactive Jupyter notebook usage.
        """
        _watch_async_impl(
            self,
            interval=interval,
            is_terminal=self._is_terminal,
        )

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
            execution_id=self.id,
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
                execution_id=self.id,
            )

            self.sync()

    def duplicate(self) -> Self:
        """Create a duplicate of this job by submitting a new execution with the same parameters.

        This method extracts the necessary fields from the current job's attributes
        (userOutputs, userInputs, and tool) and submits them as a new
        execution using the same tool key and version. The platform will fill in
        all other fields (executionId, status, timestamps, etc.).

        Duplicating a job submits a new execution using the same tool key and version, with approveAmount set to 0.
        The new execution will be in the "Quoted" state, and will need to be confirmed before it can be started.

        Returns:
            A new Job instance representing the duplicated execution.

        Raises:
            ValueError: If the job's attributes are missing or incomplete.
            DeepOriginException: If the tool execution fails.
        """
        if self.client is None:
            self.client = DeepOriginClient()

        if self._attributes is None:
            raise ValueError(
                "Cannot duplicate job: job attributes are not available. Try calling sync() first."
            )

        # Extract tool information
        tool = self._attributes.get("tool")
        if not isinstance(tool, dict):
            raise ValueError(
                "Cannot duplicate job: tool information is missing or invalid."
            )

        tool_key = tool.get("key")
        tool_version = tool.get("version")

        if not tool_key or not tool_version:
            raise ValueError(
                f"Cannot duplicate job: tool key or version is missing. "
                f"Found tool_key={tool_key}, tool_version={tool_version}"
            )

        # Build data dict with only the allowed fields
        data: dict[str, Any] = {}

        # Extract allowed fields if they exist
        if "userOutputs" in self._attributes:
            data["outputs"] = self._attributes["userOutputs"]
        if "userInputs" in self._attributes:
            data["inputs"] = self._attributes["userInputs"]
        if "metadata" in self._attributes:
            data["metadata"] = self._attributes["metadata"]

        # force approve amount to 0 because we don't want it to immediately run
        data["approveAmount"] = 0

        # Submit the new execution
        response_dto = self.client.executions.create(
            tool_key=tool_key,
            tool_version=tool_version,
            data=data,
        )

        # Create and return a new Job instance from the response DTO
        return Job.from_dto(response_dto, client=self.client)


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

    def logs(self):
        """Print the logs of all jobs in the list, if any are available.

        This method iteratively calls Job.logs() for every job in the JobList instance.
        """
        for i, job in enumerate(self.jobs):
            if len(self.jobs) > 1:
                print(f"\n--- Logs for Job {i + 1} (ID: {job.id}) ---")
            job.logs()

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

        If the JOB_WATCH_BLOCK environment variable is set to a truthy value,
        this method will block until all jobs reach terminal states.
        Otherwise, it returns immediately after starting the background task.
        """
        # Check if blocking mode is enabled
        should_block = get_bool_env("JOB_WATCH_BLOCK", default=False)

        # Check if all jobs are in terminal states
        if self._is_terminal():
            display(
                HTML(
                    "<div style='color: gray;'>All jobs are in terminal states. This display will not update.</div>"
                )
            )
            self.show()
            return

        if should_block:
            # Blocking mode: use synchronous polling loop
            self._watch_blocking(interval=interval)
        else:
            # Non-blocking mode: use async background task
            self._watch_async(interval=interval)

    def _is_terminal(self) -> bool:
        """Check if all jobs in the list are in terminal states.

        Returns:
            True if all jobs have status in TERMINAL_STATES, False otherwise.
        """
        return all(
            job.status in TERMINAL_STATES if job.status else False for job in self.jobs
        )

    def _watch_blocking(self, *, interval: float = 5.0):
        """Blocking watch implementation using synchronous polling.

        This method blocks until all jobs reach terminal states, updating
        the display at regular intervals. Used when JOB_WATCH_BLOCK is set.

        Error handling: Transient errors during sync() or _render_view() are
        caught and displayed as error banners. The monitoring continues retrying
        until either all jobs reach terminal states or too many consecutive
        errors occur (default: 10), at which point monitoring stops to prevent
        infinite loops. This ensures robust behavior even when network issues or
        transient server problems occur.

        This is a thin wrapper around _watch_blocking_impl that provides
        JobList-specific termination logic. The wrapper pattern allows us to:
        1. Share the common blocking loop implementation with Job
        2. Keep termination logic explicit and close to the class definition
        3. Maintain encapsulation (the shared function doesn't need to know
           about JobList-specific attributes like self.jobs)

        Args:
            interval: Polling interval in seconds. Defaults to 5.0.
        """
        _watch_blocking_impl(
            self,
            interval=interval,
            is_terminal=self._is_terminal,
        )

    def _watch_async(self, *, interval: float = 5.0):
        """Non-blocking watch implementation using async background task.

        This method starts a background task and returns immediately.
        Used for interactive Jupyter notebook usage.
        """
        _watch_async_impl(
            self,
            interval=interval,
            is_terminal=self._is_terminal,
        )

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
            status_html = _viz_func_quoted(self)
        else:
            if all_same_tool:
                tool_key = common_tool_key
                # Use tool-specific viz function for bulk-docking
                if tool_key == tool_mapper["Docking"]:
                    try:
                        status_html = _viz_func_docking(self)
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
                    name_func = globals()[name_func_name]
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
            job_id = job.id
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

    def filter(
        self,
        *,
        status: Optional[str | list[str] | set[str]] = None,
        tool_key: Optional[str] = None,
        tool_version: Optional[str] = None,
        require_metadata: bool = False,
        predicate: Optional[Callable[[Job], bool]] = None,
        **kwargs: Any,
    ) -> Self:
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
                client = DeepOriginClient()

            users = client.organizations.users()

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
        tool_key: Optional[str] = None,
        tool_version: Optional[str] = None,
        client: Optional[DeepOriginClient] = None,
    ) -> Self:
        """Fetch executions from the API and return a JobList.

        This method automatically handles pagination, fetching all pages if necessary
        and combining them into a single JobList.

        Args:
            page: Page number to start from (default 0). If None, starts from page 0.
            page_size: Page size of the pagination (max 10,000).
            order: Order of the pagination, e.g., "executionId? asc", "completedAt? desc".
            tool_key: Tool key to filter by.
            tool_version: Tool version to filter by.
            client: Optional client for API calls.

        Returns:
            A new JobList instance containing the fetched jobs.
        """
        if client is None:
            client = DeepOriginClient()

        # Start from page 0 if not specified
        current_page = page if page is not None else 0
        all_dtos: list[dict] = []

        while True:
            response = client.executions.list(
                page=current_page,
                page_size=page_size,
                order=order,
                tool_key=tool_key,
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

        # filter client side by tool_key and tool_version
        if tool_key is not None:
            all_dtos = [
                dto for dto in all_dtos if dto.get("tool", {}).get("key") == tool_key
            ]
        if tool_version is not None:
            all_dtos = [
                dto
                for dto in all_dtos
                if dto.get("tool", {}).get("version") == tool_version
            ]

        return cls.from_dtos(all_dtos, client=client)

    @classmethod
    def from_ids(
        cls,
        ids: list[str],
        *,
        client: Optional[DeepOriginClient] = None,
    ) -> Self:
        """Create a JobList from a list of job IDs.

        Args:
            ids: A list of job IDs.
            client: Optional client for API calls.

        Returns:
            A new JobList instance.
        """
        jobs = [Job.from_id(job_id, client=client) for job_id in ids]
        return cls(jobs)

    @classmethod
    def from_dtos(
        cls,
        dtos: list[dict],
        *,
        client: Optional[DeepOriginClient] = None,
    ) -> Self:
        """Create a JobList from a list of execution DTOs.

        Args:
            dtos: A list of execution DTOs.
            client: Optional client for API calls.

        Returns:
            A new JobList instance.
        """
        jobs = [Job.from_dto(dto, client=client) for dto in dtos]
        return cls(jobs)
