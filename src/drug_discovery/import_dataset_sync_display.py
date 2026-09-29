"""Notebook step progress for entity ``.sync()`` import-dataset flows."""

from __future__ import annotations

from dataclasses import dataclass, field
import html
from typing import Protocol
import uuid

from deeporigin.utils.constants import BOOTSTRAP_5_CSS_CDN_URL

# Served ``process_sdf`` + pose registration (``PoseSet.sync``).
POSE_REGISTRATION_STEPS: tuple[str, ...] = (
    "Prepare staging SDF",
    "Upload to workspace",
    "Run import-dataset",
    "Wait for data ingestion",
    "Resolve platform IDs",
)


def render_import_dataset_sync_progress_html(
    *,
    completed: int,
    total: int,
    status_label: str,
    detail: str = "",
    failed: bool = False,
) -> str:
    """Render a compact progress bar and one line of current status."""

    if total <= 0:
        total = 1
    completed = max(0, min(completed, total))
    pct = (completed / total) * 100.0
    if failed:
        pct = min(pct, 100.0)
    elif completed < total and not failed:
        # Show partial fill while the current step is in flight.
        pct = min(100.0, pct + (100.0 / total) * 0.35)

    pct_s = html.escape(f"{pct:.0f}", quote=True)
    esc_label = html.escape(status_label, quote=True)
    esc_detail = html.escape(detail.strip(), quote=True) if detail.strip() else ""
    detail_bit = f" · {esc_detail}" if esc_detail else ""

    if failed:
        status_line = f'<span class="text-danger">{esc_label}{detail_bit}</span>'
        bar_inner = (
            f'<div class="progress-bar bg-danger" style="width: {pct_s}%;"></div>'
        )
    elif completed >= total:
        status_line = f'<span class="text-success">Done</span>'
        bar_inner = f'<div class="progress-bar bg-success" style="width: 100%;"></div>'
    else:
        status_line = (
            f'<span class="spinner-border spinner-border-sm text-primary" '
            f'role="status" aria-hidden="true"></span>'
            f"<span>{esc_label}{detail_bit}</span>"
        )
        bar_inner = (
            '<div class="progress-bar progress-bar-striped progress-bar-animated" '
            f'style="width: {pct_s}%;"></div>'
        )

    uid = f"import_sync_{uuid.uuid4().hex}"
    return f"""<div id="{html.escape(uid, quote=True)}" class="do-import-sync-progress">
<link href="{html.escape(BOOTSTRAP_5_CSS_CDN_URL, quote=True)}" rel="stylesheet">
<div style="max-width: 18rem; font-size: 0.8125rem;">
<div class="progress" style="height: 6px;" role="progressbar"
aria-valuenow="{pct_s}" aria-valuemin="0" aria-valuemax="100">
{bar_inner}
</div>
<div class="d-flex align-items-center gap-2 mt-1 text-body-secondary">
{status_line}
</div>
</div>
</div>"""


class ImportDatasetSyncProgressReporter(Protocol):
    """Hook for import-dataset sync phases (no-op or live notebook UI)."""

    def start_step(self, index: int, *, detail: str = "") -> None:
        """Mark a step as in progress."""
        ...

    def finish_step(self, index: int, *, detail: str = "") -> None:
        """Mark a step as completed."""
        ...

    def set_execution_id(self, execution_id: str) -> None:
        """Record the platform workflow execution id (optional)."""
        ...

    def fail_step(self, index: int, *, message: str = "") -> None:
        """Mark a step as failed."""
        ...

    def close(self) -> None:
        """Finalize the progress UI."""
        ...


@dataclass
class NullImportDatasetSyncProgress:
    """No-op reporter for scripts and non-notebook environments."""

    def start_step(self, index: int, *, detail: str = "") -> None:
        """No-op."""

    def finish_step(self, index: int, *, detail: str = "") -> None:
        """No-op."""

    def set_execution_id(self, execution_id: str) -> None:
        """No-op."""

    def fail_step(self, index: int, *, message: str = "") -> None:
        """No-op."""

    def close(self) -> None:
        """No-op."""


