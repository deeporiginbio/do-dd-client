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
        status_line = (
            f'<span class="text-danger">{esc_label}{detail_bit}</span>'
        )
        bar_inner = (
            f'<div class="progress-bar bg-danger" style="width: {pct_s}%;"></div>'
        )
    elif completed >= total:
        status_line = f'<span class="text-success">Done</span>'
        bar_inner = (
            f'<div class="progress-bar bg-success" style="width: 100%;"></div>'
        )
    else:
        status_line = (
            f'<span class="spinner-border spinner-border-sm text-primary" '
            f'role="status" aria-hidden="true"></span>'
            f'<span>{esc_label}{detail_bit}</span>'
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

    def start_step(self, index: int, *, detail: str = "") -> None: ...

    def finish_step(self, index: int, *, detail: str = "") -> None: ...

    def set_execution_id(self, execution_id: str) -> None: ...

    def fail_step(self, index: int, *, message: str = "") -> None: ...

    def close(self) -> None: ...


@dataclass
class NullImportDatasetSyncProgress:
    """No-op reporter for scripts and non-notebook environments."""

    def start_step(self, index: int, *, detail: str = "") -> None:
        return None

    def finish_step(self, index: int, *, detail: str = "") -> None:
        return None

    def set_execution_id(self, execution_id: str) -> None:
        return None

    def fail_step(self, index: int, *, message: str = "") -> None:
        return None

    def close(self) -> None:
        return None


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
        if self._failed or index < 0 or index >= len(self.step_labels):
            return
        self._status_label = self.step_labels[index]
        self._detail = detail
        self._refresh()

    def finish_step(self, index: int, *, detail: str = "") -> None:
        if self._failed or index < 0 or index >= len(self.step_labels):
            return
        self._completed = max(self._completed, index + 1)
        if detail:
            self._detail = detail
        self._refresh()

    def set_execution_id(self, execution_id: str) -> None:
        return None

    def fail_step(self, index: int, *, message: str = "") -> None:
        self._failed = True
        if 0 <= index < len(self.step_labels):
            self._status_label = self.step_labels[index]
        if message:
            self._detail = message
        self._refresh()

    def close(self) -> None:
        if self._failed:
            return
        self._completed = self._total
        self._detail = ""
        self._refresh()


def import_dataset_sync_progress_for_pose_registration(
    *,
    show_progress: bool | None,
) -> ImportDatasetSyncProgressReporter:
    """Return a notebook step UI when ``show_progress`` is true (default: Jupyter only)."""
    if show_progress is False:
        return NullImportDatasetSyncProgress()
    if show_progress is None:
        from deeporigin.utils.notebook import get_notebook_environment

        if get_notebook_environment() != "jupyter":
            return NullImportDatasetSyncProgress()
    return NotebookImportDatasetSyncProgress(step_labels=POSE_REGISTRATION_STEPS)
