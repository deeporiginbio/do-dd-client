"""Tests for :class:`~deeporigin.platform.user_logs.UserLogs`."""

from __future__ import annotations

import pytest

from deeporigin.platform.client import DeepOriginClient

# Dev fixture: execution that has user_logs rows (verified against api.dev).
_DEV_USER_LOGS_EXECUTION_ID = "63e61f69-55be-465c-83be-18c5cf511bdf"


def test_user_logs_search_by_execution_id_local(client: DeepOriginClient) -> None:
    """Mock store rows use ``execution_id``; search must find them by tools id."""

    assert client.env == "local"
    ul = client.user_logs
    assert ul is not None
    out = ul.search(execution_id="MOCK-USER-LOGS-CJ-ID", limit=10)
    rows = out.get("data") or []
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0].get("execution_id") == "MOCK-USER-LOGS-CJ-ID"


def test_user_logs_search_dev_known_execution_lv1(client: DeepOriginClient) -> None:
    """Regression: ``user_logs`` search filters the ``execution_id`` column."""

    if client.env == "local":
        pytest.skip("dev/staging/prod only — uses real user_logs rows")

    ul = client.user_logs
    assert ul is not None
    out = ul.search(execution_id=_DEV_USER_LOGS_EXECUTION_ID, limit=50)
    rows = out.get("data") or []
    assert isinstance(rows, list)
    assert len(rows) >= 1, (
        f"expected user_logs for execution {_DEV_USER_LOGS_EXECUTION_ID!r} on "
        f"{client.env}; got empty data"
    )
    for row in rows:
        assert row.get("execution_id") == _DEV_USER_LOGS_EXECUTION_ID
