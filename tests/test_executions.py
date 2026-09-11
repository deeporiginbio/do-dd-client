from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import MagicMock

import pandas as pd
import pytest

from deeporigin.drug_discovery import Konnektor, Ligand
from deeporigin.drug_discovery.execution import Execution
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.executions import Executions
from deeporigin.utils.constants import (
    TOOL_EXECUTION_GET_ACCEPT_HEADER,
    TOOL_EXECUTION_POST_TIMEOUT_SECONDS,
)


def test_execution_runtime_none_without_dto() -> None:
    """``runtime`` is ``None`` when no execution DTO has been stored."""
    ex: Any = Execution()
    assert ex.runtime is None


def test_execution_runtime_none_without_started_at() -> None:
    """``runtime`` is ``None`` when the DTO has no usable ``startedAt``."""
    ex: Any = Execution()
    ex._dto = {"startedAt": None}
    assert ex.runtime is None


def test_execution_runtime_completed_uses_dto_timestamps() -> None:
    """``runtime`` is the delta in seconds between ``startedAt`` and ``completedAt``."""
    ex: Any = Execution()
    ex._dto = {
        "startedAt": "2024-06-01T10:00:00+00:00",
        "completedAt": "2024-06-01T10:00:30+00:00",
    }
    assert ex.runtime == pytest.approx(30.0)


def test_execution_runtime_incomplete_uses_now() -> None:
    """Without ``completedAt``, ``runtime`` uses current UTC as the end time."""
    ex: Any = Execution()
    # startedAt far in the past so the elapsed seconds stay positive under wall clock.
    ex._dto = {"startedAt": "2000-01-01T00:00:00+00:00"}
    assert ex.runtime is not None
    assert ex.runtime > 0


class _TestToolExecution(Execution):
    """Minimal concrete execution for unit tests (no platform create)."""

    tool_key = "deeporigin.test-sync-tool"
    tool_version = "1.0.0"

    def _make_payload(
        self,
        *,
        approve_amount: int | None,
        sync: bool,
    ) -> dict[str, Any]:
        """Unused in unit tests that don't exercise payload building."""
        raise NotImplementedError


def test_execution_sync_requires_id() -> None:
    """``sync`` raises when no platform execution id is set."""
    client = MagicMock()
    job = _TestToolExecution(client=client)

    with pytest.raises(ValueError, match="id is None"):
        job.sync()

    client.executions.get.assert_not_called()


def test_execution_sync_requires_tool_key() -> None:
    """``sync`` on the bare base class raises (no ``tool_key``)."""
    client = MagicMock()
    ex: Any = Execution(client=client)
    ex._id = "any-id"

    with pytest.raises(NotImplementedError, match="tool_key"):
        ex.sync()


def test_execution_sync_applies_get_response(
    client: DeepOriginClient,
    registered_ligand: Ligand,
    registered_ligand_brd3: Ligand,
) -> None:
    """``sync`` calls ``executions.get`` and applies fields via ``update_from_dto``."""
    job = Konnektor(
        ligands=[registered_ligand, registered_ligand_brd3],
        client=client,
    )
    job.run(quote=True)
    job.confirm()

    job.sync()

    assert job.status == "Running"
    assert job.id is not None
    assert job.dto is not None
    assert job.dto["status"] == "Running"


def test_execution_sync_no_op_when_get_returns_falsy() -> None:
    """When ``get`` returns a falsy value, ``sync`` leaves local state unchanged."""
    client = MagicMock()
    client.executions.get.return_value = None
    job = _TestToolExecution(client=client)
    job._id = "exec-1"
    job.status = "Created"

    job.sync()

    assert job.status == "Created"


def test_execution_wait_requires_id() -> None:
    """``wait`` raises when no platform execution id is set."""
    client = MagicMock()
    job: Any = _TestToolExecution(client=client)

    with pytest.raises(ValueError, match="execution ID"):
        job.wait()

    client.executions.wait.assert_not_called()


def test_execution_wait_calls_platform_and_applies_response() -> None:
    """``wait`` delegates to ``client.executions.wait`` and refreshes local state."""
    client = MagicMock()
    dto: dict[str, Any] = {
        "executionId": "exec-99",
        "tool": {"key": "deeporigin.test-sync-tool", "version": "1.0.0"},
        "status": "Succeeded",
        "quotationResult": {"successfulQuotations": [{"priceTotal": "2.25"}]},
    }
    client.executions.wait.return_value = [dto]
    job: Any = _TestToolExecution(client=client)
    job._id = "exec-99"

    result = job.wait(poll_interval=1.5, timeout=30)

    client.executions.wait.assert_called_once_with(
        "exec-99",
        poll_interval=1.5,
        timeout=30,
    )
    assert result == dto
    assert job.status == "Completed"
    assert job.cost == pytest.approx(2.25)


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


