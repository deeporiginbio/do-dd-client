"""Tests for :mod:`deeporigin.drug_discovery.execution_mixins`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from deeporigin.drug_discovery import Konnektor, Ligand
from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import AsyncExecutableMixin

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


class _ConfirmableJob(Execution):
    """Minimal execution with :class:`Execution` ``confirm()`` for tests."""

    tool_key = "deeporigin.test-tool"
    tool_version = "0.0.0"

    def _make_payload(
        self, *, approve_amount: int | None, sync: bool
    ) -> dict[str, Any]:
        """Unused for ``confirm()``-only tests."""
        raise NotImplementedError


class _AsyncJob(Execution, AsyncExecutableMixin):
    """Async job used to test ``start()`` behaviour."""

    tool_key = "deeporigin.test-tool"
    tool_version = "0.0.0"
    _start_impl_calls: list[dict]

    def __init__(self, **kwargs: Any) -> None:
        """Initialise and reset call tracking."""
        super().__init__(**kwargs)
        self._start_impl_calls = []

    def _make_payload(
        self, *, approve_amount: int | None, sync: bool
    ) -> dict[str, Any]:
        """Unused for ``start()`` tests."""
        raise NotImplementedError

    def _start_impl(self, *, approve_amount: int | None = None, **kwargs: Any) -> None:
        """Record the call for assertions."""
        self._start_impl_calls.append({"approve_amount": approve_amount, **kwargs})


def test_execution_confirm_transitions_quoted_to_running(
    client: DeepOriginClient,
    registered_ligand: Ligand,
    registered_ligand_brd3: Ligand,
) -> None:
    """``confirm`` on a quoted execution transitions to Running via the mock server."""
    job = Konnektor(
        ligands=[registered_ligand, registered_ligand_brd3],
        client=client,
    )
    assert job.run(quote=True) is None
    assert job.status == "Quoted"
    assert job.id is not None

    job.confirm()

    assert job.status == "Running"
    assert job.dto is not None
    assert job.dto["status"] == "Running"


def test_execution_confirm_requires_id() -> None:
    """``confirm`` raises when no platform execution id is set."""
    job = _ConfirmableJob()
    job.status = "Quoted"

    with pytest.raises(ValueError, match="no platform execution id"):
        job.confirm()


def test_execution_confirm_requires_quoted_status() -> None:
    """``confirm`` raises when status is not ``Quoted``."""
    job = _ConfirmableJob()
    job._id = "exec-1"
    job.status = "Created"

    with pytest.raises(ValueError, match="not 'Quoted'"):
        job.confirm()


def test_async_start_calls_start_impl_with_no_approve_amount() -> None:
    """``start()`` with no args forwards ``approve_amount=None`` to ``_start_impl``."""
    job = _AsyncJob()

    job.start()

    assert len(job._start_impl_calls) == 1
    assert job._start_impl_calls[0]["approve_amount"] is None


def test_async_start_quote_true_forwards_zero_approve_amount() -> None:
    """``start(quote=True)`` forwards ``approve_amount=0`` to ``_start_impl``."""
    job = _AsyncJob()

    job.start(quote=True)

    assert len(job._start_impl_calls) == 1
    assert job._start_impl_calls[0]["approve_amount"] == 0


def test_async_start_approve_amount_forwarded() -> None:
    """``start(approve_amount=50)`` forwards the value to ``_start_impl``."""
    job = _AsyncJob()

    job.start(approve_amount=50)

    assert len(job._start_impl_calls) == 1
    assert job._start_impl_calls[0]["approve_amount"] == 50


def test_async_start_rejects_non_none_status() -> None:
    """``start()`` raises when status is not ``None``."""
    job = _AsyncJob()
    job.status = "Running"

    with pytest.raises(ValueError, match="'Running'"):
        job.start()

    assert not job._start_impl_calls
