"""Bootstrap card HTML for notebook execution status without the legacy Job widget."""

from __future__ import annotations

from dataclasses import dataclass
import html
import json
import time
from typing import Self
import uuid

from beartype import beartype

from deeporigin.platform.progress_tree_display import (
    is_v2_progress_tree,
    render_progress_tree_html,
)
from deeporigin.utils.constants import BOOTSTRAP_5_CSS_CDN_URL

# Bootstrap 5 ``bg-*`` suffix for status badges (footer).
_STATUS_BADGE_VARIANT: dict[str, str] = {
    "Succeeded": "success",
    "Completed": "success",
    "Failed": "danger",
    "Quoted": "secondary",
    "Running": "primary",
    "Created": "info",
    "Queued": "info",
    "Cancelled": "secondary",
    "InsufficientFunds": "warning",
    "FailedQuotation": "warning",
    "New": "secondary",
}


def _status_badge_bg_class(status: str) -> str:
    """Return Bootstrap ``bg-*`` class suffix for a platform status string."""
    return _STATUS_BADGE_VARIANT.get(status, "secondary")


def _mean_complete_from_batch_subjobs(data: dict) -> float | None:
    """If ``data`` is a dict of sub-job dicts each with ``complete``, return their mean.

    Returns:
        Mean in ``[0, 100]``, or ``None`` if ``data`` is not in that batched shape.
    """
    if not data:
        return None
    batch_values: list[float] = []
    for v in data.values():
        if not isinstance(v, dict) or "complete" not in v:
            return None
        try:
            batch_values.append(float(v["complete"]))
        except (TypeError, ValueError):
            return None
    avg = sum(batch_values) / len(batch_values)
    return max(0.0, min(100.0, avg))


def _parse_complete_from_progress_report(progress_report: object) -> float:
    """Extract a 0–100 completion value from ``progressReport`` JSON.

    Supports a flat ``{"complete": n}`` shape and batched runs where every
    top-level value is a dict with its own ``complete`` (e.g. per sub-job
    workflow keys). In the batched case, the displayed value is the
    arithmetic mean of those ``complete`` values.

    Args:
        progress_report: Raw DTO field (``None``, ``str`` JSON, or ``dict``).

    Returns:
        Completion percentage in ``[0, 100]``, or ``0.0`` if missing or invalid.
    """
    if progress_report is None:
        return 0.0
    data: dict | None
    if isinstance(progress_report, dict):
        data = progress_report
    elif isinstance(progress_report, str):
        try:
            parsed = json.loads(progress_report)
        except (json.JSONDecodeError, TypeError):
            return 0.0
        data = parsed if isinstance(parsed, dict) else None
    else:
        return 0.0
    if data is None:
        return 0.0
    batched = _mean_complete_from_batch_subjobs(data)
    if batched is not None:
        return batched
    raw = data.get("complete", 0)
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, v))


def _progress_report_data(progress_report: object) -> dict | None:
    """Parse ``progressReport`` into a dict, or ``None`` if missing or invalid."""
    if progress_report is None:
        return None
    if isinstance(progress_report, dict):
        return progress_report
    if isinstance(progress_report, str):
        try:
            parsed = json.loads(progress_report)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _clamp_complete(raw: object) -> float:
    """Coerce a raw ``complete`` value to ``[0, 100]``."""
    try:
        v = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, v))


def _workflow_subjob_completes_from_progress_report(
    progress_report: object,
) -> tuple[float, ...]:
    """Return sorted ``complete`` values for each top-level ``workflow`` key.

    Args:
        progress_report: Raw DTO field (``None``, ``str`` JSON, or ``dict``).

    Returns:
        Tuple of completion percentages in ``[0, 100]``, one per workflow key
        (sorted by key). Empty when there are no workflow keys.
    """
    data = _progress_report_data(progress_report)
    if not data:
        return ()
    completes: list[float] = []
    workflow_keys = sorted(
        k for k in data if isinstance(k, str) and "workflow" in k.lower()
    )
    for key in workflow_keys:
        sub = data[key]
        if isinstance(sub, dict):
            completes.append(_clamp_complete(sub.get("complete", 0)))
        else:
            completes.append(0.0)
    return tuple(completes)


def _render_single_progress_bar_html(*, complete: float) -> str:
    """Render one Bootstrap progress bar for a 0–100 completion value."""
    pct = float(complete)
    if pct > 0:
        width = min(100.0, pct)
        width_s = html.escape(f"{width:.1f}".rstrip("0").rstrip("."), quote=True)
        return (
            f'<div class="progress" style="height: 22px;" role="progress" '
            f'aria-label="Execution progress">'
            f'<div class="progress-bar" role="progressbar" '
            f'style="width: {width_s}%;" '
            f'aria-valuenow="{width_s}" aria-valuemin="0" aria-valuemax="100">'
            f"{width_s}%</div></div>"
        )
    return (
        '<div class="progress" style="height: 22px;" role="progress" '
        'aria-label="Execution progress (indeterminate)">'
        '<div class="progress-bar progress-bar-striped progress-bar-animated w-100" '
        'role="progressbar"></div></div>'
    )


