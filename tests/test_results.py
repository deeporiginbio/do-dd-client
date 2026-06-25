"""Tests for the Results API wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.platform.results import (
    Results,
    _build_result_filter,
    _build_result_type_filter,
    _filter_dict_has_result_type,
    _normalize_result_type,
)

if TYPE_CHECKING:
    from deeporigin.drug_discovery import Protein


def test_normalize_result_type_lowercases_and_strips():
    """Result types are normalized to lowercase catalog names."""
    assert _normalize_result_type("Pocket") == "pocket"
    assert _normalize_result_type("  Pose ") == "pose"


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


def test_get_result_type_conflict_raises():
    """Passing result_type both as kwarg and in filter_dict raises ValueError."""
    mock_client = MagicMock()
    mock_client.org_key = "test-org"
    mock_client.project_id = None
    results = Results(mock_client)

    with pytest.raises(ValueError, match="Cannot pass result_type"):
        results.get(
            result_type="pose",
            filter_dict={"result_type": {"eq": "pocket"}},
        )


def test_get_passes_sort_in_request_body():
    """Results.get forwards sort to the result-explorer search endpoint."""
    mock_client = MagicMock()
    mock_client.org_key = "test-org"
    mock_client.project_id = None
    mock_client.post_json.return_value = {"data": [], "meta": {}}
    results = Results(mock_client)

    results.get(sort={"measured_at": "desc"}, limit=5)

    body = mock_client.post_json.call_args.kwargs["body"]
    assert body["sort"] == {"measured_at": "desc"}
    assert "result_type" not in body["filter"]


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
        select=["id", "result_type", "tool_key", "data"],
    )

    assert isinstance(response["data"], list)
    assert len(response["data"]) >= 1
    for record in response["data"]:
        assert record.get("result_type") == "pocket"


def test_get_results_by_result_types_list_lv1(client):
    """Filter result-explorer rows by multiple result_type values."""
    response = client.results.get(
        result_type=["Pocket", "Pose"],
        select=["id", "result_type", "tool_key", "data"],
    )

    assert isinstance(response["data"], list)
    assert len(response["data"]) >= 1
    result_types = {record.get("result_type") for record in response["data"]}
    assert result_types.issubset({"pocket", "pose"})
    assert len(result_types) >= 1


def test_get_results_pose_score_filter_lv1(client):
    """JSONB numeric filters apply to nested pose fields."""
    response = client.results.get(
        result_type="pose",
        filter_dict={"pose_score": {"lt": 1}},
        select=["id", "result_type", "data"],
    )

    assert isinstance(response["data"], list)
    assert len(response["data"]) >= 1
    for record in response["data"]:
        assert record.get("result_type") == "pose"
        assert (record.get("data") or {}).get("pose_score", 0) < 1


def test_get_results_pose_score_range_filter_lv1(client):
    """Combined numeric bounds (gte + lt) are all enforced."""
    response = client.results.get(
        result_type="pose",
        filter_dict={"pose_score": {"gte": 0.5, "lt": 0.8}},
        select=["id", "result_type", "data"],
    )

    assert isinstance(response["data"], list)
    assert len(response["data"]) >= 1
    for record in response["data"]:
        score = (record.get("data") or {}).get("pose_score", 0)
        assert 0.5 <= score < 0.8


def test_get_results_sort_by_measured_at_lv1(client):
    """Sort directive orders rows by measured_at descending."""
    response = client.results.get(
        sort={"measured_at": "desc"},
        select=["result_type", "measured_at"],
    )

    measured_at_values = [
        record["measured_at"]
        for record in response["data"]
        if record.get("measured_at") is not None
    ]
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