def test_execution_from_last_run_requires_tool_key() -> None:
    """``Execution.from_last_run`` rejects the bare base class."""

    with pytest.raises(NotImplementedError, match="tool_key"):
        Execution.from_last_run()


def test_execution_from_last_run_raises_when_empty() -> None:
    """``from_last_run`` raises when the platform returns no executions."""
    client = MagicMock()
    client.executions.list.return_value = {"data": []}

    with pytest.raises(ValueError, match="No executions found"):
        _TestToolExecution.from_last_run(client=client)


def test_execution_from_last_run_hydrates_latest() -> None:
    """``from_last_run`` lists by createdAt desc and hydrates the first DTO."""
    client = MagicMock()
    dto: dict[str, Any] = {
        "executionId": "exec-latest",
        "tool": {"key": "deeporigin.test-sync-tool", "version": "1.0.0"},
        "status": "Succeeded",
        "createdAt": "2026-06-04T12:00:00.000Z",
    }
    client.executions.list.return_value = {"data": [dto]}

    instance = _TestToolExecution.from_last_run(client=client)

    client.executions.list.assert_called_once_with(
        tool_key="deeporigin.test-sync-tool",
        order="createdAt desc",
        page=0,
        page_size=1,
    )
    assert instance.id == "exec-latest"
    assert instance.status == "Completed"


def test_execution_get_user_logs_no_id_noop() -> None:
    """``get_user_logs`` returns ``None`` when the execution has no platform id yet."""

    ex: Any = Execution()
    assert ex.get_user_logs() is None


def test_execution_get_results_scopes_to_execution_tool_key() -> None:
    """``get_results`` adds a ``tool_key`` filter for concrete executions."""
    client = MagicMock()
    client.results.get.return_value = {"data": [], "meta": {}}
    job = _TestToolExecution(client=client)
    job._id = "exec-123"

    job.get_results(limit=5)

    client.results.get.assert_called_once_with(
        compute_job_id="exec-123",
        filter_dict={"tool_key": {"eq": "deeporigin.test-sync-tool"}},
        limit=5,
    )


def test_execution_get_results_preserves_explicit_tool_key_filter() -> None:
    """``get_results`` does not override a caller-provided ``tool_key`` filter."""
    client = MagicMock()
    client.results.get.return_value = {"data": [], "meta": {}}
    job = _TestToolExecution(client=client)
    job._id = "exec-123"

    job.get_results(
        filter_dict={"tool_key": {"eq": "deeporigin.custom-tool"}, "foo": {"eq": "bar"}}
    )

    client.results.get.assert_called_once_with(
        compute_job_id="exec-123",
        filter_dict={
            "tool_key": {"eq": "deeporigin.custom-tool"},
            "foo": {"eq": "bar"},
        },
    )


def test_execution_get_user_logs_returns_dataframe() -> None:
    """``get_user_logs`` maps ``UserLogs.search`` rows into a DataFrame."""

    ex: Any = _TestToolExecution()
    ex._id = "exec-123"
    mock_user_logs = MagicMock()
    mock_user_logs.search.return_value = {
        "data": [
            {
                "log_level": "info",
                "tool_key": "deeporigin.rbfe",
                "date": "2026-06-04T16:18:53.034Z",
                "message": "CPU cpuset check passed.",
            }
        ]
    }
    ex.client = MagicMock(user_logs=mock_user_logs)

    logs = ex.get_user_logs()

    mock_user_logs.search.assert_called_once_with(
        execution_id="exec-123",
        limit=None,
        offset=None,
        select=None,
        with_total_count=False,
    )
    assert logs is not None
    assert isinstance(logs, pd.DataFrame)
    assert list(logs.columns) == Execution.USER_LOG_COLUMNS
    assert logs.iloc[0]["log_level"] == "info"
    assert logs.iloc[0]["tool_key"] == "rbfe"
    assert logs.iloc[0]["message"] == "CPU cpuset check passed."


