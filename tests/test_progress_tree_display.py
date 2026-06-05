"""Tests for v2 progress tree HTML rendering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeporigin.platform.progress_tree_display import (
    is_v2_progress_tree,
    render_progress_tree_html,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "executions"


def _load_fixture(name: str) -> dict:
    """Load a JSON execution fixture from ``tests/fixtures/executions``."""
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def test_is_v2_progress_tree_true_for_execution_node() -> None:
    """v2 trees expose ``displayName`` and ``status`` on the root node."""
    dto = _load_fixture("rbfe-v2-progress-tree.json")
    report = dto["progressReport"]
    assert is_v2_progress_tree(report) is True


def test_is_v2_progress_tree_false_for_legacy_complete() -> None:
    """Flat legacy ``complete`` payloads are not v2 trees."""
    assert is_v2_progress_tree({"complete": 42}) is False


def test_is_v2_progress_tree_false_for_batched_workflow_keys() -> None:
    """Batched workflow-key maps are not v2 trees."""
    batched = {"workflow-abc-123": {"complete": 100}}
    assert is_v2_progress_tree(batched) is False


def test_is_v2_progress_tree_false_for_non_dict() -> None:
    """Non-dict progress reports are not v2 trees."""
    assert is_v2_progress_tree(None) is False
    assert is_v2_progress_tree("not json") is False


def test_render_progress_tree_contains_labels_and_statuses() -> None:
    """Rendered HTML includes truncated labels and status badges."""
    dto = _load_fixture("rbfe-v2-progress-tree.json")
    html = render_progress_tree_html(dto["progressReport"])

    assert "do-progress-tree" in html
    assert "prepare-inputs" in html
    assert "pair-pipeline" in html
    assert "system-prep-task" in html
    assert "rbfe-e2e-task" in html
    assert ">Succeeded<" in html
    assert ">Failed<" in html


def test_render_progress_tree_shows_svg_ring_when_complete_present() -> None:
    """Nodes with ``toolProgress.complete`` render ring and percent badge."""
    dto = _load_fixture("rbfe-v2-progress-tree.json")
    html = render_progress_tree_html(dto["progressReport"])

    assert "do-progress-ring" in html
    assert "do-progress-complete-badge" in html
    assert "do-progress-ring-group" in html
    assert 'aria-label="100% complete"' in html
    assert ">100%<" in html


def test_render_progress_tree_details_only_on_failed_with_message() -> None:
    """Failed nodes with messages get expandable ``details`` blocks."""
    dto = _load_fixture("rbfe-v2-progress-tree.json")
    html = render_progress_tree_html(dto["progressReport"])

    assert html.count("<details") >= 2
    assert "main: Error (exit code 1)" in html
    assert "prepare-inputs" in html
    assert "prepare-inputs</span>" in html or "prepare-inputs" in html


def test_render_progress_tree_escapes_html_injection() -> None:
    """Display names and messages are HTML-escaped."""
    report = {
        "id": "root",
        "displayName": '<script>alert("x")</script>',
        "status": "Failed",
        "message": "<b>broken</b>",
        "children": [],
    }
    html = render_progress_tree_html(report)

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>broken</b>" not in html
    assert "&lt;b&gt;broken&lt;/b&gt;" in html


def test_render_progress_tree_truncates_long_display_name() -> None:
    """Long ``displayName`` values are truncated for inline display."""
    long_name = "pair-pipeline(" + "x" * 80 + ")"
    report = {
        "id": "root",
        "displayName": long_name,
        "status": "Running",
        "children": [],
    }
    html = render_progress_tree_html(report)

    visible = long_name[:47] + "…"
    assert visible in html
    assert long_name in html


@pytest.mark.parametrize(
    ("status", "color"),
    [
        ("Running", "#0d6efd"),
        ("Succeeded", "#198754"),
        ("Failed", "#dc3545"),
        ("Cancelled", "#6c757d"),
    ],
)
def test_render_progress_tree_status_colors(status: str, color: str) -> None:
    """Status strings map to the expected node border colors."""
    report = {
        "id": "node-1",
        "displayName": "step",
        "status": status,
        "children": [],
    }
    html = render_progress_tree_html(report)
    assert color in html
