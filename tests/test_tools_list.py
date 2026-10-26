"""Tests for :meth:`deeporigin.platform.tools.Tools.list` on old and new platforms."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from deeporigin.platform.tools import Tools
from deeporigin.utils.constants import (
    TOOL_DEFINITIONS_LIST_ACCEPT_HEADER,
    TOOL_DEFINITIONS_LIST_PAGE_SIZE,
)

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


class _FakeClient:
    """Answers ``get_json`` from a queue and records each call."""

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get_json(self, path: str, **kwargs: Any) -> Any:
        self.calls.append({"path": path, **kwargs})
        return self.responses.pop(0)


def _rows(n: int, start: int = 0, enabled: bool = True) -> list[dict]:
    """Return *n* tool definition rows named ``tool-{start}`` onwards."""
    return [
        {"key": f"tool-{i}", "version": "1.0.0", "enabled": enabled}
        for i in range(start, start + n)
    ]


def test_tools_list_reads_every_v2_page() -> None:
    """The v2 list is followed page by page until ``count`` rows are read."""
    size = TOOL_DEFINITIONS_LIST_PAGE_SIZE
    fake = _FakeClient(
        {"count": size + 3, "data": _rows(size)},
        {"count": size + 3, "data": _rows(3, start=size)},
    )

    rows = Tools(fake).list()  # type: ignore[arg-type]

    assert len(rows) == size + 3
    assert [c["params"]["page"] for c in fake.calls] == [0, 1]
    assert all(
        c["headers"] == {"Accept": TOOL_DEFINITIONS_LIST_ACCEPT_HEADER}
        and c["params"]["pageSize"] == size
        and "filter" not in c["params"]
        for c in fake.calls
    )


def test_tools_list_stops_on_an_empty_page() -> None:
    """An empty page ends the loop even when ``count`` says more rows exist."""
    fake = _FakeClient({"count": 50, "data": _rows(2)}, {"count": 50, "data": []})

    assert len(Tools(fake).list()) == 2  # type: ignore[arg-type]
    assert len(fake.calls) == 2


def test_tools_list_accepts_an_old_platform_bare_array() -> None:
    """A platform without the v2 list returns the whole registry in one bare array."""
    registry = _rows(3) + _rows(2, start=3, enabled=False)
    fake = _FakeClient(registry)

    assert Tools(fake).list() == registry  # type: ignore[arg-type]
    assert len(fake.calls) == 1


def test_tools_list_enabled_filter_is_sent_and_applied_locally() -> None:
    """``enabled`` goes to the server, and is applied again for old platforms."""
    old_platform = _FakeClient(_rows(2) + _rows(1, start=2, enabled=False))

    enabled = Tools(old_platform).list(enabled=True)  # type: ignore[arg-type]
    old_platform.responses.append(_rows(2) + _rows(1, start=2, enabled=False))
    disabled = Tools(old_platform).list(enabled=False)  # type: ignore[arg-type]

    assert [r["key"] for r in enabled] == ["tool-0", "tool-1"]
    assert [r["key"] for r in disabled] == ["tool-2"]
    assert json.loads(old_platform.calls[0]["params"]["filter"]) == {"enabled": True}
    assert json.loads(old_platform.calls[1]["params"]["filter"]) == {"enabled": False}


def test_tools_list_v2_against_mock_server(client: DeepOriginClient) -> None:
    """Against the mock tools-service: every version by default, filters honoured."""
    every = client.tools.list()
    enabled = client.tools.list(enabled=True)
    disabled = client.tools.list(enabled=False)

    assert len(every) == len(enabled) + len(disabled)
    assert all(r["enabled"] for r in enabled)
    assert disabled and not any(r["enabled"] for r in disabled)
