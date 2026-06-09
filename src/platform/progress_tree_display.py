"""HTML/SVG progress tree for v2 tools-service ``progressReport`` DTOs."""

from __future__ import annotations

from datetime import datetime, timezone
import html
import re
from typing import Any

from beartype import beartype

from deeporigin.utils.constants import PROGRESS_TREE_DISPLAY_ACRONYMS
from deeporigin.utils.iso8601 import parse_iso_timestamp_utc

_DISPLAY_INDEX_RE = re.compile(r"index:(\d+)")

# Bootstrap-aligned status colors for tree nodes.
_STATUS_COLORS: dict[str, str] = {
    "Running": "#0d6efd",
    "Queued": "#0d6efd",
    "Created": "#0d6efd",
    "Finishing": "#0d6efd",
    "Succeeded": "#198754",
    "Completed": "#198754",
    "Failed": "#dc3545",
    "Cancelled": "#6c757d",
    "Suspended": "#6c757d",
}
_DEFAULT_STATUS_COLOR = "#adb5bd"

_TREE_STYLES = """
<style>
.do-progress-tree { font-size: 0.875rem; line-height: 1.4; }
.do-progress-node {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem 0.5rem;
  padding: 0.25rem 0 0.25rem 0.5rem;
  margin-bottom: 0.125rem;
  border-left: 3px solid var(--do-node-color, #adb5bd);
}
.do-progress-node-label {
  flex: 1 1 auto;
  min-width: 0;
  word-break: break-word;
}
.do-progress-ring-group {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  flex-shrink: 0;
}
.do-progress-complete-badge {
  font-size: 0.65rem;
  font-weight: 600;
  padding: 0.1em 0.35em;
  border-radius: 999px;
  background: #e7f1ff;
  color: #0d6efd;
  white-space: nowrap;
  line-height: 1.2;
}
.do-progress-node-badge {
  flex-shrink: 0;
  font-size: 0.7rem;
  padding: 0.15em 0.5em;
  border-radius: 999px;
  color: #fff;
  white-space: nowrap;
}
.do-progress-runtime {
  flex-shrink: 0;
  font-size: 0.7rem;
  color: #6c757d;
  white-space: nowrap;
}
.do-progress-ring-spacer {
  display: inline-block;
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}
.do-progress-error {
  flex-basis: 100%;
  margin-left: 1.5rem;
}
</style>
"""


@beartype
def is_v2_progress_tree(report: object) -> bool:
    """Return True when ``report`` is a v2 execution progress tree node.

    Args:
        report: Raw ``progressReport`` field from a tools execution DTO.

    Returns:
        True if the value looks like an ``ExecutionProgressNode`` root.
    """
    if not isinstance(report, dict):
        return False
    display_name = report.get("displayName")
    status = report.get("status")
    return isinstance(display_name, str) and isinstance(status, str)


@beartype
def _is_leaf_node(node: dict[str, Any]) -> bool:
    """Return True when a progress node has no child steps.

    Args:
        node: One ``ExecutionProgressNode`` dict.

    Returns:
        True if status badges and error details should be shown.
    """
    children = node.get("children")
    return not isinstance(children, list) or len(children) == 0


@beartype
def _status_color(status: str) -> str:
    """Map a platform node status string to a CSS color.

    Args:
        status: Node status from the progress tree.

    Returns:
        Hex color string.
    """
    return _STATUS_COLORS.get(status, _DEFAULT_STATUS_COLOR)


@beartype
def _strip_display_name_args(raw: str) -> str:
    """Trim workflow argument suffixes from a raw ``displayName``.

    Strips everything from the first ``(`` onward. When an ``index:N`` token is
    present inside the parentheses, appends ``-N`` to the kebab-case prefix
    (e.g. ``pair-pipeline(1:index:1,...)`` → ``pair-pipeline-1``).

    Args:
        raw: Raw ``displayName`` from the progress tree.

    Returns:
        Kebab-case base name, optionally with an index suffix.
    """
    paren = raw.find("(")
    if paren == -1:
        return raw.strip()
    prefix = raw[:paren].rstrip()
    inner = raw[paren + 1 :]
    match = _DISPLAY_INDEX_RE.search(inner)
    if match:
        return f"{prefix}-{match.group(1)}"
    return prefix


@beartype
def format_display_name(raw: str) -> str:
    """Format a workflow ``displayName`` for human-readable tree labels.

    Applies :func:`_strip_display_name_args`, replaces hyphens with spaces,
    capitalizes the first word, and uppercases known acronyms (RBFE, ABFE).

    Args:
        raw: Raw ``displayName`` from the progress tree.

    Returns:
        Friendly label text for inline display.
    """
    base = _strip_display_name_args(raw)
    tokens = [token for token in base.replace("-", " ").split() if token]
    if not tokens:
        return raw.strip()

    formatted: list[str] = []
    for index, token in enumerate(tokens):
        lower = token.lower()
        if lower in PROGRESS_TREE_DISPLAY_ACRONYMS:
            formatted.append(lower.upper())
        elif index == 0:
            formatted.append(lower.capitalize())
        else:
            formatted.append(lower)
    return " ".join(formatted)


