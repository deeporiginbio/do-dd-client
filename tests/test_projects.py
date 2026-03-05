"""Tests for the Projects API wrapper."""

from deeporigin.platform.client import DeepOriginClient


def test_list_projects_lv1():
    """Test listing projects."""
    client = DeepOriginClient()
    response = client.projects.list()

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"