def _count_workflow_children_from_progress_report(progress_report: object) -> int:
    """Count top-level keys in ``progressReport`` whose names contain ``workflow``.

    Used when a parent execution aggregates child runs (e.g. workflow batch keys
    like ``workflow-…-123``).

    Args:
        progress_report: Raw DTO field (``None``, ``str`` JSON, or ``dict``).

    Returns:
        Number of keys whose string form contains ``workflow`` (case-insensitive).
    """
    if progress_report is None:
        return 0
    data: dict | None
    if isinstance(progress_report, dict):
        data = progress_report
    elif isinstance(progress_report, str):
        try:
            parsed = json.loads(progress_report)
        except (json.JSONDecodeError, TypeError):
            return 0
        data = parsed if isinstance(parsed, dict) else None
    else:
        return 0
    if not data:
        return 0
    return sum(1 for k in data if isinstance(k, str) and "workflow" in k.lower())


@beartype
@dataclass
class ExecutionDisplay:
    """Display model for a single platform execution in Jupyter HTML.

    Attributes:
        complete: Progress 0–100 from ``progressReport``; ``0`` means an indeterminate bar
            when :attr:`status` is ``"Running"`` (the bar is hidden for other statuses).
        execution_id: Platform execution UUID string, or ``None`` if nothing has been submitted.
        name: Optional user label from the execution.
        status: Lifecycle status (see :data:`~deeporigin.platform.constants.PlatformStatus`).
        tool_key: Platform tool identifier from the execution DTO, if known.
        tool_version: Tool version string from the execution DTO, if known.
        workflow_child_count: Number of ``progressReport`` top-level keys whose names
            contain ``workflow`` (child executions in a workflow batch); ``0`` if none.
        workflow_subjob_completes: Per-workflow ``complete`` values when batch keys exist;
            used to render one progress bar per child. Empty when not a workflow batch.
        progress_report: Raw ``progressReport`` from the execution DTO, when present.
    """

    complete: float | int
    execution_id: str | None
    name: str | None
    status: str
    tool_key: str | None = None
    tool_version: str | None = None
    workflow_child_count: int = 0
    workflow_subjob_completes: tuple[float, ...] = ()
    progress_report: dict | str | None = None

    @classmethod
    def from_pending(
        cls,
        *,
        name: str | None,
        status: str | None,
        tool_key: str | None = None,
        tool_version: str | None = None,
    ) -> Self:
        """Build a display for an object that has not received a platform execution ID yet.

        Args:
            name: Optional user label (e.g. from :class:`~deeporigin.drug_discovery.execution.Execution`).
            status: Current lifecycle status, or ``None`` before any lifecycle state.
            tool_key: Optional tool key (e.g. from the execution class ``tool_key``).
            tool_version: Optional tool version (e.g. from ``tool_version``).

        Returns:
            Display model with ``status`` defaulting to ``\"New\"`` when missing.
        """
        st = (status or "").strip() or "New"
        return cls(
            complete=0,
            execution_id=None,
            name=name,
            status=st,
            tool_key=tool_key,
            tool_version=tool_version,
            workflow_child_count=0,
        )

    @classmethod
    def from_dto(cls, dto: dict) -> Self:
        """Build an :class:`ExecutionDisplay` from a tools API execution DTO.

        Args:
            dto: Execution dict with at least ``executionId`` and ``status``.

        Returns:
            Populated display model.

        Raises:
            ValueError: If ``executionId`` is missing.
        """
        execution_id = dto.get("executionId")
        if execution_id is None:
            raise ValueError("DTO must contain 'executionId' field")
        status = dto.get("status") or ""
        raw_name = dto.get("name")
        name: str | None
        if raw_name is None:
            name = None
        else:
            name = str(raw_name)
        raw_progress = dto.get("progressReport")
        complete = _parse_complete_from_progress_report(raw_progress)
        workflow_child_count = _count_workflow_children_from_progress_report(
            raw_progress
        )
        workflow_subjob_completes = _workflow_subjob_completes_from_progress_report(
            raw_progress
        )
        tool_key: str | None = None
        tool_version: str | None = None
        raw_tool = dto.get("tool")
        if isinstance(raw_tool, dict):
            k = raw_tool.get("key")
            v = raw_tool.get("version")
            if k is not None and str(k).strip():
                tool_key = str(k).strip()
            if v is not None and str(v).strip():
                tool_version = str(v).strip()
        return cls(
            complete=complete,
            execution_id=str(execution_id),
            name=name,
            status=str(status),
            tool_key=tool_key,
            tool_version=tool_version,
            workflow_child_count=workflow_child_count,
            workflow_subjob_completes=workflow_subjob_completes,
            progress_report=raw_progress
            if isinstance(raw_progress, (dict, str))
            else None,
        )

    def _card_header_title(self) -> str:
        """Card header text: non-empty ``name``, else ``execution_id``, else ``New``."""
        if self.name is not None and self.name.strip():
            return self.name.strip()
        if self.execution_id:
            return self.execution_id
        return "New"

    def _tool_metadata_html(self) -> str:
        """Subtitle under the card title: tool key and version when available."""
        if self.tool_key is None and self.tool_version is None:
            return ""
        chunks: list[str] = []
        if self.tool_key is not None:
            chunks.append(
                f'<code class="small text-body-secondary text-break">{html.escape(self.tool_key, quote=True)}</code>'
            )
        if self.tool_version is not None:
            chunks.append(
                f'<span class="text-muted">v{html.escape(self.tool_version, quote=True)}</span>'
            )
        inner = ' <span class="text-muted" aria-hidden="true">·</span> '.join(chunks)
        return f'<div class="small mt-1">{inner}</div>'

    def _render_progress_block(self) -> str:
        """Render the card-body progress section (v2 tree or legacy bar).

        Returns:
            HTML fragment for progress display, or empty string when none applies.
        """
        progress_data = _progress_report_data(self.progress_report)
        if progress_data is not None and is_v2_progress_tree(progress_data):
            return render_progress_tree_html(progress_data)
        if self.status != "Running":
            return ""
        if self.workflow_subjob_completes:
            bar_htmls = [
                _render_single_progress_bar_html(complete=c)
                for c in self.workflow_subjob_completes
            ]
            progress_parts: list[str] = []
            for i, bar in enumerate(bar_htmls):
                if i < len(bar_htmls) - 1:
                    progress_parts.append(f'<div class="mb-2">{bar}</div>')
                else:
                    progress_parts.append(bar)
            return "".join(progress_parts)
        return _render_single_progress_bar_html(complete=float(self.complete))

    def render_html(self, *, will_auto_update: bool = False) -> str:
        """Render a self-contained Bootstrap 5 card HTML fragment.

        Args:
            will_auto_update: If True, show a live-update hint in the footer.

        Returns:
            HTML string safe for :class:`IPython.display.HTML`.

        Note:
            When ``progress_report`` is a v2 tree, the tree is shown for all
            statuses. Otherwise the Bootstrap progress bar is shown only when
            :attr:`status` is ``"Running"``.
        """
        esc_status = html.escape(self.status, quote=True)
        esc_title = html.escape(self._card_header_title(), quote=True)
        tool_meta = self._tool_metadata_html()
        badge_bg = html.escape(_status_badge_bg_class(self.status), quote=True)
        last_updated = time.strftime("%Y-%m-%d %H:%M:%S")
        uid = f"exec_disp_{uuid.uuid4().hex}"
        if self.execution_id is None:
            pending_notice = (
                '<div class="alert alert-secondary py-2 px-3 small mb-3" role="status">'
                "No platform execution ID yet. When you are ready, submit your run with "
                "<code>start()</code> (use <code>quote()</code> first if your workflow "
                "requires a quote).</div>"
            )
            id_below_progress = ""
        else:
            esc_id = html.escape(self.execution_id, quote=True)
            pending_notice = ""
            id_below_progress = (
                '<div class="small text-muted mt-2 text-break">'
                f"<code>{esc_id}</code></div>"
            )
        progress_block = self._render_progress_block()

        live_inline = ""
        if will_auto_update:
            live_inline = (
                '<span class="d-inline-flex align-items-center gap-1 text-muted" '
                'title="Refreshing automatically">'
                '<span class="spinner-border spinner-border-sm text-primary" '
                'role="status" aria-hidden="true"></span>'
                "<span>Live updates…</span>"
                "</span>"
            )

        wf_n = int(self.workflow_child_count)
        if wf_n > 0:
            wf_label = html.escape(f"WORKFLOW ({wf_n}x)", quote=True)
            workflow_badge = (
                '<span class="badge rounded-pill bg-secondary-subtle text-secondary-emphasis '
                'border border-secondary-subtle align-middle" '
                'style="font-variant: small-caps; letter-spacing: 0.04em;" '
                f'title="This run includes {wf_n} workflow child execution(s)">{wf_label}</span>'
            )
        else:
            workflow_badge = ""

        return f"""<div id="{html.escape(uid, quote=True)}" class="deeporigin-exec-display">
<link href="{html.escape(BOOTSTRAP_5_CSS_CDN_URL, quote=True)}" rel="stylesheet">
<div class="card shadow-sm" style="max-width: 42rem;">
<div class="card-header py-2">
<div class="fw-semibold">{esc_title}</div>
{tool_meta}
</div>
<div class="card-body py-3">
{pending_notice}
{progress_block}
{id_below_progress}
</div>
<div class="card-footer small py-2">
<div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
<div class="d-flex align-items-center flex-wrap gap-2">
<div class="text-muted">Last updated: {html.escape(last_updated, quote=True)}</div>
{live_inline}
</div>
<div class="d-flex align-items-center flex-wrap gap-2">
{workflow_badge}
<span class="badge rounded-pill bg-{badge_bg}">{esc_status}</span>
</div>
</div>
</div>
</div>
</div>"""
