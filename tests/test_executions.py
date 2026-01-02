from deeporigin.platform.client import DeepOriginClient


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
