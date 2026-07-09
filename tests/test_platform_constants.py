"""Tests for platform execution status constants and helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from deeporigin.drug_discovery.abfe import ABFE
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.platform.constants import (
    ALLOWED_STATUS_TRANSITIONS,
    CANONICAL_SUCCESS_STATUS,
    LEGACY_SUCCEEDED_STATUS,
    TERMINAL_STATES,
    display_platform_status,
    is_success_status,
    normalize_platform_status,
)


def test_normalize_platform_status_maps_succeeded_to_completed() -> None:
    """Legacy Succeeded is normalized to Completed."""
    assert normalize_platform_status("Succeeded") == "Completed"
    assert normalize_platform_status("Completed") == "Completed"
    assert normalize_platform_status("Running") == "Running"
    assert normalize_platform_status(None) is None


def test_is_success_status_accepts_completed_and_succeeded() -> None:
    """Terminal-success checks accept both canonical and legacy values."""
    assert is_success_status("Completed") is True
    assert is_success_status("Succeeded") is True
    assert is_success_status("Running") is False
    assert is_success_status(None) is False


def test_display_platform_status_shows_completed_for_legacy_succeeded() -> None:
    """User-facing labels always use Completed for success."""
    assert display_platform_status("Succeeded") == "Completed"
    assert display_platform_status("Completed") == "Completed"
    assert display_platform_status("Running") == "Running"
    assert display_platform_status(None) == "New"
    assert display_platform_status("") == "New"


def test_terminal_states_include_completed_and_legacy_succeeded() -> None:
    """Terminal set includes canonical Completed and legacy Succeeded."""
    assert "Completed" in TERMINAL_STATES
    assert "Succeeded" in TERMINAL_STATES
    assert "Failed" in TERMINAL_STATES


def test_running_transitions_to_completed() -> None:
    """Running may transition to Completed (not legacy Succeeded)."""
    assert CANONICAL_SUCCESS_STATUS in ALLOWED_STATUS_TRANSITIONS["Running"]
    assert LEGACY_SUCCEEDED_STATUS not in ALLOWED_STATUS_TRANSITIONS["Running"]
    assert ALLOWED_STATUS_TRANSITIONS["Completed"] == set()
    assert ALLOWED_STATUS_TRANSITIONS["Succeeded"] == set()


def test_watch_stops_when_status_is_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The notebook watch loop stops when sync reports ``Completed``."""
    ps = PreparedSystem(
        binding_xml_path="b.xml",
        solvation_xml_path="s.xml",
        system_pdb_path="p.pdb",
    )
    running = {
        "executionId": "exec-1",
        "status": "Running",
        "tool": {"key": "deeporigin.abfe-end-to-end", "version": "latest"},
        "userInputs": {},
        "userOutputs": {},
        "quotationResult": {},
    }
    completed = {
        **running,
        "status": "Completed",
    }

    mock_client = MagicMock()
    mock_client.executions.get.side_effect = [running, completed]

    abfe = ABFE(prepared_system=ps)
    abfe.client = mock_client
    abfe._id = running["executionId"]
    abfe._dto = running
    abfe.status = "Running"

    update_calls: list[object] = []
    monkeypatch.setattr(
        "deeporigin.drug_discovery.notebook_watch_mixin.display",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "deeporigin.drug_discovery.notebook_watch_mixin.update_display",
        lambda *args, **kwargs: update_calls.append(None),
    )
    monkeypatch.setattr(
        abfe,
        "_render_execution_html",
        lambda: "<html>x</html>",
    )

    asyncio.run(abfe._watch_until_terminal(interval=0.001))

    assert mock_client.executions.get.call_count >= 2
    assert abfe.status == "Completed"
    assert len(update_calls) >= 1
