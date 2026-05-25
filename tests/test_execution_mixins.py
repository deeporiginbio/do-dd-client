"""Tests for :mod:`deeporigin.drug_discovery.execution_mixins`."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import AsyncExecutableMixin
from deeporigin.utils.constants import TOOL_EXECUTION_POST_TIMEOUT_SECONDS


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


def test_execution_confirm_calls_platform_with_long_timeout_no_retry() -> None:
    """``confirm`` hits ``executions.confirm`` with 600s timeout and ``retry=False``."""
    client = MagicMock()
    job = _ConfirmableJob(client=client)
    job._id = "exec-quoted-1"
    job.status = "Quoted"

    job.confirm()

    client.executions.confirm.assert_called_once_with(
        "exec-quoted-1",
        timeout=TOOL_EXECUTION_POST_TIMEOUT_SECONDS,
        retry=False,
    )


def test_execution_confirm_requires_id() -> None:
    """``confirm`` raises when no platform execution id is set."""
    client = MagicMock()
    job = _ConfirmableJob(client=client)
    job.status = "Quoted"

    with pytest.raises(ValueError, match="no platform execution id"):
        job.confirm()

    client.executions.confirm.assert_not_called()


def test_execution_confirm_requires_quoted_status() -> None:
    """``confirm`` raises when status is not ``Quoted``."""
    client = MagicMock()
    job = _ConfirmableJob(client=client)
    job._id = "exec-1"
    job.status = "Created"

    with pytest.raises(ValueError, match="not 'Quoted'"):
        job.confirm()

    client.executions.confirm.assert_not_called()


def test_async_start_calls_start_impl_with_no_approve_amount() -> None:
    """``start()`` with no args forwards ``approve_amount=None`` to ``_start_impl``."""
    client = MagicMock()
    job = _AsyncJob(client=client)

    job.start()

    assert len(job._start_impl_calls) == 1
    assert job._start_impl_calls[0]["approve_amount"] is None


def test_async_start_quote_true_forwards_zero_approve_amount() -> None:
    """``start(quote=True)`` forwards ``approve_amount=0`` to ``_start_impl``."""
    client = MagicMock()
    job = _AsyncJob(client=client)

    job.start(quote=True)

    assert len(job._start_impl_calls) == 1
    assert job._start_impl_calls[0]["approve_amount"] == 0


def test_async_start_approve_amount_forwarded() -> None:
    """``start(approve_amount=50)`` forwards the value to ``_start_impl``."""
    client = MagicMock()
    job = _AsyncJob(client=client)

    job.start(approve_amount=50)

    assert len(job._start_impl_calls) == 1
    assert job._start_impl_calls[0]["approve_amount"] == 50


def test_async_start_rejects_non_none_status() -> None:
    """``start()`` raises when status is not ``None``."""
    client = MagicMock()
    job = _AsyncJob(client=client)
    job.status = "Running"

    with pytest.raises(ValueError, match="'Running'"):
        job.start()

    assert not job._start_impl_calls


def test_cancel_allows_data_ingesting_status() -> None:
    """``cancel()`` does not reject ``DataIngesting`` status."""
    client = MagicMock()
    client.executions.get.return_value = {
        "executionId": "exec-di",
        "tool": {"key": "deeporigin.test-tool", "version": "0.0.0"},
        "status": "Cancelled",
    }
    job = _AsyncJob(client=client)
    job._id = "exec-di"
    job.status = "DataIngesting"

    job.cancel()

    client.executions.cancel.assert_called_once_with("exec-di")
