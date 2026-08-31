"""Tests for the Results API wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.platform.results import (
    Results,
    _build_result_filter,
    _build_result_type_filter,
    _filter_dict_has_result_type,
    _normalize_result_type,
    _resolve_request_page_size,
    _sort_uses_jsonb_fields,
)
from deeporigin.utils.constants import DEFAULT_SEARCH_PAGE_SIZE
from tests.mock_server.routers.data_platform import _apply_eq_filters

if TYPE_CHECKING:
    from deeporigin.drug_discovery import Protein
    from deeporigin.platform.client import DeepOriginClient


class _RecordingResultsClient:
    """Minimal stand-in for ``DeepOriginClient`` that records ``post_json`` bodies.

    Used only for unit tests that assert request-shape (sort/pagination) without
    going through the mock server. Not a substitute for platform-facing tests.
    """

    def __init__(self, responses: list[dict]) -> None:
        """Store canned responses returned in order by ``post_json``."""
        self.org_key = "test-org"
        self.project_id = None
        self._responses = list(responses)
        self.post_json_bodies: list[dict] = []

    def post_json(self, _url: str, *, body: dict) -> dict:
        """Record ``body`` and return the next canned response."""
        self.post_json_bodies.append(body)
        if not self._responses:
            return {"data": [], "meta": {}}
        return self._responses.pop(0)


_POCKET_TOOL_KEYS = {
    TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_key"],
    "deeporigin.pocketfinder",
}
_POSE_TOOL_KEYS = {
    TOOL_KEYS_AND_VERSIONS["docking"]["tool_key"],
    TOOL_KEYS_AND_VERSIONS["constrained_docking"]["tool_key"],
    TOOL_KEYS_AND_VERSIONS["import_dataset"]["tool_key"],
    "deeporigin.bulk-docking",
}


def _pose_scores_from_response(response: dict) -> list[float]:
    """Extract numeric pose_score values from a result-explorer response."""
    scores: list[float] = []
    for record in response.get("data", []):
        raw_score = (record.get("data") or {}).get("pose_score")
        if isinstance(raw_score, (int, float)):
            scores.append(float(raw_score))
    return scores


def test_normalize_result_type_lowercases_and_strips():
    """Result types are normalized to lowercase catalog names."""
    assert _normalize_result_type("Pocket") == "pocket"
    assert _normalize_result_type("  Pose ") == "pose"


def test_apply_eq_filters_rejects_mixed_membership_and_comparison_operators():
    """Mock result-explorer rejects ambiguous eq/in + lt/gte filter shapes."""
    records = [{"id": "1", "score": 1.0}]
    with pytest.raises(ValueError, match="cannot mix membership"):
        _apply_eq_filters(records, {"score": {"eq": 1, "lt": 2}})


def test_build_result_type_filter_eq_and_in():
    """Single values use eq; lists use in with normalized values."""
    assert _build_result_type_filter("Pocket") == {
        "result_type": {"eq": "pocket"},
    }
    assert _build_result_type_filter(["Pocket", "Pose"]) == {
        "result_type": {"in": ["pocket", "pose"]},
    }


def test_filter_dict_has_result_type_detects_top_level_and_props():
    """Conflict detection covers top-level and props result_type filters."""
    assert _filter_dict_has_result_type({"result_type": {"eq": "pose"}})
    assert _filter_dict_has_result_type(
        {"props": [{"column": "result_type", "op": "eq", "value": "pose"}]}
    )
    assert not _filter_dict_has_result_type({"protein_id": {"eq": "p1"}})


def test_get_result_type_conflict_raises(client: DeepOriginClient):
    """Passing result_type both as kwarg and in filter_dict raises ValueError."""
    results = Results(client)

    with pytest.raises(ValueError, match="Cannot pass result_type"):
        results.get(
            result_type="pose",
            filter_dict={"result_type": {"eq": "pocket"}},
        )


def test_get_compute_job_id_conflict_with_in_operator_raises(
    client: DeepOriginClient,
):
    """compute_job_id kwarg cannot override a non-eq filter_dict operator."""
    results = Results(client)

    with pytest.raises(ValueError, match="Conflicting compute_job_id"):
        results.get(
            compute_job_id="job-a",
            filter_dict={"compute_job_id": {"in": ["job-a", "job-b"]}},
        )


def test_get_compute_job_id_conflict_with_mismatched_eq_raises(
    client: DeepOriginClient,
):
    """compute_job_id kwarg must match an existing eq filter in filter_dict."""
    results = Results(client)

    with pytest.raises(ValueError, match="Conflicting compute_job_id"):
        results.get(
            compute_job_id="job-a",
            filter_dict={"compute_job_id": {"eq": "job-b"}},
        )


def test_sort_uses_jsonb_fields_detects_non_canonical_keys():
    """JSONB tool-data sort keys require offset pagination."""
    assert _sort_uses_jsonb_fields({"pose_score": "desc"})
    assert not _sort_uses_jsonb_fields({"measured_at": "desc"})
    assert _sort_uses_jsonb_fields(
        {"measured_at": "desc", "pose_score": "asc"},
    )
    assert _sort_uses_jsonb_fields({"data": "asc"})
    assert _sort_uses_jsonb_fields({"parameters": "desc"})


def test_get_passes_sort_in_request_body():
    """Results.get forwards sort to the result-explorer search endpoint."""
    fake_client = _RecordingResultsClient([{"data": [], "meta": {}}])
    results = Results(fake_client)  # type: ignore[arg-type]

    results.get(sort={"measured_at": "desc"}, limit=5)

    body = fake_client.post_json_bodies[0]
    assert body["sort"] == {"measured_at": "desc"}
    assert "result_type" not in body["filter"]
    assert "cursor" not in body
    assert "offset" not in body


def test_resolve_request_page_size_defaults_and_caps() -> None:
    """Page size defaults to 100 and is capped by total limit when set."""
    assert _resolve_request_page_size(limit=None, page_size=None) == (
        DEFAULT_SEARCH_PAGE_SIZE
    )
    assert _resolve_request_page_size(limit=None, page_size=1000) == 1000
    assert _resolve_request_page_size(limit=50, page_size=1000) == 50
    assert _resolve_request_page_size(limit=5000, page_size=1000) == 1000
    with pytest.raises(ValueError, match="page_size must be >= 1"):
        _resolve_request_page_size(limit=None, page_size=0)


def test_get_uses_configured_page_size() -> None:
    """Results.get sends the caller page_size as each request's limit."""
    fake_client = _RecordingResultsClient(
        [
            {
                "data": [{"id": str(i)} for i in range(1000)],
                "meta": {"nextCursor": "page-2"},
            },
            {
                "data": [{"id": "1000"}],
                "meta": {},
            },
        ]
    )
    results = Results(fake_client)  # type: ignore[arg-type]

    response = results.get(limit=None, page_size=1000, select=["id"])

    assert len(response["data"]) == 1001
    assert fake_client.post_json_bodies[0]["limit"] == 1000
    assert fake_client.post_json_bodies[1]["cursor"] == "page-2"
    assert fake_client.post_json_bodies[1]["limit"] == 1000