@beartype
def _truncate_label(text: str, *, max_len: int = 48) -> str:
    """Truncate a node label for inline display.

    Args:
        text: Full display name.
        max_len: Maximum visible character count before ellipsis.

    Returns:
        Truncated label with ellipsis when needed.
    """
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


@beartype
def _clamp_complete(raw: object) -> float:
    """Coerce a raw completion value to ``[0, 100]``.

    Args:
        raw: Raw ``complete`` value from ``toolProgress``.

    Returns:
        Clamped float in ``[0, 100]``.
    """
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, value))


@beartype
def _extract_complete(node: dict[str, Any]) -> float | None:
    """Read ``toolProgress.complete`` from a progress tree node.

    Args:
        node: One ``ExecutionProgressNode`` dict.

    Returns:
        Completion percentage, or ``None`` when absent.
    """
    tool_progress = node.get("toolProgress")
    if not isinstance(tool_progress, dict):
        return None
    if "complete" not in tool_progress:
        return None
    return _clamp_complete(tool_progress["complete"])


@beartype
def _node_end_timestamp(node: dict[str, Any]) -> datetime | None:
    """Parse a progress node's end timestamp, if present.

    Args:
        node: One ``ExecutionProgressNode`` dict.

    Returns:
        UTC end time from ``finishedAt`` or ``completedAt``, or ``None``.
    """
    for key in ("finishedAt", "completedAt"):
        raw = node.get(key)
        if isinstance(raw, str) and raw.strip():
            return parse_iso_timestamp_utc(raw.strip())
    return None


@beartype
def _node_runtime_seconds(node: dict[str, Any]) -> float | None:
    """Compute elapsed seconds for a progress node from its timestamps.

    Uses ``startedAt`` as the start. When ``finishedAt`` / ``completedAt`` is
    missing, uses the current UTC time (for in-flight leaf steps).

    Args:
        node: One ``ExecutionProgressNode`` dict.

    Returns:
        Elapsed seconds, or ``None`` when ``startedAt`` is missing or invalid.
    """
    started_raw = node.get("startedAt")
    if not isinstance(started_raw, str) or not started_raw.strip():
        return None
    try:
        started = parse_iso_timestamp_utc(started_raw.strip())
        end = _node_end_timestamp(node)
        if end is None:
            end = datetime.now(timezone.utc)
        seconds = (end - started).total_seconds()
    except ValueError:
        return None
    if seconds < 0:
        return None
    return seconds


@beartype
def format_runtime(seconds: float | int) -> str:
    """Format elapsed seconds as a compact, human-readable duration.

    Args:
        seconds: Elapsed time in seconds.

    Returns:
        Short label such as ``45s``, ``2m 34s``, or ``1h 5m``.
    """
    total = int(round(seconds))
    if total < 1:
        return "<1s"
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        if secs:
            return f"{minutes}m {secs}s"
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        if minutes:
            return f"{hours}h {minutes}m"
        return f"{hours}h"
    days, hours = divmod(hours, 24)
    if hours:
        return f"{days}d {hours}h"
    return f"{days}d"


@beartype
def _render_runtime(seconds: float) -> str:
    """Render a gray runtime label for a leaf node.

    Args:
        seconds: Elapsed time in seconds.

    Returns:
        HTML span for the runtime label.
    """
    label = format_runtime(seconds)
    esc_label = html.escape(label, quote=True)
    return f'<span class="do-progress-runtime">{esc_label}</span>'


@beartype
def _render_complete_badge(complete: float) -> str:
    """Render a small percent-complete badge beside the progress ring.

    Args:
        complete: Completion percentage in ``[0, 100]``.

    Returns:
        HTML span for the completion badge.
    """
    pct = _clamp_complete(complete)
    if pct == int(pct):
        label = f"{int(pct)}%"
    else:
        label = f"{pct:.1f}%".rstrip("0").rstrip(".") + "%"
    esc_label = html.escape(label, quote=True)
    return f'<span class="do-progress-complete-badge">{esc_label}</span>'


@beartype
def _render_progress_indicator(complete: float) -> str:
    """Render ring + percent badge grouped together.

    Args:
        complete: Completion percentage in ``[0, 100]``.

    Returns:
        HTML fragment with SVG ring and completion badge.
    """
    return (
        '<span class="do-progress-ring-group">'
        f"{_render_svg_ring(complete)}"
        f"{_render_complete_badge(complete)}"
        "</span>"
    )


