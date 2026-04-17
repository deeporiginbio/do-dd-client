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