def test_get_rejects_invalid_page_size() -> None:
    """Results.get raises when page_size is less than 1."""
    fake_client = _RecordingResultsClient([])
    results = Results(fake_client)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="page_size must be >= 1"):
        results.get(page_size=0)


def test_get_jsonb_sort_uses_offset_pagination():
    """JSONB sort keys paginate with offset instead of cursor."""
    fake_client = _RecordingResultsClient(
        [
            {
                "data": [{"id": "1", "data": {"pose_score": 1.0}}],
                "meta": {"hasMore": True},
            },
            {
                "data": [{"id": "2", "data": {"pose_score": 2.0}}],
                "meta": {"hasMore": False},
            },
        ]
    )
    results = Results(fake_client)  # type: ignore[arg-type]

    response = results.get(
        result_type="pose",
        sort={"pose_score": "desc"},
        limit=None,
        select=["id", "data"],
    )

    assert len(response["data"]) == 2
    first_body = fake_client.post_json_bodies[0]
    second_body = fake_client.post_json_bodies[1]
    assert first_body["sort"] == {"pose_score": "desc"}
    assert first_body["offset"] == 0
    assert "cursor" not in first_body
    assert second_body["offset"] == 100
    assert "cursor" not in second_body


def test_get_canonical_sort_uses_cursor_pagination():
    """Canonical sort keys continue to paginate with cursor tokens."""
    fake_client = _RecordingResultsClient(
        [
            {
                "data": [{"id": "1", "measured_at": "2026-01-02T00:00:00Z"}],
                "meta": {"nextCursor": "cursor-page-2"},
            },
            {
                "data": [{"id": "2", "measured_at": "2026-01-01T00:00:00Z"}],
                "meta": {},
            },
        ]
    )
    results = Results(fake_client)  # type: ignore[arg-type]

    response = results.get(
        sort={"measured_at": "desc"},
        limit=None,
        select=["id", "measured_at"],
    )

    assert len(response["data"]) == 2
    first_body = fake_client.post_json_bodies[0]
    second_body = fake_client.post_json_bodies[1]
    assert "offset" not in first_body
    assert second_body["cursor"] == "cursor-page-2"
    assert "offset" not in second_body


