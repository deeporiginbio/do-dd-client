"""Tests for ExecutionDisplay notebook HTML."""

import json

import pytest

from deeporigin.platform.execution_display import (
    ExecutionDisplay,
    _count_workflow_children_from_progress_report,
    _parse_complete_from_progress_report,
    _workflow_subjob_completes_from_progress_report,
)


def test_from_dto_maps_fields_and_complete() -> None:
    """from_dto reads ids, status, name, and complete from progress JSON."""
    dto = {
        "executionId": "e1-uuid",
        "status": "Running",
        "name": "my-run",
        "progressReport": json.dumps({"complete": 42, "other": 1}),
    }
    display = ExecutionDisplay.from_dto(dto)
    assert display.execution_id == "e1-uuid"
    assert display.status == "Running"
    assert display.name == "my-run"
    assert display.complete == pytest.approx(42)
    assert display.tool_key is None
    assert display.tool_version is None


def test_from_dto_maps_tool_key_and_version() -> None:
    """from_dto reads tool key and version from the ``tool`` object."""
    dto = {
        "executionId": "e1",
        "status": "Running",
        "tool": {"key": "deeporigin.bulk-docking", "version": "0.8.2"},
        "progressReport": None,
    }
    display = ExecutionDisplay.from_dto(dto)
    assert display.tool_key == "deeporigin.bulk-docking"
    assert display.tool_version == "0.8.2"


def test_from_dto_raises_without_execution_id() -> None:
    """from_dto requires executionId."""
    with pytest.raises(ValueError, match="executionId"):
        ExecutionDisplay.from_dto({"status": "Running"})


@pytest.mark.parametrize(
    ("progress_report", "expected_indeterminate"),
    [
        (None, True),
        (json.dumps({"complete": 50}), False),
    ],
    ids=["complete_0_indeterminate", "complete_50_determinate"],
)
def test_render_html_progress_bar_by_complete(
    progress_report: str | None,
    expected_indeterminate: bool,
) -> None:
    """Progress bar is indeterminate at 0% and determinate when ``complete`` > 0."""
    dto = {
        "executionId": "e1",
        "status": "Running",
        "progressReport": progress_report,
    }
    html = ExecutionDisplay.from_dto(dto).render_html()
    if expected_indeterminate:
        assert "progress-bar-striped" in html
        assert "progress-bar-animated" in html
        assert "w-100" in html
    else:
        assert "50%" in html
        assert "progress-bar-striped" not in html
        assert 'style="width: 50' in html


@pytest.mark.parametrize(
    ("status", "expected_bg_class", "expect_progress_bar"),
    [
        ("Completed", "bg-success", False),
        ("Failed", "bg-danger", False),
        ("Quoted", "bg-secondary", False),
        ("Running", "bg-primary", True),
    ],
)
def test_render_html_status_badge_colors(
    status: str,
    expected_bg_class: str,
    expect_progress_bar: bool,
) -> None:
    """Footer status uses Bootstrap badges with contextual colors."""
    dto = {
        "executionId": "e1",
        "status": status,
        "progressReport": None,
    }
    html = ExecutionDisplay.from_dto(dto).render_html()
    assert expected_bg_class in html
    assert "badge" in html
    display_status = "Completed" if status == "Succeeded" else status
    assert display_status in html
    if expect_progress_bar:
        assert 'role="progressbar"' in html
    else:
        assert 'role="progressbar"' not in html


def test_render_html_displays_completed_for_legacy_succeeded_dto() -> None:
    """Legacy Succeeded DTOs render the Completed user-facing badge."""
    dto = {
        "executionId": "e1",
        "status": "Succeeded",
        "progressReport": None,
    }
    html = ExecutionDisplay.from_dto(dto).render_html()
    assert "Completed" in html
    assert "Succeeded" not in html


def test_render_html_escapes_injection() -> None:
    """User-controlled fields are HTML-escaped."""
    dto = {
        "executionId": "e1",
        "status": "<script>alert(1)</script>",
        "name": "<img src=x onerror=alert(1)>",
        "progressReport": json.dumps({"complete": 0}),
    }
    html = ExecutionDisplay.from_dto(dto).render_html()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img" not in html


def test_will_auto_update_adds_spinner() -> None:
    """Live updates add a spinner only when requested."""
    dto = {"executionId": "e1", "status": "Running", "progressReport": None}
    html_off = ExecutionDisplay.from_dto(dto).render_html(will_auto_update=False)
    html_on = ExecutionDisplay.from_dto(dto).render_html(will_auto_update=True)
    assert "spinner-border" not in html_off
    assert "spinner-border" in html_on
    assert "Live updates" in html_on


def test_parse_complete_clamps() -> None:
    """Completion is clamped to 0–100."""
    assert _parse_complete_from_progress_report(
        json.dumps({"complete": 150})
    ) == pytest.approx(100)
    assert _parse_complete_from_progress_report(
        json.dumps({"complete": -5})
    ) == pytest.approx(0)


