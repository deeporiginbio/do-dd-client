"""Tests for the Results API wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING

from deeporigin.platform.constants import ABFE_TOOL_KEY, SYSPREP_FUNCTION_KEY

if TYPE_CHECKING:
    from deeporigin.drug_discovery import Protein


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
    assert len(response["data"]) > 0, "Expected at least one result"

    for record in response["data"]:
        for field in ("id", "tool_key", "tool_version", "data", "compute_job_id"):
            assert field in record, f"Expected '{field}' key in record"


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
    for record in response["data"]:
        for field in ("id", "tool_key", "tool_version", "data", "compute_job_id"):
            assert field in record, f"Expected '{field}' key in record"
        assert record.get("tool_key") == SYSPREP_FUNCTION_KEY, (
            "Expected all records to be system-prep results"
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
        assert record.get("tool_key") == SYSPREP_FUNCTION_KEY
        data = record.get("data") or {}
        assert data.get("protein_id") == protein_id
        assert data.get("padding") == 1
        assert data.get("add_H_atoms") is True
        assert data.get("retain_waters") is False
        assert data.get("protonate_protein") is True


def test_get_abfe_results(client):
    """Test get_abfe_results returns ABFE results with expected shape."""
    response = client.results.get_abfe_results()

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"
    for record in response["data"]:
        for field in ("id", "tool_key", "tool_version", "data", "compute_job_id"):
            assert field in record, f"Expected '{field}' key in record"
        assert record.get("tool_key") == ABFE_TOOL_KEY, (
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
        assert record.get("tool_key") == ABFE_TOOL_KEY