def test_build_result_filter_eq_and_omits_none():
    """Non-list values use eq; None values are skipped."""
    assert _build_result_filter(protein_id="p1", effort=3) == {
        "protein_id": {"eq": "p1"},
        "effort": {"eq": 3},
    }
    assert _build_result_filter(protein_id=None, x=1) == {"x": {"eq": 1}}


def test_build_result_filter_list_uses_in():
    """List values use the in operator."""
    assert _build_result_filter(ligand_id=["a", "b"]) == {
        "ligand_id": {"in": ["a", "b"]},
    }


def test_get_results_lv1(client, registered_protein: "Protein"):
    """Test searching result-explorer records filtered by tool and protein."""
    response = client.results.get(
        filter_dict={
            "protein_id": {"eq": registered_protein.id},
        },
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"

    for record in response["data"]:
        for field in ("id", "tool_key", "tool_version", "data", "compute_job_id"):
            assert field in record, f"Expected '{field}' key in record"


def test_get_results_by_result_type_pocket_lv1(client):
    """Filter result-explorer rows by a single result_type directive."""
    response = client.results.get(
        result_type="pocket",
        select=["id", "tool_key", "data"],
    )

    assert isinstance(response["data"], list)
    if client.env != "local" and not response["data"]:
        pytest.skip("No pocket rows available in live environment")
    assert len(response["data"]) >= 1
    for record in response["data"]:
        assert record.get("tool_key") in _POCKET_TOOL_KEYS


def test_get_results_by_result_types_list_lv1(client):
    """Filter result-explorer rows by multiple result_type values."""
    response = client.results.get(
        result_type=["Pocket", "Pose"],
        select=["id", "tool_key", "data"],
    )

    assert isinstance(response["data"], list)
    if client.env != "local" and not response["data"]:
        pytest.skip(
            "No pocket/pose rows available in live environment for multi-type query"
        )
    assert len(response["data"]) >= 1
    allowed_tool_keys = _POCKET_TOOL_KEYS | _POSE_TOOL_KEYS
    tool_keys = {record.get("tool_key") for record in response["data"]}
    assert tool_keys.issubset(allowed_tool_keys)
    assert len(tool_keys) >= 1


def test_get_results_pose_score_filter_lv1(client):
    """JSONB numeric filters apply to nested pose fields."""
    baseline = client.results.get(
        result_type="pose",
        select=["id", "data"],
        limit=25,
    )
    baseline_scores = _pose_scores_from_response(baseline)
    if not baseline_scores:
        pytest.skip("No pose rows with pose_score available in live environment")

    response = client.results.get(
        result_type="pose",
        filter_dict={"pose_score": {"lt": 1}},
        select=["id", "data"],
    )

    assert isinstance(response["data"], list)
    if client.env != "local" and not response["data"]:
        pytest.skip(
            "Live result-explorer returned no rows for pose_score filter; "
            "backend JSONB numeric filters may not be deployed yet."
        )

    assert len(response["data"]) >= 1
    for record in response["data"]:
        assert "pose_score" in (record.get("data") or {})
        assert (record.get("data") or {}).get("pose_score", 0) < 1


def test_get_results_pose_score_range_filter_lv1(client):
    """Combined numeric bounds (gte + lt) are all enforced."""
    baseline = client.results.get(
        result_type="pose",
        select=["id", "data"],
        limit=25,
    )
    baseline_scores = _pose_scores_from_response(baseline)
    if not baseline_scores:
        pytest.skip("No pose rows with pose_score available in live environment")

    lower = min(baseline_scores)
    upper = max(baseline_scores) + 0.001
    response = client.results.get(
        result_type="pose",
        filter_dict={"pose_score": {"gte": lower, "lt": upper}},
        select=["id", "data"],
    )

    assert isinstance(response["data"], list)
    if client.env != "local" and not response["data"]:
        pytest.skip(
            "Live result-explorer returned no rows for combined pose_score "
            "bounds; backend JSONB numeric filters may not be deployed yet."
        )

    assert len(response["data"]) >= 1
    for record in response["data"]:
        score = (record.get("data") or {}).get("pose_score", 0)
        assert lower <= score < upper


def test_get_results_sort_by_measured_at_lv1(client):
    """Sort directive orders rows by measured_at descending."""
    response = client.results.get(
        sort={"measured_at": "desc"},
        select=["measured_at"],
    )

    measured_at_values = [
        record["measured_at"]
        for record in response["data"]
        if record.get("measured_at") is not None
    ]
    if len(measured_at_values) < 2:
        pytest.skip(
            "Need at least two rows with non-null measured_at to validate sort order"
        )
    assert measured_at_values == sorted(measured_at_values, reverse=True)


def test_get_results_with_tool_version_lv1(client, registered_protein: "Protein"):
    """Test results.get with an explicit tool_version filter."""
    response = client.results.get(
        filter_dict={
            "tool_key": {"eq": "deeporigin.bulk-docking"},
            "protein_id": {"eq": registered_protein.id},
        },
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_get_prepared_systems(client):
    """Test get_prepared_systems returns system-prep results with expected shape."""
    response = client.results.get_prepared_systems()

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"
    assert len(response["data"]) >= 1, (
        "Mock should expose at least one prepared-system fixture"
    )
    for record in response["data"]:
        for field in ("id", "tool_key", "tool_version", "data", "compute_job_id"):
            assert field in record, f"Expected '{field}' key in record"
        assert (
            record.get("tool_key") == TOOL_KEYS_AND_VERSIONS["sysprep"]["tool_key"]
        ), "Expected all records to be system-prep results"
        data = record.get("data") or {}
        assert data.get("solvation_xml_ligand_file_path"), (
            "Expected solvation_xml_ligand_file_path in prepared-system data"
        )


def test_get_prepared_systems_with_filters(client, registered_protein: "Protein"):
    """Test get_prepared_systems with optional filters builds correct filter and returns."""
    protein_id = registered_protein.id
    response = client.results.get_prepared_systems(
        protein_id=protein_id,
        padding=1,
        add_H_atoms=True,
        retain_waters=False,
        protonate_protein=True,
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"
    for record in response["data"]:
        assert record.get("tool_key") == TOOL_KEYS_AND_VERSIONS["sysprep"]["tool_key"]
        data = record.get("data") or {}
        assert data.get("protein_id") == protein_id
        assert data.get("padding") == 1
        assert data.get("add_H_atoms") is True
        assert data.get("retain_waters") is False
        assert data.get("protonate_protein") is True


def test_prepared_system_from_result_hydrates_paths(
    client, registered_protein: "Protein"
):
    """PreparedSystem.from_result returns rows when the mock exposes system-prep data."""
    from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem

    systems = PreparedSystem.from_result(
        protein_id=registered_protein.id, client=client
    )
    assert len(systems) >= 1
    ps = systems[0]
    assert ps.binding_xml_path
    assert ps.solvation_xml_path
    assert ps.system_pdb_path


def test_get_abfe_results(client):
    """Test get_abfe_results returns ABFE results with expected shape."""
    response = client.results.get_abfe_results()

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"
    for record in response["data"]:
        for field in ("id", "tool_key", "tool_version", "data", "compute_job_id"):
            assert field in record, f"Expected '{field}' key in record"
        assert record.get("tool_key") == TOOL_KEYS_AND_VERSIONS["abfe"]["tool_key"], (
            "Expected all records to be ABFE results"
        )


def test_get_abfe_results_with_filters(client):
    """Test get_abfe_results with optional filters builds correct filter and returns."""
    response = client.results.get_abfe_results(limit=10)

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"
    assert len(response["data"]) <= 10, "Expected at most 10 results"
    for record in response["data"]:
        assert record.get("tool_key") == TOOL_KEYS_AND_VERSIONS["abfe"]["tool_key"]
