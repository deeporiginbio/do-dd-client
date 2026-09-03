"""Tests for :class:`~deeporigin.drug_discovery.structure_report.StructureReport`."""

from __future__ import annotations

import pytest

from deeporigin.drug_discovery import (
    Protein,
    StructureReport,
    StructureReportResult,
)
from deeporigin.drug_discovery.structure_report import (
    StructureReportResult as StructureReportResultCls,
)
from deeporigin.drug_discovery.structure_report import (
    _structure_reports_from_dto,
)
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS


def test_structure_report_requires_protein_or_pdb_id(
    client: DeepOriginClient,
) -> None:
    """Constructor rejects missing protein and pdb_id."""
    with pytest.raises(ValueError, match="protein and/or pdb_id"):
        StructureReport(client=client)


def test_structure_report_rejects_malformed_pdb_id(
    client: DeepOriginClient,
) -> None:
    """Constructor validates four-character PDB IDs."""
    with pytest.raises(ValueError, match="four alphanumeric"):
        StructureReport(pdb_id="1AB", client=client)


def test_structure_report_normalizes_pdb_id(client: DeepOriginClient) -> None:
    """PDB IDs are uppercased after validation."""
    job = StructureReport(pdb_id="1abc", client=client)
    assert job.pdb_id == "1ABC"
    assert job.protein is None
    assert job.tool_version == "latest"
    assert job.tool_key == TOOL_KEYS_AND_VERSIONS["structure_report"]["tool_key"]


def test_structure_report_make_payload_pdb_id_only(
    client: DeepOriginClient,
) -> None:
    """Remote mode sends only ``pdb_id``."""
    job = StructureReport(pdb_id="1ABC", client=client, name="sr-remote")
    payload = job._make_payload(approve_amount=None, sync=True)

    assert payload["sync"] is True
    assert payload["name"] == "sr-remote"
    assert payload["inputs"] == {"pdb_id": "1ABC"}
    assert "protein" not in payload["inputs"]


def test_structure_report_make_payload_with_protein(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """Local mode includes protein tool input and optional pdb_id."""
    job = StructureReport(
        protein=registered_protein,
        pdb_id="1ABC",
        client=client,
    )
    payload = job._make_payload(approve_amount=5, sync=True)

    assert payload["approveAmount"] == 5
    assert payload["inputs"]["pdb_id"] == "1ABC"
    protein_in = payload["inputs"]["protein"]
    assert protein_in["file_path"] == registered_protein.remote_path
    assert protein_in["id"] == registered_protein.id


def test_structure_report_result_from_json_round_trip() -> None:
    """``from_json`` maps required and optional tool fields."""
    raw = {
        "metadata_source": "rcsb",
        "field_status": {
            "organism": "value",
            "method": "value",
            "resolution": "value",
            "coverage": "unknown",
            "rfree": "value",
            "inhibitor": "value",
        },
        "resolution_score": 0.5,
        "coverage_score": 0.0,
        "rfree_score": 0.8,
        "inhibitor_score": 1.0,
        "method_score": 0.95,
        "organism_score": 1.0,
        "weighted_score": 0.7,
        "grade": "B",
        "pdb_id": "1ABC",
        "resolution": 2.0,
    }
    row = StructureReportResultCls.from_json(raw)
    assert isinstance(row, StructureReportResult)
    assert row.grade == "B"
    assert row.pdb_id == "1ABC"
    assert row.coverage is None
    assert row.source_sha256 is None

    # Sanity check: interactive-friendly representations.
    repr_str = repr(row)
    assert "StructureReportResult(" in repr_str
    assert "field_status" not in repr_str
    assert "grade='B'" in repr_str
    assert "weighted_score=0.700" in repr_str

    html = row._repr_html_()
    assert "<table" in html
    assert "Weighted score" in html
    assert ">B<" in html


def test_structure_reports_from_dto_rejects_empty() -> None:
    """Missing ``structure_reports`` raises."""
    with pytest.raises(DeepOriginException, match="structure_reports"):
        _structure_reports_from_dto({"jobOutputs": {}})


def test_structure_report_run_pdb_id_only(client: DeepOriginClient) -> None:
    """``run()`` returns typed rows for remote PDB-ID mode."""
    job = StructureReport(pdb_id="1abc", client=client)
    rows = job.run()

    assert rows is not None
    assert len(rows) == 1
    assert rows[0].grade == "A"
    assert rows[0].pdb_id == "1ABC"
    assert rows[0].metadata_source == "rcsb"
    assert rows[0].source_sha256 is None
    assert job.id is not None
    assert job.status in {"Completed", "Succeeded"}


def test_structure_report_run_with_protein(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """``run()`` returns typed rows for local protein (+ optional pdb_id)."""
    job = StructureReport(
        protein=registered_protein,
        pdb_id="1ABC",
        client=client,
    )
    rows = job.run()

    assert rows is not None
    assert len(rows) == 1
    assert rows[0].grade == "A"
    assert rows[0].metadata_source == "file_header+rcsb"
    assert rows[0].source_sha256 is not None
    assert rows[0].protein_id == registered_protein.id


def test_structure_report_run_quote_returns_none(
    client: DeepOriginClient,
) -> None:
    """Quote-only ``run`` returns ``None`` and leaves status Quoted."""
    job = StructureReport(pdb_id="1ABC", client=client)
    assert job.run(quote=True) is None
    assert job.status == "Quoted"
    assert job.id is not None


def test_structure_report_from_dto_restores_pdb_id(
    client: DeepOriginClient,
) -> None:
    """``from_dto`` restores remote-mode inputs."""
    job = StructureReport(pdb_id="1ABC", client=client)
    rows = job.run()
    assert rows is not None

    dto = client.executions.get(job.id)
    restored = StructureReport.from_dto(dto, client=client)
    assert restored.pdb_id == "1ABC"
    assert restored.protein is None
    assert restored.id == job.id