@beartype
def _render_svg_ring(complete: float, *, size: int = 18) -> str:
    """Render a small inline SVG circular progress ring.

    Args:
        complete: Completion percentage in ``[0, 100]``.
        size: SVG width and height in pixels.

    Returns:
        HTML string with an inline SVG element.
    """
    pct = _clamp_complete(complete)
    radius = (size - 3) / 2
    circumference = 2 * 3.141592653589793 * radius
    offset = circumference * (1.0 - pct / 100.0)
    center = size / 2
    esc_size = html.escape(str(size), quote=True)
    esc_cx = html.escape(f"{center:.2f}", quote=True)
    esc_cy = esc_cx
    esc_r = html.escape(f"{radius:.2f}", quote=True)
    esc_circ = html.escape(f"{circumference:.2f}", quote=True)
    esc_offset = html.escape(f"{offset:.2f}", quote=True)
    esc_pct = html.escape(f"{pct:.0f}", quote=True)
    return (
        f'<svg class="do-progress-ring" width="{esc_size}" height="{esc_size}" '
        f'viewBox="0 0 {esc_size} {esc_size}" aria-label="{esc_pct}% complete" '
        f'role="img">'
        f'<circle cx="{esc_cx}" cy="{esc_cy}" r="{esc_r}" fill="none" '
        f'stroke="#dee2e6" stroke-width="2.5"/>'
        f'<circle cx="{esc_cx}" cy="{esc_cy}" r="{esc_r}" fill="none" '
        f'stroke="#0d6efd" stroke-width="2.5" stroke-linecap="round" '
        f'stroke-dasharray="{esc_circ}" stroke-dashoffset="{esc_offset}" '
        f'transform="rotate(-90 {esc_cx} {esc_cy})"/>'
        f"</svg>"
    )


@beartype
def _render_failed_details(message: str) -> str:
    """Render expandable error details for a failed node.

    Args:
        message: Failure message from the progress node.

    Returns:
        HTML ``details`` fragment.
    """
    esc_message = html.escape(message, quote=True)
    return (
        '<details class="do-progress-error small text-danger">'
        "<summary>Error details</summary>"
        f'<pre class="mb-0 mt-1 text-break">{esc_message}</pre>'
        "</details>"
    )


@beartype
def _render_node(node: dict[str, Any], *, depth: int) -> str:
    """Render one progress tree node and its descendants.

    Args:
        node: One ``ExecutionProgressNode`` dict.
        depth: Zero-based tree depth for indentation.

    Returns:
        HTML fragment for this node and all children.
    """
    display_name = str(node.get("displayName") or node.get("id") or "step")
    status = str(node.get("status") or "")
    is_leaf = _is_leaf_node(node)
    color = _status_color(status)
    esc_color = html.escape(color, quote=True)
    esc_full_name = html.escape(display_name, quote=True)
    friendly_name = format_display_name(display_name)
    esc_label = html.escape(_truncate_label(friendly_name), quote=True)
    esc_status = html.escape(status, quote=True)

    complete = _extract_complete(node)
    if complete is not None:
        ring_html = _render_progress_indicator(complete)
    else:
        ring_html = '<span class="do-progress-ring-spacer" aria-hidden="true"></span>'

    indent_rem = depth * 1.5
    esc_indent = html.escape(f"{indent_rem:.1f}", quote=True)

    parts: list[str] = [
        f'<div class="do-progress-node" style="margin-left: {esc_indent}rem; '
        f'--do-node-color: {esc_color}; border-left-color: {esc_color};">',
        ring_html,
        f'<span class="do-progress-node-label fw-medium" title="{esc_full_name}">'
        f"{esc_label}</span>",
    ]

    if is_leaf:
        runtime_secs = _node_runtime_seconds(node)
        if runtime_secs is not None:
            parts.append(_render_runtime(runtime_secs))
        parts.append(
            f'<span class="do-progress-node-badge" style="background:{esc_color}">'
            f"{esc_status}</span>"
        )

    message = node.get("message")
    if is_leaf and status == "Failed" and isinstance(message, str) and message.strip():
        parts.append(_render_failed_details(message.strip()))

    parts.append("</div>")

    children = node.get("children")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                parts.append(_render_node(child, depth=depth + 1))

    return "".join(parts)


@beartype
def render_progress_tree_html(progress_report: dict[str, Any]) -> str:
    """Render an indented HTML/SVG progress tree from a v2 ``progressReport``.

    Args:
        progress_report: Root ``ExecutionProgressNode`` dict.

    Returns:
        Self-contained HTML fragment with scoped CSS.
    """
    body = _render_node(progress_report, depth=0)
    return f'{_TREE_STYLES}<div class="do-progress-tree">{body}</div>'