def test_from_pending_shows_notice_and_omits_execution_id_row() -> None:
    """Pending state explains why there is no ID; header uses name; no ID under bar."""
    html = ExecutionDisplay.from_pending(name="My job", status=None).render_html()
    assert "No platform execution ID yet" in html
    assert "<dt" not in html
    assert "fw-semibold" in html
    assert "My job" in html
    assert "New" in html
    assert 'role="progressbar"' not in html


def test_card_header_shows_tool_key_and_version() -> None:
    """Tool key and version are rendered under the title in the card header."""
    html = ExecutionDisplay.from_dto(
        {
            "executionId": "e1",
            "status": "Running",
            "name": "Run",
            "tool": {"key": "deeporigin.foo-fake-tool", "version": "0.2.37"},
            "progressReport": None,
        }
    ).render_html()
    assert "deeporigin.foo-fake-tool" in html
    assert "v0.2.37" in html
    assert "card-header" in html


def test_from_pending_passes_tool_metadata() -> None:
    """from_pending can show tool key/version before an execution exists."""
    html = ExecutionDisplay.from_pending(
        name="Prep",
        status=None,
        tool_key="deeporigin.system-prep",
        tool_version="0.7.6",
    ).render_html()
    assert "deeporigin.system-prep" in html
    assert "v0.7.6" in html


def test_card_header_uses_name_else_execution_id() -> None:
    """Header is the execution name when set, otherwise the execution id."""
    with_name = ExecutionDisplay.from_dto(
        {
            "executionId": "uuid-aaa",
            "status": "Running",
            "name": "Docking run",
            "progressReport": None,
        }
    ).render_html()
    assert "Docking run" in with_name
    assert "uuid-aaa" in with_name

    no_name = ExecutionDisplay.from_dto(
        {
            "executionId": "uuid-bbb",
            "status": "Running",
            "progressReport": None,
        }
    ).render_html()
    assert "uuid-bbb" in no_name


def test_execution_id_shown_below_progress_bar() -> None:
    """When an execution id exists, it appears under the progress bar."""
    html = ExecutionDisplay.from_dto(
        {
            "executionId": "exec-under-bar",
            "status": "Running",
            "name": "Named",
            "progressReport": None,
        }
    ).render_html()
    # After progress markup, id line should include the same id
    bar_end = html.find("progressbar")
    id_line = html.find("exec-under-bar")
    assert bar_end != -1 and id_line != -1
    assert id_line > bar_end


def test_from_dto_dict_progress_report() -> None:
    """progressReport may already be a dict."""
    dto = {
        "executionId": "x",
        "status": "Running",
        "progressReport": {"complete": 33},
    }
    display = ExecutionDisplay.from_dto(dto)
    assert display.complete == pytest.approx(33)


def test_parse_complete_batches_averages_sub_job_completes() -> None:
    """Batched progress (dict of workflow id -> {complete}) uses mean complete."""
    batched = {
        "workflow-a-1": {"complete": 0},
        "workflow-a-2": {"complete": 0},
        "workflow-a-3": {"complete": 100},
        "workflow-a-4": {"complete": 100},
    }
    assert _parse_complete_from_progress_report(batched) == pytest.approx(50.0)
    assert _parse_complete_from_progress_report(json.dumps(batched)) == pytest.approx(
        50.0
    )


def test_parse_complete_flat_complete_not_confused_with_batch() -> None:
    """Single-key flat ``{complete: n}`` still uses top-level complete."""
    assert _parse_complete_from_progress_report({"complete": 42}) == pytest.approx(42)


def test_parse_complete_mixed_batch_falls_back_to_top_level() -> None:
    """If not every top-level value is a dict with ``complete``, use flat ``complete``."""
    assert _parse_complete_from_progress_report(
        {"sub": {"complete": 100}, "complete": 7}
    ) == pytest.approx(7)


def test_count_workflow_children_matches_workflow_keys() -> None:
    """Keys containing ``workflow`` (case-insensitive) are counted as child slots."""
    pr = {
        "workflow-ppu1d9qkoqdkufjnck1e9-1597457250": {"complete": 0},
        "workflow-ppu1d9qkoqdkufjnck1e9-2853961406": {"complete": 0},
        "other": {"complete": 50},
    }
    assert _count_workflow_children_from_progress_report(pr) == 2
    assert _count_workflow_children_from_progress_report(json.dumps(pr)) == 2
    assert _count_workflow_children_from_progress_report(None) == 0


def test_from_dto_sets_workflow_child_count() -> None:
    """from_dto records how many workflow batch keys are in progressReport."""
    batched = {
        "workflow-a": {"complete": 0},
        "workflow-b": {"complete": 0},
        "workflow-c": {"complete": 0},
        "workflow-d": {"complete": 0},
    }
    display = ExecutionDisplay.from_dto(
        {"executionId": "e1", "status": "Running", "progressReport": batched}
    )
    assert display.workflow_child_count == 4


