from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from deeporigin.drug_discovery.execution import Execution
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.executions import Executions
from deeporigin.utils.constants import TOOL_EXECUTION_POST_TIMEOUT_SECONDS


def test_execution_from_id_requires_tool_key() -> None:
    """The bare ``Execution`` class has no ``tool_key``; ``from_id`` is invalid."""

    with pytest.raises(NotImplementedError, match="tool_key"):
        Execution.from_id("any-id")


def test_execution_from_dto_requires_tool_key() -> None:
    """``Execution.from_dto`` rejects the bare base class."""

    with pytest.raises(NotImplementedError, match="tool_key"):
        Execution.from_dto({"tool": {"key": "x", "version": "1"}, "executionId": "e"})


def test_execution_list_requires_tool_key() -> None:
    """``Execution.list`` rejects the bare base class."""

    with pytest.raises(NotImplementedError, match="tool_key"):
        Execution.list()


def test_execution_get_user_logs_no_id_noop() -> None:
    """``get_user_logs`` returns ``None`` when the execution has no platform id yet."""

    ex: Any = Execution()
    assert ex.get_user_logs() is None


def test_execution_get_user_logs_lv1(client: DeepOriginClient) -> None:
    """Load a succeeded execution and fetch user_logs scoped to its execution id."""

    search = client.executions.search(status="Succeeded", limit=200)  # ty:ignore[unresolved-attribute]
    rows = search.get("data") or []
    succeeded = [r for r in rows if r.get("status") == "Succeeded"]
    if not succeeded:
        pytest.skip("no succeeded execution visible for this account")

    row = succeeded[0]
    # Data-platform rows often use ``id`` for the row key; tools ``GET`` needs the
    # compute job UUID (``compute_job_id`` on DP rows, ``executionId`` on tools DTOs).
    candidate = str(
        row.get("compute_job_id") or row.get("executionId") or row.get("id") or ""
    )
    if not candidate:
        pytest.skip("succeeded execution row missing execution id")

    try:
        dto = client.executions.get(candidate)  # ty:ignore[unresolved-attribute]
    except DeepOriginException:
        pytest.skip(f"tools API cannot load execution id {candidate!r}")

    exec_id = str(dto.get("executionId") or "")
    if not exec_id:
        pytest.skip("execution DTO missing executionId")

    execution = cast(Any, Execution(client=client))
    execution._id = exec_id
    try:
        logs = execution.get_user_logs()
    except DeepOriginException:
        pytest.skip("user_logs search failed on this environment (schema or access)")

    assert logs is not None
    assert isinstance(logs.get("data"), list)


def test_list_executions_lv1(client: DeepOriginClient):
    """Test listing executions."""
    data = client.executions.list()  # ty:ignore[unresolved-attribute]
    executions = data.get("data", [])
    assert isinstance(executions, list), "Expected a list"


def test_list_executions_by_tool_key_lv1(client: DeepOriginClient):
    """Test listing executions by tool key."""
    data = client.executions.list(tool_key="deeporigin.bulk-docking")  # ty:ignore[unresolved-attribute]
    executions = data.get("data", [])
    assert isinstance(executions, list), "Expected a list"

    for execution in executions:
        assert execution.get("tool", {}).get("key") == "deeporigin.bulk-docking"


def test_search_executions_project_scope_lv1(client: DeepOriginClient):
    """The data-platform /executions/search endpoint must honor the
    project_id filter server-side — rows whose non-null project_id does
    not match should not leak from other projects.

    Rows where ``project_id`` is ``None`` are tolerated: the DTO does not
    always carry the column (mock server and some real-server shapes
    omit it), so we only assert on rows that actually expose the field.
    """

    # Find a project that actually has executions, else skip.
    # Project list may be large; fetch a page and probe each until one has rows.
    projects = client.projects.list(limit=25).get("data") or []  # ty:ignore[unresolved-attribute]
    target_project = None
    for p in projects:
        pid = p.get("id") or p.get("canonical_id")
        if not pid:
            continue
        resp = client.executions.search(project_id=pid, limit=1)  # ty:ignore[unresolved-attribute]
        if resp.get("data"):
            target_project = pid
            break
    if target_project is None:
        pytest.skip("no project with executions visible on this account")

    resp = client.executions.search(project_id=target_project, limit=20)  # ty:ignore[unresolved-attribute]
    rows = resp.get("data") or []
    assert isinstance(rows, list)
    for r in rows:
        pid = r.get("project_id")
        if pid is None:
            continue

        assert pid == target_project, (
            f"leak: got project_id={pid!r} when filter was {target_project!r}"
        )


def _make_executions(get_side_effect: Any) -> Executions:
    """Build an ``Executions`` wired to a mock client.

    Args:
        get_side_effect: Iterable / callable consumed by ``Executions.get`` via
            ``MagicMock.side_effect``.

    Returns:
        ``Executions`` instance whose ``get`` returns the supplied values.
    """
    executions = Executions(client=MagicMock())
    executions.get = MagicMock(side_effect=get_side_effect)  # ty:ignore[assignment]
    return executions


def test_confirm_default_forwards_only_confirm_path() -> None:
    """``confirm`` uses the client default timeout and retry policy when omitted."""
    client = MagicMock()
    client.org_key = "my-org"
    Executions(client).confirm("exec-1")
    client._patch.assert_called_once_with(
        "/tools/my-org/tools/executions/exec-1:confirm"
    )


