"""Tests for :class:`deeporigin.platform.user_logs.UserLogs` API wrapper."""

from __future__ import annotations

from typing import Any

import pytest

from deeporigin.platform.client import DeepOriginClient


def _capture_post_json(client: DeepOriginClient) -> dict[str, Any]:
    """Replace ``post_json`` and return a dict that receives endpoint and body."""

    captured: dict[str, Any] = {}

    def mock_post_json(
        endpoint: str,
        *,
        body: dict[str, Any],
        **kwargs: object,
    ) -> dict[str, Any]:
        captured["endpoint"] = endpoint
        captured["body"] = body
        return {"data": []}

    client.post_json = mock_post_json  # type: ignore[method-assign]
    return captured


def test_user_logs_search_maps_compute_job_id_to_execution_id_column() -> None:
    """Data-platform ``user_logs`` search accepts ``execution_id``, not ``compute_job_id``."""

    DeepOriginClient.close_all()
    client = DeepOriginClient.from_local()
    ul = client.user_logs
    assert ul is not None

    cap = _capture_post_json(client)
    jid = "2b7ae1bc-d3a3-4ad9-8a0e-53699f936203"
    ul.search(compute_job_id=jid)

    assert cap["endpoint"] == f"/data-platform/{client.org_key}/user_logs/search"
    props = cap["body"]["filter"]["props"]
    assert props == [{"column": "execution_id", "op": "eq", "value": jid}]
