import pytest

from deeporigin.drug_discovery.execution import Execution
from deeporigin.platform.client import DeepOriginClient


def test_execution_get_results_rejects_filter_dict_with_pose_kwargs():
    """Pose routing must not forward filter_dict to get_poses."""
    ex = Execution()
    ex._id = "00000000-0000-0000-0000-000000000001"
    with pytest.raises(TypeError, match="cannot combine filter_dict"):
        ex.get_results(
            filter_dict={"tool_key": {"eq": "x"}},
            best_pose=True,
        )


def test_list_executions_lv1():
    """Test listing executions."""
    client = DeepOriginClient()
    data = client.executions.list()
    executions = data.get("data", [])
    assert isinstance(executions, list), "Expected a list"


def test_list_executions_by_tool_key_lv1():
    """Test listing executions by tool key."""
    client = DeepOriginClient()
    data = client.executions.list(tool_key="deeporigin.bulk-docking")
    executions = data.get("data", [])
    assert isinstance(executions, list), "Expected a list"

    for execution in executions:
        assert execution.get("tool", {}).get("key") == "deeporigin.bulk-docking"


def test_list_executions_by_session_lv1():
    """Test listing executions by session — server-side filter must drop
    executions that aren't tagged with the requested session."""
    client = DeepOriginClient()

    sample = client.executions.list(page_size=200).get("data", [])
    session = next((e.get("session") for e in sample if e.get("session")), None)
    if session is None:
        pytest.skip("no executions carry a session on this account")

    filtered = client.executions.list(session=session)
    rows = filtered.get("data", [])
    assert isinstance(rows, list), "Expected a list"
    for execution in rows:
        assert execution.get("session") == session, (
            f"server returned row with session={execution.get('session')!r} "
            f"when filter was {session!r}"
        )