def test_render_html_workflow_footer_badge() -> None:
    """Footer shows WORKFLOW (Nx) when progressReport has workflow child keys."""
    dto = {
        "executionId": "e1",
        "status": "Running",
        "progressReport": {
            "workflow-x-1": {"complete": 0},
            "workflow-x-2": {"complete": 0},
            "workflow-x-3": {"complete": 0},
        },
    }
    html = ExecutionDisplay.from_dto(dto).render_html()
    assert "WORKFLOW (3x)" in html
    assert "font-variant: small-caps" in html
    assert "bg-secondary-subtle" in html


def test_render_html_no_workflow_badge_when_absent() -> None:
    """No workflow badge when there are no workflow-* keys."""
    html = ExecutionDisplay.from_dto(
        {
            "executionId": "e1",
            "status": "Running",
            "progressReport": json.dumps({"complete": 10}),
        }
    ).render_html()
    assert "WORKFLOW (" not in html


def test_workflow_subjob_completes_sorted_and_ignores_non_workflow_keys() -> None:
    """Per-workflow completes are sorted by key; non-workflow keys are omitted."""
    pr = {
        "workflow-b": {"complete": 25},
        "other": {"complete": 99},
        "workflow-a": {"complete": 50},
    }
    assert _workflow_subjob_completes_from_progress_report(pr) == (50.0, 25.0)


def test_render_html_one_progress_bar_per_workflow_subjob_at_zero() -> None:
    """Two workflow children at 0% render two indeterminate progress bars."""
    dto = {
        "executionId": "e1",
        "status": "Running",
        "progressReport": {
            "workflow-xdkse3iq171637hcwuo8x-643413961": {"complete": 0},
            "workflow-xdkse3iq171637hcwuo8x-2789035895": {"complete": 0},
        },
    }
    html = ExecutionDisplay.from_dto(dto).render_html()
    assert html.count('role="progressbar"') == 2
    assert html.count("progress-bar-striped") == 2
    assert html.count("progress-bar-animated") == 2


def test_render_html_one_progress_bar_per_workflow_subjob_mixed_complete() -> None:
    """Each workflow child gets its own bar with independent completion."""
    dto = {
        "executionId": "e1",
        "status": "Running",
        "progressReport": {
            "workflow-a": {"complete": 0},
            "workflow-b": {"complete": 50},
        },
    }
    html = ExecutionDisplay.from_dto(dto).render_html()
    assert html.count('role="progressbar"') == 2
    assert "50%" in html
    assert html.count("progress-bar-striped") == 1


def test_render_html_workflow_multi_bar_ignores_non_workflow_keys() -> None:
    """Multi-bar mode shows only workflow-* keys, not other top-level entries."""
    dto = {
        "executionId": "e1",
        "status": "Running",
        "progressReport": {
            "workflow-ppu1d9qkoqdkufjnck1e9-1597457250": {"complete": 0},
            "workflow-ppu1d9qkoqdkufjnck1e9-2853961406": {"complete": 0},
            "other": {"complete": 50},
        },
    }
    html = ExecutionDisplay.from_dto(dto).render_html()
    assert html.count('role="progressbar"') == 2


def test_render_html_workflow_bar_order_follows_sorted_keys() -> None:
    """Progress bars appear in alphabetical order of workflow keys."""
    dto = {
        "executionId": "e1",
        "status": "Running",
        "progressReport": {
            "workflow-z-last": {"complete": 80},
            "workflow-a-first": {"complete": 20},
        },
    }
    display = ExecutionDisplay.from_dto(dto)
    assert display.workflow_subjob_completes == (20.0, 80.0)
    html = display.render_html()
    first_pos = html.find("20%")
    second_pos = html.find("80%")
    assert first_pos != -1 and second_pos != -1
    assert first_pos < second_pos


def test_render_html_v2_progress_tree() -> None:
    """v2 ``progressReport`` trees render the HTML progress tree, not bootstrap bars."""
    import json
    from pathlib import Path

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "executions"
        / "rbfe-v2-progress-tree.json"
    )
    dto = json.loads(fixture.read_text(encoding="utf-8"))
    html = ExecutionDisplay.from_dto(dto).render_html()

    assert "do-progress-tree" in html
    assert "prepare-inputs" in html
    assert "progress-bar" not in html


def test_render_html_v2_tree_visible_when_failed() -> None:
    """Failed executions still show the v2 progress tree."""
    dto = {
        "executionId": "e-failed",
        "status": "Failed",
        "progressReport": {
            "id": "wf-1",
            "displayName": "workflow-root",
            "status": "Failed",
            "message": "top-level failure",
            "children": [
                {
                    "id": "step-1",
                    "displayName": "child-step",
                    "status": "Succeeded",
                    "children": [],
                }
            ],
        },
    }
    html = ExecutionDisplay.from_dto(dto).render_html()

    assert "do-progress-tree" in html
    assert "workflow-root" in html
    assert "progress-bar" not in html


def test_render_html_legacy_running_still_uses_bootstrap_bar() -> None:
    """Legacy ``complete`` progress reports keep the Bootstrap progress bar."""
    dto = {
        "executionId": "e1",
        "status": "Running",
        "progressReport": {"complete": 55},
    }
    html = ExecutionDisplay.from_dto(dto).render_html()

    assert "progress-bar" in html
    assert "do-progress-tree" not in html
    assert "55%" in html
