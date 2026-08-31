"""StructureReport -- grade a protein structure (served, sync-only).

Backed by the platform tool ``deeporigin.structure-report``. Configure one
:class:`StructureReport` with a :class:`~deeporigin.drug_discovery.structures.protein.Protein`
and/or a four-character PDB ID, then call :meth:`run`. The tool returns graded
rows under ``jobOutputs.structure_reports``; :meth:`run` maps those rows to
:class:`StructureReportResult` instances. Do not recompute grades in the client.

Indexed result-explorer rows remain available via the inherited
:meth:`~deeporigin.drug_discovery.execution.Execution.get_results`.

Usage::

    from deeporigin.drug_discovery import Protein, StructureReport

    # Local structure (optionally with PDB ID for RCSB metadata authority):
    protein = Protein.from_pdb_id("1ABC")
    rows = StructureReport(protein=protein, pdb_id="1ABC").run()

    # Remote PDB ID only (no coordinate file upload):
    rows = StructureReport(pdb_id="1ABC").run()
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Literal, Self

from beartype import beartype

from deeporigin.drug_discovery.execution import (
    Execution,
    _default_execution_payload,
    _execution_outputs_dict,
    _optional_float,
)
from deeporigin.drug_discovery.execution_mixins import SyncExecutableMixin
from deeporigin.drug_discovery.protein_prep import _protein_tool_input
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status

StructureReportGrade = Literal["A", "B", "C", "D"]
MetadataSource = Literal["rcsb", "file_header", "file_header+rcsb"]
FieldStatusValue = Literal["value", "not_applicable", "unknown"]

_PDB_ID_RE = re.compile(r"^[A-Za-z0-9]{4}$")

_REQUIRED_RESULT_KEYS = (
    "metadata_source",
    "field_status",
    "resolution_score",
    "coverage_score",
    "rfree_score",
    "inhibitor_score",
    "method_score",
    "organism_score",
    "weighted_score",
    "grade",
)


@dataclass(frozen=True)
class StructureReportResult:
    """One graded Structure Report row from ``jobOutputs.structure_reports``.

    Attributes:
        metadata_source: Provenance of experimental metadata used for scoring.
        field_status: Per-field status map (``value``, ``not_applicable``, or
            ``unknown``).
        resolution_score: Resolution component score.
        coverage_score: Coverage component score.
        rfree_score: Rfree component score.
        inhibitor_score: Inhibitor/holo component score.
        method_score: Method component score.
        organism_score: Organism component score.
        weighted_score: Weighted Structure Report score from the tool.
        grade: Letter grade ``A``–``D`` from the tool.
        coverage: Polymer residue coverage fraction (0–1), if known.
        has_ligand: Whether a non-water, non-ion ligand is present.
        method: Experimental method string.
        method_class: Normalized method class.
        organism: Source organism scientific name.
        organism_class: Normalized organism class.
        pdb_id: PDB ID used for experimental metadata.
        protein_id: Platform protein entity id when provided.
        resolution: Structure resolution in Angstroms.
        rfree: Rfree (X-ray).
        source_sha256: SHA-256 of uploaded structure bytes (omitted in remote
            PDB-ID-only mode).
    """

    metadata_source: MetadataSource
    field_status: dict[str, FieldStatusValue]
    resolution_score: float
    coverage_score: float
    rfree_score: float
    inhibitor_score: float
    method_score: float
    organism_score: float
    weighted_score: float
    grade: StructureReportGrade
    coverage: float | None = None
    has_ligand: bool | None = None
    method: str | None = None
    method_class: str | None = None
    organism: str | None = None
    organism_class: str | None = None
    pdb_id: str | None = None
    protein_id: str | None = None
    resolution: float | None = None
    rfree: float | None = None
    source_sha256: str | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> StructureReportResult:
        """Build a result from one ``structure_reports[]`` object.

        Args:
            data: Raw row from ``jobOutputs.structure_reports``.

        Returns:
            A :class:`StructureReportResult` with tool fields populated.

        Raises:
            DeepOriginException: If required fields are missing or mistyped.
        """
        missing = [key for key in _REQUIRED_RESULT_KEYS if key not in data]
        if missing:
            raise DeepOriginException(
                title="Invalid Structure Report row",
                message=f"Missing required fields: {missing!r}.",
            ) from None

        field_status = data["field_status"]
        if not isinstance(field_status, dict):
            raise DeepOriginException(
                title="Invalid Structure Report row",
                message="Expected field_status to be a dict.",
            ) from None

        return cls(
            metadata_source=data["metadata_source"],
            field_status=dict(field_status),
            resolution_score=float(data["resolution_score"]),
            coverage_score=float(data["coverage_score"]),
            rfree_score=float(data["rfree_score"]),
            inhibitor_score=float(data["inhibitor_score"]),
            method_score=float(data["method_score"]),
            organism_score=float(data["organism_score"]),
            weighted_score=float(data["weighted_score"]),
            grade=data["grade"],
            coverage=_optional_float(data.get("coverage")),
            has_ligand=data.get("has_ligand"),
            method=data.get("method"),
            method_class=data.get("method_class"),
            organism=data.get("organism"),
            organism_class=data.get("organism_class"),
            pdb_id=data.get("pdb_id"),
            protein_id=data.get("protein_id"),
            resolution=_optional_float(data.get("resolution")),
            rfree=_optional_float(data.get("rfree")),
            source_sha256=data.get("source_sha256"),
        )


def _structure_reports_from_dto(dto: dict[str, Any]) -> list[StructureReportResult]:
    """Parse ``jobOutputs.structure_reports`` into result objects."""
    outputs = _execution_outputs_dict(dto)
    raw_rows = outputs.get("structure_reports")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise DeepOriginException(
            title="Structure Report results missing",
            message=(
                "Expected a non-empty jobOutputs.structure_reports list "
                "on the execution response."
            ),
        ) from None

    rows: list[StructureReportResult] = []
    for index, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            raise DeepOriginException(
                title="Invalid Structure Report row",
                message=(
                    f"Expected structure_reports[{index}] to be a dict, "
                    f"got {type(row).__name__}."
                ),
            ) from None
        rows.append(StructureReportResult.from_json(row))
    return rows


def _normalize_pdb_id(pdb_id: str) -> str:
    """Validate and normalize a four-character PDB ID.

    Args:
        pdb_id: Candidate PDB ID.

    Returns:
        Uppercased PDB ID.

    Raises:
        ValueError: If ``pdb_id`` is not four alphanumeric characters.
    """
    cleaned = pdb_id.strip()
    if not _PDB_ID_RE.fullmatch(cleaned):
        raise ValueError(
            f"pdb_id must be exactly four alphanumeric characters, got {pdb_id!r}."
        )
    return cleaned.upper()


class StructureReport(Execution, SyncExecutableMixin):
    """Grade a structure via the Structure Report platform tool.

    Provide a :class:`~deeporigin.drug_discovery.structures.protein.Protein`
    (local/UFA file), a four-character ``pdb_id`` (remote RCSB metadata only),
    or both (local file with RCSB as experimental-metadata authority). Call
    :meth:`run` to execute synchronously and receive
    :class:`StructureReportResult` rows.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["structure_report"]["tool_key"]

    @beartype
    def __init__(
        self,
        protein: Protein | None = None,
        *,
        pdb_id: str | None = None,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["structure_report"]["tool_version"],
        client: DeepOriginClient | None = None,
        name: str | None = None,
    ) -> None:
        """Configure a Structure Report run.

        Args:
            protein: Local protein with a remote path (synced before ``run``).
            pdb_id: Four-character PDB ID. Alone enables remote mode; with
                ``protein``, RCSB supplies experimental metadata.
            tool_version: Platform tool version (defaults to ``"latest"``).
            client: Optional API client.
            name: Optional execution label.

        Raises:
            ValueError: If neither ``protein`` nor ``pdb_id`` is set, or if
                ``pdb_id`` is malformed.
        """
        super().__init__(client=client)
        if protein is None and pdb_id is None:
            raise ValueError("StructureReport requires a protein and/or pdb_id.")
        self._protein = protein
        self._pdb_id = _normalize_pdb_id(pdb_id) if pdb_id is not None else None
        self.tool_version = tool_version
        self.name = name

    @property
    def protein(self) -> Protein | None:
        """Input protein, if configured."""
        return self._protein

    @property
    def pdb_id(self) -> str | None:
        """Four-character PDB ID, if configured."""
        return self._pdb_id

    def _ensure_protein_remote(self) -> None:
        """Sync the protein so the tool receives a UFA ``file_path``."""
        if self._protein is None:
            return
        self._protein.sync(lazy=True, client=self.client)
        self._protein.ensure_remote_path(client=self.client, label="Protein")

    def _make_inputs(self) -> dict[str, Any]:
        """Build Structure Report tool inputs."""
        inputs: dict[str, Any] = {}
        if self._protein is not None:
            inputs["protein"] = _protein_tool_input(self._protein)
        if self._pdb_id is not None:
            inputs["pdb_id"] = self._pdb_id
        return inputs

    def _make_payload(
        self,
        *,
        approve_amount: int | None,
        sync: bool,
    ) -> dict[str, Any]:
        """Build the body dict for ``client.executions.create``."""
        return _default_execution_payload(
            self._make_inputs(),
            name=self.name,
            approve_amount=approve_amount,
            sync=sync,
        )

    def run(
        self,
        *,
        quote: bool = False,
        approve_amount: int | None = None,
    ) -> list[StructureReportResult] | None:
        """Run Structure Report synchronously and return graded rows.

        Args:
            quote: Shorthand for ``approve_amount=0``. Returns ``None`` when the
                platform returns a quotation.
            approve_amount: Spend cap forwarded as ``approveAmount``.

        Returns:
            One or more :class:`StructureReportResult` rows, or ``None`` for
            quote-only responses.

        Raises:
            DeepOriginException: If the execution does not succeed or
                ``jobOutputs.structure_reports`` is missing/invalid.
        """
        self._ensure_protein_remote()
        resolved_amount = 0 if quote else approve_amount
        response = self._create_execution(
            data=self._make_payload(
                approve_amount=resolved_amount,
                sync=not quote,
            ),
        )
        self.update_from_dto(response)

        if self.status == "Quoted":
            return None

        final_status = response.get("status")
        if not is_success_status(final_status):
            eid = response.get("executionId")
            reason = response.get("statusReason") or final_status
            raise DeepOriginException(
                title="Structure Report run did not succeed",
                message=(
                    f"Execution {eid!r} ended with status {final_status!r}: {reason!r}."
                ),
            ) from None

        return _structure_reports_from_dto(response)

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct a ``StructureReport`` from a tools execution DTO.

        Restores ``protein`` and/or ``pdb_id`` from ``userInputs`` (falling back
        to ``inputs``).

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client.

        Returns:
            A ``StructureReport`` with ``id``, pricing fields, and domain inputs.

        Raises:
            ValueError: If stored inputs lack both ``protein`` and ``pdb_id``.
        """
        instance = super().from_dto(dto, client=client)
        inputs: dict[str, Any] = dto.get("userInputs") or dto.get("inputs") or {}

        protein_input = inputs.get("protein")
        pdb_raw = inputs.get("pdb_id")
        protein: Protein | None = None
        pdb_id: str | None = None

        if isinstance(protein_input, dict):
            protein_id = protein_input.get("id")
            file_path = protein_input.get("file_path")
            if protein_id is not None:
                protein = Protein.from_id(
                    str(protein_id),
                    client=client,
                    download=False,
                    remote_path_override=file_path,
                )
            else:
                name = str(file_path).rsplit("/", 1)[-1] if file_path else "protein"
                protein = Protein(
                    name=name,
                    structure=None,
                    remote_path=str(file_path) if file_path else None,
                )

        if isinstance(pdb_raw, str) and pdb_raw.strip():
            pdb_id = _normalize_pdb_id(pdb_raw)

        if protein is None and pdb_id is None:
            raise ValueError(
                "Cannot restore StructureReport: stored inputs lack protein and pdb_id."
            )

        instance._protein = protein
        instance._pdb_id = pdb_id
        return instance
