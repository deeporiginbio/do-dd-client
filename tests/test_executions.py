import pytest

from deeporigin.platform.client import DeepOriginClient


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
