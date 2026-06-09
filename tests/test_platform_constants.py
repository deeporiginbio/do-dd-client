"""Tests for platform execution status constants."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from deeporigin.drug_discovery.abfe import ABFE
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.platform.constants import SUCCESS_STATES, TERMINAL_STATES


def test_completed_is_terminal_and_success_state() -> None:
    """``Completed`` is treated as a successful terminal execution status."""
    assert "Completed" in TERMINAL_STATES
    assert "Completed" in SUCCESS_STATES
    assert "Succeeded" in TERMINAL_STATES
    assert "Succeeded" in SUCCESS_STATES


@patch("deeporigin.drug_discovery.notebook_watch_mixin.display")
@patch("deeporigin.drug_discovery.notebook_watch_mixin.update_display")
def test_watch_stops_when_status_is_completed(
    mock_update_display,
    mock_display,
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
        "tool": {"key": "deeporigin.abfe", "version": "latest"},
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

    with patch.object(abfe, "_render_execution_html", return_value="<html>x</html>"):
        asyncio.run(abfe._watch_until_terminal(interval=0.001))

    assert mock_client.executions.get.call_count >= 2
    assert abfe.status == "Completed"
    assert mock_update_display.call_count >= 1
