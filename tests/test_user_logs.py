from deeporigin.platform.client import DeepOriginClient


def test_search_user_logs_by_compute_job_id_lv1(client: DeepOriginClient) -> None:
    """``user_logs.search`` filters the user_logs entity by ``compute_job_id``."""
    user_logs = client.user_logs  # ty:ignore[unresolved-attribute]
    assert user_logs is not None

    resp = user_logs.search("MOCK-USER-LOGS-CJ-ID")
    data = resp.get("data", [])
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0].get("compute_job_id") == "MOCK-USER-LOGS-CJ-ID"

    empty = user_logs.search("nonexistent-compute-job-id")
    assert empty.get("data", []) == []
