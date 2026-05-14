"""Tests for :mod:`deeporigin.drug_discovery.execution_mixins`."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import AsyncExecutableMixin, QuoteMixin
from deeporigin.utils.constants import TOOL_EXECUTION_POST_TIMEOUT_SECONDS


class _ConfirmableJob(Execution, QuoteMixin):
    """Minimal execution with :class:`QuoteMixin` for ``confirm()`` tests."""

    tool_key = "deeporigin.test-tool"
    tool_version = "0.0.0"


class _AsyncQuotedJob(Execution, QuoteMixin, AsyncExecutableMixin):
    """Async job used to assert ``start()`` delegates to ``confirm()``."""

    tool_key = "deeporigin.test-tool"
    tool_version = "0.0.0"

    def _start_impl(self, **kwargs: Any) -> None:
        """No-op for tests that only exercise the ``Quoted`` branch."""
        raise AssertionError("_start_impl should not run in these tests")


def test_quote_mixin_confirm_calls_platform_with_long_timeout_no_retry() -> None:
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


def test_quote_mixin_confirm_requires_id() -> None:
    """``confirm`` raises when no platform execution id is set."""
    client = MagicMock()
    job = _ConfirmableJob(client=client)
    job.status = "Quoted"

    with pytest.raises(ValueError, match="no platform execution id"):
        job.confirm()

    client.executions.confirm.assert_not_called()


def test_quote_mixin_confirm_requires_quoted_status() -> None:
    """``confirm`` raises when status is not ``Quoted``."""
    client = MagicMock()
    job = _ConfirmableJob(client=client)
    job._id = "exec-1"
    job.status = "Created"

    with pytest.raises(ValueError, match="not 'Quoted'"):
        job.confirm()

    client.executions.confirm.assert_not_called()


def test_async_start_when_quoted_calls_confirm_then_sync() -> None:
    """``start()`` on a ``Quoted`` job uses :meth:`QuoteMixin.confirm` then ``sync``."""
    client = MagicMock()
    job = _AsyncQuotedJob(client=client)
    job._id = "exec-1"
    job.status = "Quoted"
    sync_mock = MagicMock()
    job.sync = sync_mock

    job.start()

    client.executions.confirm.assert_called_once_with(
        "exec-1",
        timeout=TOOL_EXECUTION_POST_TIMEOUT_SECONDS,
        retry=False,
    )
    sync_mock.assert_called_once()


def test_quote_setup_error_mentions_confirm() -> None:
    """Re-quoting a ``Quoted`` job tells the user to call ``confirm()``."""
    client = MagicMock()
    job = _ConfirmableJob(client=client)
    job.status = "Quoted"

    with pytest.raises(ValueError, match=r"confirm\(\)"):
        job.quote()
