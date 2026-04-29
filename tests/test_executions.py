from typing import Any, cast

import pytest

from deeporigin.drug_discovery.execution import Execution
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient


def test_execution_get_user_logs_no_id_noop() -> None:
    """``get_user_logs`` returns ``None`` when the execution has no platform id yet."""

    ex: Any = Execution()
    assert ex.get_user_logs() is None


def test_execution_get_user_logs_lv1(client: DeepOriginClient) -> None:
    """Load a succeeded execution and fetch user_logs scoped to its compute job id."""

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
