"""Tests that notebook error overlays escape untrusted message text."""

from __future__ import annotations

from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin


def test_compose_error_overlay_html_escapes_message() -> None:
    """Watch overlay HTML must not embed raw script from error strings."""
    mixin = object.__new__(NotebookWatchMixin)
    banner = mixin._compose_error_overlay_html(
        message='<script>alert("x")</script>',
    )

    assert "<script>" not in banner
    assert "&lt;script&gt;" in banner
