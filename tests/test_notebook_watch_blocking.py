"""Tests for NotebookWatchMixin.watch blocking mode and JOB_WATCH_BLOCK."""

import asyncio
from unittest.mock import patch

from deeporigin.drug_discovery.abfe import ABFE
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.utils.constants import JOB_WATCH_BLOCK_ENV


def _abfe_with_id() -> ABFE:
    """Minimal ABFE instance with a platform execution id."""
    ps = PreparedSystem(
        binding_xml_path="b.xml",
        solvation_xml_path="s.xml",
        system_pdb_path="p.pdb",
    )
    abfe = ABFE(prepared_system=ps)
    abfe._id = "exec-1"
    return abfe


def test_watch_should_block_from_kwarg() -> None:
    """Explicit blocking=True enables inline watch."""
    abfe = _abfe_with_id()
    assert abfe._watch_should_block(blocking=True) is True
    assert abfe._watch_should_block(blocking=False) is False


def test_watch_should_block_from_env(monkeypatch) -> None:
    """JOB_WATCH_BLOCK enables blocking when the kwarg is False."""
    monkeypatch.setenv(JOB_WATCH_BLOCK_ENV, "1")
    abfe = _abfe_with_id()
    assert abfe._watch_should_block(blocking=False) is True


def test_watch_blocking_awaits_loop() -> None:
    """watch(blocking=True) runs the loop inline and returns None."""

    async def _run() -> None:
        abfe = _abfe_with_id()
        entered = asyncio.Event()

        async def fake_watch(self, *, interval: float = 5.0) -> None:
            entered.set()

        with patch.object(type(abfe), "_watch_until_terminal", fake_watch):
            result = await abfe.watch(blocking=True)

        assert result is None
        assert entered.is_set()

    asyncio.run(_run())


def test_watch_non_blocking_returns_task() -> None:
    """Default watch returns a Task without awaiting the loop."""

    async def _run() -> None:
        abfe = _abfe_with_id()
        done = asyncio.Event()

        async def fake_watch(self, *, interval: float = 5.0) -> None:
            done.set()

        with patch.object(type(abfe), "_watch_until_terminal", fake_watch):
            task = await abfe.watch()

        assert isinstance(task, asyncio.Task)
        await asyncio.wait_for(done.wait(), timeout=1.0)
        await task

    asyncio.run(_run())


def test_watch_env_block_awaits_loop(monkeypatch) -> None:
    """JOB_WATCH_BLOCK=1 makes watch() blocking without blocking=True."""
    monkeypatch.setenv(JOB_WATCH_BLOCK_ENV, "yes")

    async def _run() -> None:
        abfe = _abfe_with_id()
        entered = asyncio.Event()

        async def fake_watch(self, *, interval: float = 5.0) -> None:
            entered.set()

        with patch.object(type(abfe), "_watch_until_terminal", fake_watch):
            result = await abfe.watch()

        assert result is None
        assert entered.is_set()

    asyncio.run(_run())