def test_confirm_can_set_long_timeout_and_disable_retries() -> None:
    """``confirm`` forwards ``timeout`` and ``retry`` to the low-level PATCH."""
    client = MagicMock()
    client.org_key = "my-org"
    Executions(client).confirm(
        "exec-1",
        timeout=TOOL_EXECUTION_POST_TIMEOUT_SECONDS,
        retry=False,
    )
    client._patch.assert_called_once_with(
        "/tools/my-org/tools/executions/exec-1:confirm",
        timeout=TOOL_EXECUTION_POST_TIMEOUT_SECONDS,
        retry=False,
    )


def test_wait_returns_immediately_when_all_terminal() -> None:
    """If every execution is already terminal, ``wait`` returns on first poll."""
    dtos = [
        {"executionId": "a", "status": "Succeeded"},
        {"executionId": "b", "status": "Failed"},
    ]
    executions = _make_executions(get_side_effect=list(dtos))

    result = executions.wait(["a", "b"], poll_interval=0.01)

    assert result == dtos
    assert executions.get.call_count == 2  # ty:ignore[unresolved-attribute]


def test_wait_polls_until_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """``wait`` keeps polling pending executions and skips already-terminal ones."""
    responses = [
        {"executionId": "a", "status": "Running"},
        {"executionId": "b", "status": "Succeeded"},
        {"executionId": "a", "status": "Queued"},
        {"executionId": "a", "status": "Succeeded"},
    ]
    executions = _make_executions(get_side_effect=responses)

    sleeps: list[float] = []
    monkeypatch.setattr(
        "deeporigin.platform.executions.time.sleep", lambda s: sleeps.append(s)
    )

    result = executions.wait(["a", "b"], poll_interval=0.5)

    assert [r["status"] for r in result] == ["Succeeded", "Succeeded"]
    assert [r["executionId"] for r in result] == ["a", "b"]
    assert executions.get.call_count == 4  # ty:ignore[unresolved-attribute]
    assert sleeps == [0.5, 0.5]


def test_wait_accepts_single_string() -> None:
    """``wait`` accepts a single execution ID string."""
    executions = _make_executions(
        get_side_effect=[{"executionId": "x", "status": "Succeeded"}]
    )

    result = executions.wait("x", poll_interval=0.01)

    assert result == [{"executionId": "x", "status": "Succeeded"}]
    executions.get.assert_called_once_with("x")  # ty:ignore[unresolved-attribute]


def test_wait_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """``wait`` raises ``TimeoutError`` when the deadline elapses."""
    executions = _make_executions(
        get_side_effect=lambda _id: {"executionId": _id, "status": "Running"}
    )

    now = {"t": 0.0}

    def fake_monotonic() -> float:
        return now["t"]

    def fake_sleep(seconds: float) -> None:
        now["t"] += seconds

    monkeypatch.setattr("deeporigin.platform.executions.time.monotonic", fake_monotonic)
    monkeypatch.setattr("deeporigin.platform.executions.time.sleep", fake_sleep)

    with pytest.raises(TimeoutError, match="Timed out after"):
        executions.wait(["a"], poll_interval=0.1, timeout=0.25)


def test_wait_rejects_empty_list() -> None:
    """``wait`` rejects an empty input list."""
    executions = Executions(client=MagicMock())
    with pytest.raises(ValueError, match="non-empty"):
        executions.wait([], poll_interval=0.1)


def test_wait_rejects_non_positive_poll_interval() -> None:
    """``wait`` rejects ``poll_interval <= 0``."""
    executions = Executions(client=MagicMock())
    with pytest.raises(ValueError, match="poll_interval must be positive"):
        executions.wait(["a"], poll_interval=0.0)
    with pytest.raises(ValueError, match="poll_interval must be positive"):
        executions.wait(["a"], poll_interval=-1.0)


def test_wait_rejects_empty_string_id() -> None:
    """``wait`` rejects empty execution ID strings."""
    executions = Executions(client=MagicMock())
    with pytest.raises(ValueError, match="empty string"):
        executions.wait(["a", ""], poll_interval=0.1)


def test_list_executions_by_session_lv1(client: DeepOriginClient):
    """Test listing executions by session — server-side filter must drop
    executions whose non-null session does not match.

    Observed server behavior: rows where ``session`` is ``None`` may still
    appear in a filtered response (the server appears to treat null as
    unassigned and pass it through any filter). Tolerate those and only
    assert on rows that carry a non-null session.
    """
    sample = client.executions.list(page_size=200).get("data", [])  # ty:ignore[unresolved-attribute]
    target = next((e.get("session") for e in sample if e.get("session")), None)
    if target is None:
        pytest.skip("no executions carry a session on this account")

    filtered = client.executions.list(session=target)  # ty:ignore[unresolved-attribute]
    rows = filtered.get("data", [])
    assert isinstance(rows, list), "Expected a list"
    for execution in rows:
        sess = execution.get("session")
        if sess is None:
            continue  # server pass-through for unassigned-session rows
        assert sess == target, (
            f"server returned row with session={sess!r} when filter was {target!r}"
        )