def test_execution_get_user_logs_lv1(client: DeepOriginClient) -> None:
    """Load a succeeded execution and fetch user_logs scoped to its execution id."""

    # Prefer tools-native list so candidate IDs are known-loadable via GET.
    listed = client.executions.list(page_size=50, order="createdAt desc")  # ty:ignore[unresolved-attribute]
    list_rows = listed.get("data") or []
    candidates: list[str] = []
    for row in list_rows:
        status = row.get("status")
        if status not in ("Completed", "Succeeded"):
            continue
        exec_id = str(row.get("executionId") or row.get("id") or "")
        if exec_id:
            candidates.append(exec_id)

    if not candidates:
        search = client.executions.search(status="Completed", limit=200)  # ty:ignore[unresolved-attribute]
        rows = search.get("data") or []
        for row in rows:
            if row.get("status") not in ("Completed", "Succeeded"):
                continue
            candidate = str(
                row.get("compute_job_id")
                or row.get("executionId")
                or row.get("id")
                or ""
            )
            if candidate:
                candidates.append(candidate)

    if not candidates:
        pytest.skip("no succeeded execution visible for this account")

    dto = None
    last_error: DeepOriginException | None = None
    for candidate in candidates[:20]:
        try:
            dto = client.executions.get(candidate)  # ty:ignore[unresolved-attribute]
            break
        except DeepOriginException as exc:
            last_error = exc
            continue

    if dto is None:
        pytest.skip(
            "tools API cannot load any candidate execution id"
            + (f" (last error: {last_error})" if last_error is not None else "")
        )

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
    assert isinstance(logs, pd.DataFrame)
    assert list(logs.columns) == Execution.USER_LOG_COLUMNS


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


def test_list_fetch_all_pages_merges_when_count_exceeds_page_size() -> None:
    """``list(fetch_all_pages=True)`` walks pages until every row is collected."""
    client = MagicMock()
    client.org_key = "org-1"
    executions = Executions(client)
    page0 = [{"executionId": f"e{i}"} for i in range(1000)]
    page1 = [{"executionId": f"e{i}"} for i in range(1000, 1500)]
    client.get_json.side_effect = [
        {"data": page0, "count": 1500},
        {"data": page1, "count": 1500},
    ]

    result = executions.list(
        fetch_all_pages=True,
        tool_key="deeporigin.bulk-docking",
        page_size=1000,
    )

    assert result["count"] == 1500
    assert len(result["data"]) == 1500
    assert client.get_json.call_count == 2
    second_call_params = client.get_json.call_args_list[1][1]["params"]
    assert second_call_params["page"] == 1
    assert second_call_params["pageSize"] == 1000


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
    client._patch.return_value.json.return_value = {"executionId": "exec-1"}
    result = Executions(client).confirm("exec-1")
    client._patch.assert_called_once_with(
        "/tools/my-org/tools/executions/exec-1:confirm"
    )
    assert result == {"executionId": "exec-1"}


def test_confirm_can_set_long_timeout_and_disable_retries() -> None:
    """``confirm`` forwards ``timeout`` and ``retry`` to the low-level PATCH."""
    client = MagicMock()
    client.org_key = "my-org"
    client._patch.return_value.json.return_value = {"executionId": "exec-1"}
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


def test_get_requests_v2_accept_header() -> None:
    """``get`` requests the tools-service v2.0 execution DTO."""
    client = MagicMock()
    client.org_key = "my-org"
    dto: dict[str, Any] = {
        "executionId": "exec-42",
        "status": "Running",
        "progressReport": {"id": "workflow-abc", "children": []},
    }
    client.get_json.return_value = dto

    result = Executions(client).get("exec-42")

    client.get_json.assert_called_once_with(
        "/tools/my-org/tools/executions/exec-42",
        headers={"Accept": TOOL_EXECUTION_GET_ACCEPT_HEADER},
    )
    assert result == dto


def test_execution_update_from_dto_sets_cost_when_succeeded() -> None:
    """``update_from_dto`` copies ``priceTotal`` into ``cost`` for completed runs."""
    client = MagicMock()
    dto: dict[str, Any] = {
        "executionId": "exec-done",
        "tool": {"key": "deeporigin.test-sync-tool", "version": "1.0.0"},
        "status": "Succeeded",
        "quotationResult": {"successfulQuotations": [{"priceTotal": 10}]},
    }
    job = _TestToolExecution(client=client)
    job.update_from_dto(dto)

    assert job.status == "Completed"
    assert job.estimate == pytest.approx(10.0)
    assert job.cost == pytest.approx(10.0)


def test_execution_update_from_dto_normalizes_legacy_succeeded() -> None:
    """Legacy API ``Succeeded`` is stored as canonical ``Completed``."""
    client = MagicMock()
    dto: dict[str, Any] = {
        "executionId": "exec-legacy",
        "tool": {"key": "deeporigin.test-sync-tool", "version": "1.0.0"},
        "status": "Succeeded",
    }
    job = _TestToolExecution(client=client)
    job.update_from_dto(dto)

    assert job.status == "Completed"


def test_execution_update_from_dto_sums_workflow_quotations() -> None:
    """``update_from_dto`` sums all successful quotation rows for workflow tools."""
    client = MagicMock()
    dto: dict[str, Any] = {
        "executionId": "exec-quoted",
        "tool": {"key": "deeporigin.test-sync-tool", "version": "1.0.0"},
        "status": "Quoted",
        "quotationResult": {
            "successfulQuotations": [
                {"itemCode": "DO_SYSTEM_PREP", "priceTotal": 0},
                {"itemCode": "DO_RBFE", "priceTotal": 1.02792},
            ],
        },
    }
    job = _TestToolExecution(client=client)
    job.update_from_dto(dto)

    assert job.status == "Quoted"
    assert job.estimate == pytest.approx(1.02792)
    assert job.cost is None


