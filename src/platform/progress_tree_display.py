"""HTML/SVG progress tree for v2 tools-service ``progressReport`` DTOs."""

from __future__ import annotations

import html
from typing import Any

from beartype import beartype

# Bootstrap-aligned status colors for tree nodes.
_STATUS_COLORS: dict[str, str] = {
    "Running": "#0d6efd",
    "Queued": "#0d6efd",
    "Created": "#0d6efd",
    "Finishing": "#0d6efd",
    "Succeeded": "#198754",
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
def _status_color(status: str) -> str:
    """Map a platform node status string to a CSS color.

    Args:
        status: Node status from the progress tree.

    Returns:
        Hex color string.
    """
    return _STATUS_COLORS.get(status, _DEFAULT_STATUS_COLOR)


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
    color = _status_color(status)
    esc_color = html.escape(color, quote=True)
    esc_full_name = html.escape(display_name, quote=True)
    esc_label = html.escape(_truncate_label(display_name), quote=True)
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
        f'<span class="do-progress-node-badge" style="background:{esc_color}">'
        f"{esc_status}</span>",
    ]

    message = node.get("message")
    if status == "Failed" and isinstance(message, str) and message.strip():
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
