"""Tests for notebook utility functions."""

import base64
import warnings

from IPython.display import IFrame
import pytest

from deeporigin.utils.notebook import (
    _iframe_markup_for_html_document,
    _iframe_src_for_html_document,
    render_html,
    render_progress_bar,
    show_progress_bar,
)


def test_render_progress_bar_basic():
    """Test basic progress bar rendering."""
    html = render_progress_bar(completed=5, total=10, failed=1)

    assert isinstance(html, str)
    assert "progress" in html
    assert "Completed: 4" in html  # passed = completed - failed = 5 - 1 = 4
    assert "Failed: 1" in html
    assert "Remaining: 5" in html  # pending = total - completed = 10 - 5 = 5


def test_render_progress_bar_with_title():
    """Test progress bar rendering with title."""
    html = render_progress_bar(completed=3, total=10, failed=0, title="Test Progress")

    assert "<h3>Test Progress</h3>" in html
    assert "progress" in html


def test_render_progress_bar_with_body_text():
    """Test progress bar rendering with body text."""
    html = render_progress_bar(
        completed=3, total=10, failed=0, body_text="Processing items..."
    )

    assert "Processing items..." in html
    assert "progress" in html


def test_render_progress_bar_animated_when_starting():
    """Test that animated striped bar is used when completed=0 and failed=0."""
    html = render_progress_bar(completed=0, total=10, failed=0)

    assert isinstance(html, str)
    assert "progress-bar-striped" in html
    assert "progress-bar-animated" in html
    assert "width: 100%" in html
    assert 'aria-label="Starting"' in html
    # Should not have the regular progress bars
    assert "bg-success" not in html
    assert "bg-danger" not in html
    assert "bg-secondary" not in html


def test_render_progress_bar_not_animated_when_completed():
    """Test that regular bars are used when progress has been made."""
    html = render_progress_bar(completed=1, total=10, failed=0)

    assert "progress-bar-striped" not in html
    assert "progress-bar-animated" not in html
    assert "bg-success" in html
    assert "bg-secondary" in html


def test_render_progress_bar_not_animated_when_failed():
    """Test that regular bars are used when there are failures."""
    html = render_progress_bar(completed=0, total=10, failed=1)

    assert "progress-bar-striped" not in html
    assert "progress-bar-animated" not in html
    assert "bg-danger" in html


def test_render_progress_bar_completed_all():
    """Test progress bar when all tasks are completed."""
    html = render_progress_bar(completed=10, total=10, failed=2)

    assert "Completed: 8" in html  # passed = 10 - 2 = 8
    assert "Failed: 2" in html
    assert "Remaining: 0" in html  # pending = 10 - 10 = 0


def test_render_progress_bar_invalid_total():
    """Test that ValueError is raised for invalid total."""
    with pytest.raises(ValueError, match="Total must be a positive integer"):
        render_progress_bar(completed=5, total=0, failed=0)

    with pytest.raises(ValueError, match="Total must be a positive integer"):
        render_progress_bar(completed=5, total=-1, failed=0)


def test_render_progress_bar_percentages():
    """Test that progress bar percentages are calculated correctly."""
    html = render_progress_bar(completed=5, total=10, failed=1)

    # passed = 4, failed = 1, pending = 5
    # percentages: 40%, 10%, 50%
    assert "width: 40.0%" in html or "width: 40%" in html
    assert "width: 10.0%" in html or "width: 10%" in html
    assert "width: 50.0%" in html or "width: 50%" in html


def test_show_progress_bar():
    """Test that show_progress_bar calls render_progress_bar correctly."""
    # This test verifies the function doesn't crash
    # We can't easily test display() without mocking
    try:
        show_progress_bar(completed=5, total=10, failed=1, title="Test")
    except Exception as e:
        # If IPython is not available, that's okay for this test
        if "IPython" not in str(type(e).__name__):
            raise


def test_iframe_src_uses_base64_data_uri() -> None:
    """HTML documents embed via base64 data URI, not srcdoc."""
    html = "<!DOCTYPE html><html><body>hi</body></html>"
    src = _iframe_src_for_html_document(html)

    assert src.startswith("data:text/html;charset=utf-8;base64,")
    decoded = base64.b64decode(src.split(",", 1)[1]).decode("utf-8")
    assert decoded == html


def test_iframe_markup_allows_scripts() -> None:
    """Iframe sandbox must allow scripts for Mol* and other JS viewers."""
    markup = _iframe_markup_for_html_document("<html></html>", height=400)

    assert 'sandbox="allow-scripts allow-same-origin"' in markup
    assert "srcdoc=" not in markup
    assert "data:text/html;charset=utf-8;base64," in markup


def test_iframe_markup_includes_bridge_id() -> None:
    """Comm-bridge iframes expose a stable id for the postMessage script."""
    markup = _iframe_markup_for_html_document(
        "<html></html>",
        height=400,
        bridge_id="abc",
    )

    assert 'id="do-bridge-abc"' in markup
    assert 'data-bridge-id="abc"' in markup


def test_render_html_displays_iframe_without_warning(monkeypatch) -> None:
    """Jupyter display must use IFrame so IPython does not warn about HTML iframes."""
    displayed: list[object] = []

    def fake_display(obj: object) -> object:
        """Capture the object passed to IPython display."""
        displayed.append(obj)
        return obj

    monkeypatch.setattr("deeporigin.utils.notebook.display", fake_display)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        render_html("<html></html>", height=400)

    assert len(displayed) == 1
    assert isinstance(displayed[0], IFrame)
    assert not any("IFrame instead" in str(warning.message) for warning in caught)
