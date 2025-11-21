"""helper module to parse progress and render progress for first party tools"""

import json
import os

from beartype import beartype


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
        inputs = (
            single_job._attributes.get("userInputs") if single_job._attributes else None
        )
        if inputs and "smiles_list" in inputs:
            total_ligands += len(inputs["smiles_list"])

        data = (
            single_job._attributes.get("progressReport")
            if single_job._attributes
            else None
        )
        if data is not None:
            total_docked += data.count("ligand docked")
            total_failed += data.count("ligand failed")

        running_time = single_job._get_running_time()
        if running_time is not None:
            total_running_time += running_time

    speed = total_docked / total_running_time if total_running_time > 0 else 0

    from deeporigin.utils.notebook import render_progress_bar

    return render_progress_bar(
        completed=total_docked,
        total=total_ligands,
        failed=total_failed,
        body_text=f"Average speed: {speed:.2f} dockings/minute",
    )


@beartype
def _name_func_docking(job) -> str:
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
    for single_job in jobs_list:
        inputs = (
            single_job._attributes.get("userInputs") if single_job._attributes else None
        )
        if inputs and "smiles_list" in inputs:
            unique_smiles.update(inputs["smiles_list"])
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


@beartype
def _name_func_abfe(job) -> str:
    """utility function to name a job using inputs to that job"""
    try:
        metadata = job._attributes.get("metadata") if job._attributes else None
        if metadata and "protein_name" in metadata and "ligand_name" in metadata:
            return f"ABFE run using <code>{metadata['protein_name']}</code> and <code>{metadata['ligand_name']}</code>"
        return "ABFE run"
    except Exception:
        return "ABFE run"


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
