"""Tests for Structure Report notebook summary HTML."""

from deeporigin.viz.structure_report_html import (
    adapt_structure_report_summary,
    render_structure_report_result_html,
    render_structure_report_summary_html,
)


def _sample_row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "grade": "b",
        "pdb_id": "4GIH",
        "method": "X-RAY DIFFRACTION",
        "organism": "Homo sapiens",
        "resolution": 2.31,
        "coverage": 0.826,
        "has_ligand": True,
        "field_status": {},
    }
    base.update(overrides)
    return base


def test_adapt_matches_platform_ui_fixture() -> None:
    summary = adapt_structure_report_summary(_sample_row())
    assert summary is not None
    assert summary.grade == "B"
    assert summary.pdb_id == "4GIH"
    assert summary.method == "x-ray"
    assert summary.organism == "Homo sapiens"
    assert summary.resolution_angstrom == 2.31
    assert summary.has_ligand is True
    assert summary.coverage_percent == 82.6
    assert summary.residue_count is None


def test_adapt_drops_not_applicable_resolution() -> None:
    summary = adapt_structure_report_summary(
        _sample_row(field_status={"resolution": "not_applicable"})
    )
    assert summary is not None
    assert summary.resolution_angstrom is None


def test_adapt_rejects_invalid_grade() -> None:
    assert adapt_structure_report_summary(_sample_row(grade="Z")) is None


def test_render_summary_card_layout() -> None:
    summary = adapt_structure_report_summary(_sample_row())
    assert summary is not None
    html = render_structure_report_summary_html(summary)
    assert "Structure Grade" in html
    assert ">B<" in html
    assert "X-ray" in html
    assert "Homo sapiens" in html
    assert "2.31Å" in html
    assert "Ligand" in html
    assert "4GIH" in html
    assert "82.6% Coverage" in html
    assert "<table" not in html


def test_render_result_invalid_grade_mapping() -> None:
    html = render_structure_report_result_html({"grade": "Z"})
    assert "Structure grade:" in html
    assert ">Z<" in html


def test_render_result_row() -> None:
    from deeporigin.drug_discovery.structure_report import StructureReportResult

    row = StructureReportResult.from_json(
        {
            "metadata_source": "rcsb",
            "field_status": {},
            "resolution_score": 1.0,
            "coverage_score": 1.0,
            "rfree_score": 1.0,
            "inhibitor_score": 1.0,
            "method_score": 1.0,
            "organism_score": 1.0,
            "weighted_score": 0.7,
            "grade": "B",
            "pdb_id": "1ABC",
            "resolution": 2.0,
            "coverage": 0.5,
            "has_ligand": False,
            "method": "X-RAY DIFFRACTION",
            "organism": "Homo sapiens",
        }
    )
    html = render_structure_report_result_html(row)
    assert "No ligand" in html
    assert "50.0% Coverage" in html
    assert row._repr_html_() == html
