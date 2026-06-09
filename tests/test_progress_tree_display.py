"""Tests for v2 progress tree HTML rendering."""

from __future__ import annotations

import json
from pathlib import Path

from deeporigin.platform.progress_tree_display import (
    format_display_name,
    format_runtime,
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
    """Rendered HTML includes friendly labels; status badges on leaf nodes only."""
    dto = _load_fixture("rbfe-v2-progress-tree.json")
    html = render_progress_tree_html(dto["progressReport"])

    assert "do-progress-tree" in html
    assert "Prepare inputs" in html
    assert "Pair pipeline" in html
    assert "Pair pipeline 1" in html
    assert "System prep task" in html
    assert "RBFE e2e task" in html
    assert ">Succeeded<" in html
    assert ">Failed<" in html
    assert "pair-pipeline failed" not in html


def test_format_display_name_pair_pipeline_with_index() -> None:
    """``displayName`` args are stripped and ``index`` is appended as a suffix."""
    raw = 'pair-pipeline(1:index:1,ligand1:{"id":"A"},ligand2:{"id":"B"},prepared_system:{})'
    assert format_display_name(raw) == "Pair pipeline 1"


def test_format_display_name_kebab_case_and_acronyms() -> None:
    """Hyphens become spaces; first word capitalized; RBFE/ABFE uppercased."""
    assert format_display_name("system-prep-task") == "System prep task"
    assert format_display_name("rbfe-e2e-task") == "RBFE e2e task"
    assert format_display_name("abfe-workflow-step") == "ABFE workflow step"
    assert format_display_name("pair-pipeline") == "Pair pipeline"
    assert format_display_name("prepare-inputs") == "Prepare inputs"


def test_format_display_name_without_parens_unchanged_structure() -> None:
    """Simple kebab names format without index suffix."""
    assert format_display_name("workflow-abc") == "Workflow abc"


def test_format_runtime_human_friendly() -> None:
    """``format_runtime`` returns compact duration labels."""
    assert format_runtime(0.4) == "<1s"
    assert format_runtime(45) == "45s"
    assert format_runtime(154) == "2m 34s"
    assert format_runtime(3600) == "1h"
    assert format_runtime(3661) == "1h 1m"
    assert format_runtime(90000) == "1d 1h"


def test_render_progress_tree_shows_runtime_on_leaf_nodes() -> None:
    """Leaf nodes with timestamps show gray runtime left of the status badge."""
    dto = _load_fixture("rbfe-v2-progress-tree.json")
    html = render_progress_tree_html(dto["progressReport"])

    assert "do-progress-runtime" in html
    assert ">14s<" in html
    assert ">2m 34s<" in html
    assert ">39m 14s<" in html
    leaf_block = html.split("System prep task", 1)[1].split("</div>", 1)[0]
    assert "2m 34s" in leaf_block
    assert ">Succeeded<" in leaf_block
    assert leaf_block.index("2m 34s") < leaf_block.index(">Succeeded<")


def test_render_progress_tree_runtime_only_on_leaf_nodes() -> None:
    """Internal nodes omit runtime even when timestamps are present."""
    report = {
        "id": "root",
        "displayName": "pair-pipeline",
        "status": "Failed",
        "startedAt": "2026-06-05T13:09:01Z",
        "finishedAt": "2026-06-05T13:53:00Z",
        "children": [
            {
                "id": "leaf",
                "displayName": "rbfe-e2e-task",
                "status": "Running",
                "startedAt": "2026-06-05T13:11:55Z",
                "finishedAt": "2026-06-05T13:12:55Z",
                "children": [],
            }
        ],
    }
    html = render_progress_tree_html(report)

    assert html.count('class="do-progress-runtime"') == 1
    assert "43m 59s" not in html
    assert ">1m<" in html


def test_render_progress_tree_shows_svg_ring_when_complete_present() -> None:
    """Nodes with ``toolProgress.complete`` render ring and percent badge."""
    dto = _load_fixture("rbfe-v2-progress-tree.json")
    html = render_progress_tree_html(dto["progressReport"])

    assert "do-progress-ring" in html
    assert "do-progress-complete-badge" in html
    assert "do-progress-ring-group" in html
    assert 'aria-label="100% complete"' in html
    assert ">100%<" in html


def test_render_progress_tree_details_only_on_leaf_failed_with_message() -> None:
    """Leaf failed nodes with messages get expandable ``details`` blocks."""
    dto = _load_fixture("rbfe-v2-progress-tree.json")
    html = render_progress_tree_html(dto["progressReport"])

    assert html.count("<details") == 1
    assert "main: Error (exit code 1)" in html
    assert "rbfe-e2e-task failed" not in html


def test_render_progress_tree_hides_status_and_errors_for_non_leaf() -> None:
    """Internal nodes show label only — no status badge or error details."""
    report = {
        "id": "root",
        "displayName": "pair-pipeline",
        "status": "Failed",
        "message": "aggregated failure",
        "children": [
            {
                "id": "child",
                "displayName": "rbfe-e2e-task",
                "status": "Running",
                "message": "should not appear",
                "toolProgress": {"complete": 42},
                "children": [],
            }
        ],
    }
    html = render_progress_tree_html(report)

    assert "Pair pipeline" in html
    assert "RBFE e2e task" in html
    assert "aggregated failure" not in html
    assert "<details" not in html
    assert "should not appear" not in html
    assert ">Running<" in html
    assert html.count('class="do-progress-node-badge"') == 1
    assert "do-progress-ring-group" in html
    assert ">42%<" in html


def test_render_progress_tree_leaf_failed_shows_status_and_details() -> None:
    """Leaf failed nodes show status badge and error details."""
    report = {
        "id": "root",
        "displayName": "failed-step",
        "status": "Failed",
        "message": "main: Error (exit code 1)",
        "children": [],
    }
    html = render_progress_tree_html(report)

    assert ">Failed<" in html
    assert 'class="do-progress-node-badge"' in html
    assert "<details" in html
    assert "main: Error (exit code 1)" in html


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
    """Long formatted labels are truncated; raw ``displayName`` stays in ``title``."""
    long_name = "pair-pipeline(" + "x" * 80 + ")"
    report = {
        "id": "root",
        "displayName": long_name,
        "status": "Running",
        "children": [],
    }
    html = render_progress_tree_html(report)

    assert "Pair pipeline" in html
    assert f'title="{long_name}"' in html


def test_render_progress_tree_status_colors() -> None:
    """Leaf node status strings map to the expected border colors."""
    report = {
        "id": "node-1",
        "displayName": "step",
        "status": "Failed",
        "children": [],
    }
    html = render_progress_tree_html(report)
    assert "border-left-color: #dc3545" in html


def test_render_progress_tree_internal_node_keeps_status_border_without_badge() -> None:
    """Internal nodes keep a status-colored border but omit the status badge."""
    report = {
        "id": "node-1",
        "displayName": "parent-step",
        "status": "Running",
        "children": [
            {
                "id": "leaf",
                "displayName": "leaf-step",
                "status": "Succeeded",
                "children": [],
            }
        ],
    }
    html = render_progress_tree_html(report)
    assert "border-left-color: #0d6efd" in html
    assert html.count('class="do-progress-node-badge"') == 1
    assert ">Succeeded<" in html