@dataclass
class NotebookImportDatasetSyncProgress:
    """Live-updating compact progress in Jupyter via ``update_display``."""

    step_labels: tuple[str, ...]
    _completed: int = field(default=0, init=False)
    _status_label: str = field(default="", init=False)
    _detail: str = field(default="", init=False)
    _failed: bool = field(default=False, init=False)
    _display_id: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.step_labels:
            self._status_label = self.step_labels[0]

    @property
    def _total(self) -> int:
        return len(self.step_labels) or 1

    def _refresh(self) -> None:
        from IPython.display import HTML, display, update_display

        html_out = render_import_dataset_sync_progress_html(
            completed=self._completed,
            total=self._total,
            status_label=self._status_label,
            detail=self._detail,
            failed=self._failed,
        )
        if self._display_id is None:
            self._display_id = str(uuid.uuid4())
            display(HTML(html_out), display_id=self._display_id)
        else:
            update_display(HTML(html_out), display_id=self._display_id)

    def start_step(self, index: int, *, detail: str = "") -> None:
        """Show the given step as in progress."""
        if self._failed or index < 0 or index >= len(self.step_labels):
            return
        self._status_label = self.step_labels[index]
        self._detail = detail
        self._refresh()

    def finish_step(self, index: int, *, detail: str = "") -> None:
        """Advance completed count and refresh the bar."""
        if self._failed or index < 0 or index >= len(self.step_labels):
            return
        self._completed = max(self._completed, index + 1)
        if detail:
            self._detail = detail
        self._refresh()

    def set_execution_id(self, execution_id: str) -> None:
        """Execution id is not shown in the compact UI."""

    def fail_step(self, index: int, *, message: str = "") -> None:
        """Show failure state for the given step."""
        self._failed = True
        if 0 <= index < len(self.step_labels):
            self._status_label = self.step_labels[index]
        if message:
            self._detail = message
        self._refresh()

    def close(self) -> None:
        """Mark all steps complete unless already failed."""
        if self._failed:
            return
        self._completed = self._total
        self._detail = ""
        self._refresh()


# Served import-dataset (``LigandSet.sync`` SDF or small CSV).
LIGAND_SERVED_SYNC_STEPS: tuple[str, ...] = (
    "Prepare staging file",
    "Upload to workspace",
    "Run import-dataset",
    "Apply ligand IDs",
)

# Large SMILES CSV via workflow (``LigandSet.sync`` above served cap).
LIGAND_WORKFLOW_SYNC_STEPS: tuple[str, ...] = (
    "Prepare staging CSV",
    "Upload to workspace",
    "Start import-dataset workflow",
    "Wait for workflow",
    "Wait for data ingestion",
    "Resolve platform IDs",
)


def import_dataset_sync_progress(
    *,
    show_progress: bool | None,
    step_labels: tuple[str, ...],
) -> ImportDatasetSyncProgressReporter:
    """Return a notebook step UI when ``show_progress`` is true (default: Jupyter only)."""
    if show_progress is False:
        return NullImportDatasetSyncProgress()
    if show_progress is None:
        from deeporigin.utils.notebook import get_notebook_environment

        if get_notebook_environment() != "jupyter":
            return NullImportDatasetSyncProgress()
    return NotebookImportDatasetSyncProgress(step_labels=step_labels)


def import_dataset_sync_progress_for_pose_registration(
    *,
    show_progress: bool | None,
) -> ImportDatasetSyncProgressReporter:
    """Compact progress for :meth:`~deeporigin.drug_discovery.structures.pose.PoseSet.sync`."""
    return import_dataset_sync_progress(
        show_progress=show_progress,
        step_labels=POSE_REGISTRATION_STEPS,
    )


def import_dataset_sync_progress_for_ligand(
    *,
    show_progress: bool | None,
    workflow: bool,
) -> ImportDatasetSyncProgressReporter:
    """Compact progress for :meth:`~deeporigin.drug_discovery.structures.ligand.LigandSet.sync`."""
    return import_dataset_sync_progress(
        show_progress=show_progress,
        step_labels=(
            LIGAND_WORKFLOW_SYNC_STEPS if workflow else LIGAND_SERVED_SYNC_STEPS
        ),
    )
