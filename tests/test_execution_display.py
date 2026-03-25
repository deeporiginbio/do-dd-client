"""Tests for ExecutionDisplay notebook HTML."""

import json

import pytest

from deeporigin.platform.execution_display import (
    ExecutionDisplay,
    _parse_complete_from_progress_report,
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
    assert display.complete == 42.0


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
    ("status", "expected_bg_class"),
    [
        ("Succeeded", "bg-success"),
        ("Failed", "bg-danger"),
        ("Quoted", "bg-secondary"),
        ("Running", "bg-primary"),
    ],
)
def test_render_html_status_badge_colors(
    status: str,
    expected_bg_class: str,
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
    assert status in html


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
    assert _parse_complete_from_progress_report(json.dumps({"complete": 150})) == 100.0
    assert _parse_complete_from_progress_report(json.dumps({"complete": -5})) == 0.0


def test_from_pending_shows_notice_and_omits_execution_id_row() -> None:
    """Pending state explains why there is no ID; header uses name; no ID under bar."""
    html = ExecutionDisplay.from_pending(name="My job", status=None).render_html()
    assert "No platform execution ID yet" in html
    assert "<dt" not in html
    assert "<strong>My job</strong>" in html
    assert "New" in html


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
    assert "<strong>Docking run</strong>" in with_name
    assert "uuid-aaa" in with_name

    no_name = ExecutionDisplay.from_dto(
        {
            "executionId": "uuid-bbb",
            "status": "Running",
            "progressReport": None,
        }
    ).render_html()
    assert "<strong>uuid-bbb</strong>" in no_name


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
    assert display.complete == 33.0
