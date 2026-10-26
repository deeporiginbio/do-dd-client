"""Notebook HTML for Structure Report summary cards (platform-ui parity).

Mirrors ``apps/uui/src/components/structure-grade`` adapters and
``StructureReportSummary`` layout — read-only grade + attribute pills.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape as html_escape
from typing import Literal, Mapping, Protocol

StructureGrade = Literal["A", "B", "C", "D", "F"]
StructureMethod = Literal["x-ray", "cryo-em", "nmr", "predicted"]
FieldStatus = Literal["value", "not_applicable", "unknown"]

_GRADES: frozenset[str] = frozenset({"A", "B", "C", "D", "F"})

_METHOD_LABELS: dict[StructureMethod, str] = {
    "x-ray": "X-ray",
    "cryo-em": "Cryo-EM",
    "nmr": "NMR",
    "predicted": "Predicted",
}

# Mantine palette index 6 from platform-ui/packages/theme/src/theme-values.ts
# (grade letter on white needs stronger contrast than filled-badge index 5).
_GRADE_HEX: dict[StructureGrade, str] = {
    "A": "#11A468",
    "B": "#1786F5",
    "C": "#F4B516",
    "D": "#E8590C",
    "F": "#D93E39",
}

_GREY_3 = "#D2D5DB"
_GREY_6 = "#4D5461"
_GREEN_5 = "#14C17B"
_YELLOW_5 = "#FFC825"
_DIMMED = "#6D717F"


@dataclass(frozen=True)
class StructureGradeSummary:
    """Headline fields for the Structure Report card (no residue count)."""

    grade: StructureGrade
    pdb_id: str | None = None
    method: StructureMethod | None = None
    organism: str | None = None
    resolution_angstrom: float | None = None
    has_ligand: bool | None = None
    coverage_percent: float | None = None
    residue_count: int | None = None


class _StructureReportRow(Protocol):
    grade: str
    pdb_id: str | None
    method: str | None
    method_class: str | None
    organism: str | None
    organism_class: str | None
    resolution: float | None
    coverage: float | None
    has_ligand: bool | None
    field_status: Mapping[str, str]


def _row_get(
    report: _StructureReportRow | Mapping[str, object],
    key: str,
) -> object | None:
    if isinstance(report, Mapping):
        return report.get(key)
    return getattr(report, key, None)


def _to_method(raw: str | None) -> StructureMethod | None:
    value = (raw or "").lower()
    if not value:
        return None
    if "cryo" in value or "electron microscopy" in value:
        return "cryo-em"
    if "nmr" in value:
        return "nmr"
    if "x-ray" in value or "xray" in value or "diffraction" in value:
        return "x-ray"
    if "predict" in value or "model" in value or "alphafold" in value:
        return "predicted"
    return None


def adapt_structure_report_summary(
    report: _StructureReportRow | Mapping[str, object] | None,
) -> StructureGradeSummary | None:
    """Map one Structure Report tool row to card header fields.

    Logic matches ``adapt-structure-report.ts`` in platform-ui.
    """
    if report is None:
        return None

    grade_raw = _row_get(report, "grade")
    grade = str(grade_raw).upper() if grade_raw is not None else ""
    if not grade or grade not in _GRADES:
        return None

    field_status_obj = _row_get(report, "field_status")
    field_status: dict[str, str] = {}
    if isinstance(field_status_obj, Mapping):
        field_status = {str(k): str(v) for k, v in field_status_obj.items()}

    def reported(field: str, value: object | None) -> object | None:
        status = field_status.get(field)
        if status and status != "value":
            return None
        return value

    method_raw = reported(
        "method", _row_get(report, "method_class") or _row_get(report, "method")
    )
    organism_raw = reported(
        "organism",
        _row_get(report, "organism") or _row_get(report, "organism_class"),
    )
    resolution_raw = reported("resolution", _row_get(report, "resolution"))
    has_ligand_raw = reported("inhibitor", _row_get(report, "has_ligand"))
    coverage_raw = reported("coverage", _row_get(report, "coverage"))

    coverage_percent: float | None = None
    if isinstance(coverage_raw, (int, float)):
        coverage_percent = float(coverage_raw) * 100.0

    resolution_angstrom: float | None = None
    if isinstance(resolution_raw, (int, float)):
        resolution_angstrom = float(resolution_raw)

    has_ligand: bool | None = None
    if isinstance(has_ligand_raw, bool):
        has_ligand = has_ligand_raw

    method: StructureMethod | None = None
    if isinstance(method_raw, str):
        method = _to_method(method_raw)

    organism: str | None = None
    if isinstance(organism_raw, str) and organism_raw:
        organism = organism_raw

    pdb_id: str | None = None
    pdb_raw = _row_get(report, "pdb_id")
    if isinstance(pdb_raw, str) and pdb_raw:
        pdb_id = pdb_raw

    return StructureGradeSummary(
        grade=grade,  # type: ignore[arg-type]
        pdb_id=pdb_id,
        method=method,
        organism=organism,
        resolution_angstrom=resolution_angstrom,
        has_ligand=has_ligand,
        coverage_percent=coverage_percent,
    )


def _badge_outline(text: str) -> str:
    safe = html_escape(text)
    return (
        f'<span style="display:inline-block;margin:2px 4px 2px 0;padding:4px 12px;'
        f"font-size:13px;font-weight:500;line-height:1.4;"
        f"border:1px solid {_GREY_3};border-radius:999px;color:{_GREY_6};"
        f'background:#fff;">{safe}</span>'
    )


def _badge_filled(
    text: str, *, bg: str, fg: str = "#131927", bold: bool = False
) -> str:
    safe = html_escape(text)
    weight = "600" if bold else "500"
    return (
        f'<span style="display:inline-block;margin:2px 4px 2px 0;padding:4px 12px;'
        f"font-size:13px;font-weight:{weight};line-height:1.4;"
        f"border-radius:999px;color:{fg};background:{bg};"
        f'border:1px solid transparent;">{safe}</span>'
    )


def _attribute_badges_html(summary: StructureGradeSummary) -> str:
    parts: list[str] = []
    if summary.method is not None:
        parts.append(_badge_outline(_METHOD_LABELS[summary.method]))
    if summary.organism:
        parts.append(_badge_outline(summary.organism))
    if summary.resolution_angstrom is not None:
        parts.append(
            _badge_filled(
                f"{summary.resolution_angstrom:.2f}Å",
                bg=_YELLOW_5,
                bold=True,
            )
        )
    if summary.has_ligand is not None:
        if summary.has_ligand:
            parts.append(_badge_filled("Ligand", bg=_GREEN_5, bold=True))
        else:
            parts.append(_badge_outline("No ligand"))
    if not parts:
        return ""
    return f'<div style="margin:0 0 6px 0;">{"".join(parts)}</div>'


def _summary_line_html(summary: StructureGradeSummary) -> str:
    parts: list[str] = []
    if summary.pdb_id:
        parts.append(html_escape(summary.pdb_id))
    if summary.residue_count is not None:
        parts.append(f"{summary.residue_count:,} Residues")
    if summary.coverage_percent is not None:
        parts.append(f"{summary.coverage_percent:.1f}% Coverage")
    if not parts:
        return ""
    joined = " · ".join(parts)
    return f'<div style="margin:0;font-size:15px;color:{_DIMMED};">{joined}</div>'


def render_structure_report_summary_html(
    summary: StructureGradeSummary,
    *,
    width_px: int = 520,
) -> str:
    """Return an HTML fragment matching ``StructureReportSummary`` in platform-ui."""
    grade = summary.grade
    grade_color = _GRADE_HEX[grade]
    grade_letter = html_escape(grade)

    badges = _attribute_badges_html(summary)
    line = _summary_line_html(summary)

    return f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  width: {width_px}px; max-width: 100%; padding: 16px; border: 1px solid {_GREY_3};
  border-radius: 8px; background: #fff; box-sizing: border-box;">
  <div style="display:flex;flex-direction:row;align-items:stretch;gap:16px;flex-wrap:nowrap;">
    <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;
      min-width:88px;padding:4px 8px;">
      <div style="font-size:14px;color:{_DIMMED};text-align:center;margin-bottom:4px;">
        Structure Grade
      </div>
      <div style="font-size:48px;font-weight:700;line-height:1;color:{grade_color};text-align:center;">{grade_letter}</div>
    </div>
    <div style="width:1px;background:{_GREY_3};flex-shrink:0;"></div>
    <div style="flex:1;min-width:0;display:flex;flex-direction:column;justify-content:center;gap:4px;">
      {badges}
      {line}
    </div>
  </div>
</div>
""".strip()


def render_structure_report_result_html(
    row: _StructureReportRow | Mapping[str, object],
    *,
    residue_count: int | None = None,
    width_px: int = 520,
) -> str:
    """Render the read-only summary card for a Structure Report result row."""
    summary = adapt_structure_report_summary(row)
    if summary is None:
        grade_raw = _row_get(row, "grade")
        grade = html_escape(str(grade_raw) if grade_raw is not None else "?")
        return (
            f'<div style="font-family: sans-serif;padding:8px;">'
            f"Structure grade: <strong>{grade}</strong></div>"
        )
    if residue_count is not None:
        summary = StructureGradeSummary(
            grade=summary.grade,
            pdb_id=summary.pdb_id,
            method=summary.method,
            organism=summary.organism,
            resolution_angstrom=summary.resolution_angstrom,
            has_ligand=summary.has_ligand,
            coverage_percent=summary.coverage_percent,
            residue_count=residue_count,
        )
    return render_structure_report_summary_html(summary, width_px=width_px)
