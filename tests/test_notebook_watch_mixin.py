"""Tests for NotebookWatchMixin / ABFE watch_async."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from deeporigin.drug_discovery.abfe import ABFE
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem


def _minimal_dto(*, status: str, execution_id: str = "exec-1") -> dict:
    """Build a minimal execution DTO for sync() / Job.from_dto."""
    return {
        "executionId": execution_id,
        "status": status,
        "tool": {
            "key": "deeporigin.abfe-end-to-end",
            "version": "0.2.0",
        },
        "userInputs": {},
        "userOutputs": {},
        "quotationResult": {},
    }


def test_watch_async_raises_without_id():
    """watch_async requires a platform execution id."""
    ps = PreparedSystem(
        binding_xml_path="b.xml",
        solvation_xml_path="s.xml",
        system_pdb_path="p.pdb",
    )
    abfe = ABFE(prepared_system=ps)

    with pytest.raises(ValueError, match="id is None"):
        asyncio.run(abfe.watch_async())


@patch("deeporigin.drug_discovery.notebook_watch_mixin.display")
@patch("deeporigin.drug_discovery.notebook_watch_mixin.update_display")
def test_watch_async_terminal_immediately(mock_update_display, mock_display):
    """Already-terminal job shows static message and skips the poll loop."""
    ps = PreparedSystem(
        binding_xml_path="b.xml",
        solvation_xml_path="s.xml",
        system_pdb_path="p.pdb",
    )
    dto = _minimal_dto(status="Succeeded")
    mock_client = MagicMock()
    mock_client.executions.get_execution.return_value = dto

    abfe = ABFE(prepared_system=ps)
    abfe.client = mock_client
    abfe._id = dto["executionId"]
    abfe._execution_dto = dto
    abfe.status = "Succeeded"

    with patch.object(abfe, "_render_job_html", return_value="<html>done</html>"):
        asyncio.run(abfe.watch_async(interval=0.01))

    mock_display.assert_called()
    mock_update_display.assert_not_called()


@patch("deeporigin.drug_discovery.notebook_watch_mixin.display")
@patch("deeporigin.drug_discovery.notebook_watch_mixin.update_display")
def test_watch_async_polls_until_terminal(mock_update_display, mock_display):
    """watch_async updates the display until status becomes terminal."""
    ps = PreparedSystem(
        binding_xml_path="b.xml",
        solvation_xml_path="s.xml",
        system_pdb_path="p.pdb",
    )
    running = _minimal_dto(status="Running")
    succeeded = _minimal_dto(status="Succeeded")

    mock_client = MagicMock()
    mock_client.executions.get_execution.side_effect = [running, succeeded]

    abfe = ABFE(prepared_system=ps)
    abfe.client = mock_client
    abfe._id = running["executionId"]
    abfe._execution_dto = running
    abfe.status = "Running"

    with patch.object(abfe, "_render_job_html", return_value="<html>x</html>"):
        asyncio.run(abfe.watch_async(interval=0.001))

    assert mock_client.executions.get_execution.call_count >= 2
    assert mock_update_display.call_count >= 1


def test_stop_watching_does_not_raise_when_idle():
    """stop_watching is a no-op when no watch is active."""
    ps = PreparedSystem(
        binding_xml_path="b.xml",
        solvation_xml_path="s.xml",
        system_pdb_path="p.pdb",
    )
    abfe = ABFE(prepared_system=ps)
    abfe.stop_watching()


@patch("deeporigin.drug_discovery.notebook_watch_mixin.display")
@patch("deeporigin.drug_discovery.notebook_watch_mixin.update_display")
def test_watch_async_raises_when_dto_missing_after_sync(
    mock_update_display,
    mock_display,
):
    """If sync leaves no DTO, watch_async raises."""
    ps = PreparedSystem(
        binding_xml_path="b.xml",
        solvation_xml_path="s.xml",
        system_pdb_path="p.pdb",
    )
    mock_client = MagicMock()
    mock_client.executions.get_execution.return_value = None

    abfe = ABFE(prepared_system=ps)
    abfe.client = mock_client
    abfe._id = "exec-1"
    abfe._execution_dto = None

    with pytest.raises(ValueError, match="No execution data after sync"):
        asyncio.run(abfe.watch_async())


def test_watch_returns_task_without_blocking_watch_async():
    """watch returns a Task; watch_async runs asynchronously."""

    async def _run() -> None:
        ps = PreparedSystem(
            binding_xml_path="b.xml",
            solvation_xml_path="s.xml",
            system_pdb_path="p.pdb",
        )
        abfe = ABFE(prepared_system=ps)
        abfe._id = "exec-1"

        done = asyncio.Event()

        async def fake_watch(self, *, interval: float = 5.0) -> None:
            done.set()

        with patch.object(
            type(abfe),
            "watch_async",
            fake_watch,
        ):
            task = await abfe.watch()

        assert isinstance(task, asyncio.Task)
        await asyncio.wait_for(done.wait(), timeout=1.0)
        await task

    asyncio.run(_run())
