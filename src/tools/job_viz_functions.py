"""helper module to parse progress and render progress for first party tools"""

import json
import os

from beartype import beartype


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

    if job._progress_report is None:
        return dict.fromkeys(steps, "NotStarted")

    try:
        data = job._progress_report

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

        status_value = job._status

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
        if job._status == "Failed":
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
    metadata = job._metadata
    report = job._progress_report

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
    if job._progress_report:
        try:
            progress_data = json.loads(job._progress_report)
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
    if job._status == "Failed" and progress_data:
        error_msg = progress_data.get("error_msg", "")
        details_html += f"""
        <div style="margin-top: 15px; padding: 10px; background-color: #ff7f7f; border-radius: 4px; color: black;">
            <strong>Error:</strong> {error_msg if error_msg else "Job failed"}
        </div>
        """

    return flowchart_html + details_html


def _viz_func_docking(job) -> str:
    """Render progress visualization for a docking job."""

    data = job._progress_report

    total_ligands = len(job._inputs["smiles_list"]) if job._inputs else 0
    total_docked = 0
    total_failed = 0

    if data is not None:
        total_docked += data.count("ligand docked")
        total_failed += data.count("ligand failed")

    total_running_time = job._get_running_time() or 0
    speed = total_docked / total_running_time if total_running_time > 0 else 0

    from deeporigin.utils.notebook import render_progress_bar

    return render_progress_bar(
        completed=total_docked,
        total=total_ligands,
        failed=total_failed,
        title="Docking Progress",
        body_text=f"Average speed: {speed:.2f} dockings/minute",
    )


@beartype
def _name_func_docking(job) -> str:
    """Generate a name for a docking job."""

    unique_smiles = set()
    if job._inputs:
        unique_smiles.update(job._inputs["smiles_list"])
    num_ligands = len(unique_smiles)

    protein_file = (
        os.path.basename(job._metadata["protein_file"])
        if job._metadata
        else "Unknown protein"
    )

    return f"Docking <code>{protein_file}</code> to {num_ligands} ligands."


@beartype
def _name_func_abfe(job) -> str:
    """utility function to name a job using inputs to that job"""
    try:
        return f"ABFE run using <code>{job._metadata['protein_name']}</code> and <code>{job._metadata['ligand_name']}</code>"
    except Exception:
        return "ABFE run"


@beartype
def _name_func_rbfe(job) -> str:
    """utility function to name a job using inputs to that job"""

    try:
        # For single job, we always have single ligand pair
        return f"RBFE run using <code>{job._metadata['protein_file']}</code> and <code>{job._metadata['ligand_file']}</code>"
    except Exception:
        return "RBFE run"