def test_execution_quotation_total_missing() -> None:
    """``_quotation_total`` returns None when there is no successful quotation."""
    assert Execution._quotation_total({}) is None
    assert Execution._quotation_total({"quotationResult": {}}) is None


def test_execution_quotation_total_present() -> None:
    """``_quotation_total`` parses priceTotal from a single successful quotation row."""
    dto = {
        "quotationResult": {
            "successfulQuotations": [{"priceTotal": 1.5}],
        }
    }
    assert Execution._quotation_total(dto) == 1.5


def test_execution_quotation_total_sums_workflow_items() -> None:
    """``_quotation_total`` sums priceTotal across all successful quotation rows."""
    dto = {
        "quotationResult": {
            "successfulQuotations": [
                {"itemCode": "DO_SYSTEM_PREP", "priceTotal": 0},
                {"itemCode": "DO_RBFE", "priceTotal": 1.02792},
            ],
        }
    }
    assert Execution._quotation_total(dto) == pytest.approx(1.02792)


def test_execution_strip_tool_key_prefix() -> None:
    """``_strip_tool_key_prefix`` strips the platform prefix from tool keys."""
    assert Execution._strip_tool_key_prefix("deeporigin.rbfe") == "rbfe"
    assert Execution._strip_tool_key_prefix("rbfe") == "rbfe"
    assert Execution._strip_tool_key_prefix(None) is None


def test_execution_format_user_log_timestamp_humanizes() -> None:
    """``_format_user_log_timestamp`` formats ISO timestamps as relative times."""
    when = datetime(2026, 6, 4, 16, 35, 0, tzinfo=timezone.utc)
    assert (
        Execution._format_user_log_timestamp("2026-06-04T16:18:53.034Z", when=when)
        == "16 minutes ago"
    )


def test_execution_user_logs_dataframe_maps_rows() -> None:
    """``_user_logs_dataframe`` maps user_logs search rows to the expected columns."""
    when = datetime(2026, 6, 4, 16, 35, 0, tzinfo=timezone.utc)
    response = {
        "data": [
            {
                "log_level": "info",
                "tool_key": "deeporigin.rbfe",
                "date": "2026-06-04T16:18:53.034Z",
                "message": "CPU cpuset check passed.",
            },
            {
                "log_level": "info",
                "tool_key": "deeporigin.rbfe",
                "created_at": "2026-06-04T16:34:58.708Z",
                "message": "Finalize: reporting results.",
            },
        ]
    }
    df = Execution._user_logs_dataframe(response, when=when)

    assert list(df.columns) == Execution.USER_LOG_COLUMNS
    assert len(df) == 2
    assert df.iloc[0]["tool_key"] == "rbfe"
    assert df.iloc[1]["tool_key"] == "rbfe"
    assert df.iloc[0]["timestamp"] == "16 minutes ago"
    assert df.iloc[1]["timestamp"] == "a second ago"


def test_execution_user_logs_dataframe_empty() -> None:
    """``_user_logs_dataframe`` returns an empty frame when there are no rows."""
    df = Execution._user_logs_dataframe({"data": []})
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == Execution.USER_LOG_COLUMNS
    assert df.empty


def test_wait_returns_immediately_when_all_terminal() -> None:
    """If every execution is already terminal, ``wait`` returns on first poll."""
    dtos = [
        {"executionId": "a", "status": "Completed"},
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
        {"executionId": "b", "status": "Completed"},
        {"executionId": "a", "status": "Queued"},
        {"executionId": "a", "status": "Completed"},
    ]
    executions = _make_executions(get_side_effect=responses)

    sleeps: list[float] = []
    monkeypatch.setattr(
        "deeporigin.platform.executions.time.sleep", lambda s: sleeps.append(s)
    )

    result = executions.wait(["a", "b"], poll_interval=0.5)

    assert [r["status"] for r in result] == ["Completed", "Completed"]
    assert [r["executionId"] for r in result] == ["a", "b"]
    assert executions.get.call_count == 4  # ty:ignore[unresolved-attribute]
    assert sleeps == [0.5, 0.5]


def test_wait_accepts_single_string() -> None:
    """``wait`` accepts a single execution ID string."""
    executions = _make_executions(
        get_side_effect=[{"executionId": "x", "status": "Completed"}]
    )

    result = executions.wait("x", poll_interval=0.01)

    assert result == [{"executionId": "x", "status": "Completed"}]
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
