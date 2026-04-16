"""Tests for the Results API wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING

from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.platform.results import _build_result_filter

if TYPE_CHECKING:
    from deeporigin.drug_discovery import Protein


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
            record.get("tool_key") == TOOL_KEYS_AND_VERSIONS["sysprep"]["function_key"]
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
        assert (
            record.get("tool_key") == TOOL_KEYS_AND_VERSIONS["sysprep"]["function_key"]
        )
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
