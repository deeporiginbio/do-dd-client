"""UniprotDiscovery -- rank experimental PDBs for a UniProt accession.

Backed by the platform tool ``deeporigin.uniprot-discovery``. Configure one
:class:`UniprotDiscovery` with a UniProtKB accession, then call :meth:`run` for
ranked :class:`UniprotDiscoveryCandidate` rows (exactly one ``recommended``
unless the list is empty). Use :meth:`import_proteins` to download selected
(or recommended) PDB entries and sync them into a project with
``uniprot_accession`` set. :meth:`~deeporigin.drug_discovery.structures.protein.Protein.from_uniprot`
is thin sugar for the recommended single-protein path.

Usage::

    from deeporigin.drug_discovery import Protein, UniprotDiscovery

    job = UniprotDiscovery(uniprot_accession="P00533", client=client)
    candidates = job.run()
    proteins = job.import_proteins()  # recommended
    protein = Protein.from_uniprot("P00533", project_id=client.project_id, client=client)
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
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status

UniprotDiscoveryGrade = Literal["A", "B", "C", "D"]
FieldStatusValue = Literal["value", "not_applicable", "unknown"]

# UniProtKB accessions: 6-char classic format or 10-char extended format.
# Isoform suffixes (e.g. "-2") are a separate concept and not matched here.
_UNIPROT_ACCESSION_RE = re.compile(
    r"^(?:[OPQ]\d[A-Z0-9]{3}\d|[A-NR-Z]\d(?:[A-Z][A-Z0-9]{2}\d){1,2})$",
    re.IGNORECASE,
)
_PDB_ID_RE = re.compile(r"^[A-Za-z0-9]{4}$")

_INVALID_CANDIDATE_TITLE = "Invalid UniProt discovery candidate"


def _required_float(data: dict[str, Any], key: str) -> float:
    """Return ``float(data[key])``, honoring the ``from_json`` error contract.

    Args:
        data: Raw row from ``jobOutputs.candidates``. ``key`` is assumed present
            (checked by the caller's required-keys pass).
        key: Field name to convert.

    Raises:
        DeepOriginException: If the value is not numeric.
    """
    try:
        return float(data[key])
    except (TypeError, ValueError) as error:
        raise DeepOriginException(
            title=_INVALID_CANDIDATE_TITLE,
            message=f"Expected {key!r} to be numeric, got {data[key]!r}.",
        ) from error


_REQUIRED_CANDIDATE_KEYS = (
    "coverage_score",
    "field_status",
    "grade",
    "inhibitor_score",
    "method_score",
    "organism_score",
    "pdb_id",
    "recommended",
    "resolution_score",
    "rfree_score",
    "weighted_score",
)


@dataclass(frozen=True)
class UniprotDiscoveryCandidate:
    """One ranked PDB candidate from ``jobOutputs.candidates``.

    Attributes:
        coverage_score: Coverage component score.
        field_status: Per-field status map (``value``, ``not_applicable``, or
            ``unknown``).
        grade: Letter grade ``A``–``D`` from the tool.
        inhibitor_score: Inhibitor/holo component score.
        method_score: Method component score.
        organism_score: Organism component score.
        pdb_id: PDB entry ID.
        recommended: True for the single top-ranked candidate.
        resolution_score: Resolution component score.
        rfree_score: Rfree component score.
        weighted_score: Weighted Structure Report score from the tool.
        coverage: Polymer residue coverage fraction (0–1), if known.
        has_ligand: Whether a non-water, non-ion ligand is present.
        method: Experimental method string.
        method_class: Normalized method class.
        organism: Source organism scientific name.
        organism_class: Normalized organism class.
        resolution: Structure resolution in Angstroms.
        rfree: Rfree (X-ray).
    """

    coverage_score: float
    field_status: dict[str, FieldStatusValue]
    grade: UniprotDiscoveryGrade
    inhibitor_score: float
    method_score: float
    organism_score: float
    pdb_id: str
    recommended: bool
    resolution_score: float
    rfree_score: float
    weighted_score: float
    coverage: float | None = None
    has_ligand: bool | None = None
    method: str | None = None
    method_class: str | None = None
    organism: str | None = None
    organism_class: str | None = None
    resolution: float | None = None
    rfree: float | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> UniprotDiscoveryCandidate:
        """Build a candidate from one ``candidates[]`` object.

        Args:
            data: Raw row from ``jobOutputs.candidates``.

        Returns:
            A :class:`UniprotDiscoveryCandidate` with tool fields populated.

        Raises:
            DeepOriginException: If required fields are missing or mistyped.
        """
        missing = [key for key in _REQUIRED_CANDIDATE_KEYS if key not in data]
        if missing:
            raise DeepOriginException(
                title=_INVALID_CANDIDATE_TITLE,
                message=f"Missing required fields: {missing!r}.",
            ) from None

        field_status = data["field_status"]
        if not isinstance(field_status, dict):
            raise DeepOriginException(
                title=_INVALID_CANDIDATE_TITLE,
                message="Expected field_status to be a dict.",
            ) from None

        pdb_raw = data["pdb_id"]
        if not isinstance(pdb_raw, str) or not pdb_raw.strip():
            raise DeepOriginException(
                title=_INVALID_CANDIDATE_TITLE,
                message="Expected pdb_id to be a non-empty string.",
            ) from None

        return cls(
            coverage_score=_required_float(data, "coverage_score"),
            field_status=dict(field_status),
            grade=data["grade"],
            inhibitor_score=_required_float(data, "inhibitor_score"),
            method_score=_required_float(data, "method_score"),
            organism_score=_required_float(data, "organism_score"),
            pdb_id=_normalize_pdb_id(pdb_raw),
            recommended=bool(data["recommended"]),
            resolution_score=_required_float(data, "resolution_score"),
            rfree_score=_required_float(data, "rfree_score"),
            weighted_score=_required_float(data, "weighted_score"),
            coverage=_optional_float(data.get("coverage")),
            has_ligand=data.get("has_ligand"),
            method=data.get("method"),
            method_class=data.get("method_class"),
            organism=data.get("organism"),
            organism_class=data.get("organism_class"),
            resolution=_optional_float(data.get("resolution")),
            rfree=_optional_float(data.get("rfree")),
        )


def _candidates_from_dto(dto: dict[str, Any]) -> list[UniprotDiscoveryCandidate]:
    """Parse ``jobOutputs.candidates`` into result objects.

    An empty list is valid (unknown accession or no experimental PDBs).
    """
    outputs = _execution_outputs_dict(dto)
    raw_rows = outputs.get("candidates")
    if raw_rows is None:
        raise DeepOriginException(
            title="UniProt discovery results missing",
            message=(
                "Expected jobOutputs.candidates on the execution response "
                "(list may be empty)."
            ),
        ) from None
    if not isinstance(raw_rows, list):
        raise DeepOriginException(
            title="UniProt discovery results missing",
            message=(
                "Expected jobOutputs.candidates to be a list, "
                f"got {type(raw_rows).__name__}."
            ),
        ) from None

    rows: list[UniprotDiscoveryCandidate] = []
    for index, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            raise DeepOriginException(
                title=_INVALID_CANDIDATE_TITLE,
                message=(
                    f"Expected candidates[{index}] to be a dict, "
                    f"got {type(row).__name__}."
                ),
            ) from None
        rows.append(UniprotDiscoveryCandidate.from_json(row))
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


def _normalize_uniprot_accession(accession: str) -> str:
    """Validate and normalize a UniProtKB accession.

    Args:
        accession: Candidate UniProtKB accession (not an entry name).

    Returns:
        Uppercased accession.

    Raises:
        ValueError: If the accession shape is invalid.
    """
    cleaned = accession.strip()
    if not _UNIPROT_ACCESSION_RE.fullmatch(cleaned):
        raise ValueError(
            "uniprot_accession must be a 6- or 10-character UniProtKB "
            f"accession, got {accession!r}."
        )
    return cleaned.upper()


class UniprotDiscovery(Execution, SyncExecutableMixin):
    """Rank experimental PDBs for a UniProt accession via the platform tool.

    Call :meth:`run` for ranked candidates. Call :meth:`import_proteins` to
    sync recommended or selected PDB IDs into a project with
    ``uniprot_accession`` persisted.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["uniprot_discovery"]["tool_key"]

    @beartype
    def __init__(
        self,
        uniprot_accession: str,
        *,
        project_id: str | None = None,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["uniprot_discovery"]["tool_version"],
        client: DeepOriginClient | None = None,
        name: str | None = None,
    ) -> None:
        """Configure a UniProt discovery run.

        Args:
            uniprot_accession: UniProtKB accession (6 or 10 characters).
            project_id: Optional project id used by :meth:`import_proteins`
                when the call does not pass ``project_id``.
            tool_version: Platform tool version (defaults to ``"latest"``).
            client: Optional API client.
            name: Optional execution label.

        Raises:
            ValueError: If ``uniprot_accession`` is malformed.
        """
        super().__init__(client=client)
        self._uniprot_accession = _normalize_uniprot_accession(uniprot_accession)
        self._project_id = project_id
        self.tool_version = tool_version
        self.name = name
        self._candidates: list[UniprotDiscoveryCandidate] | None = None

    @property
    def uniprot_accession(self) -> str:
        """UniProtKB accession configured for this job."""
        return self._uniprot_accession

    @property
    def project_id(self) -> str | None:
        """Optional project id used as a default for :meth:`import_proteins`."""
        return self._project_id

    @property
    def candidates(self) -> list[UniprotDiscoveryCandidate] | None:
        """Cached candidates from the last successful :meth:`run`, if any."""
        return self._candidates

    def _make_inputs(self) -> dict[str, Any]:
        """Build UniProt discovery tool inputs."""
        return {"uniprot_accession": self._uniprot_accession}

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
    ) -> list[UniprotDiscoveryCandidate] | None:
        """Run UniProt discovery synchronously and return ranked candidates.

        Args:
            quote: Shorthand for ``approve_amount=0``. Returns ``None`` when the
                platform returns a quotation.
            approve_amount: Spend cap forwarded as ``approveAmount``.

        Returns:
            Ranked :class:`UniprotDiscoveryCandidate` rows (possibly empty), or
            ``None`` for quote-only responses.

        Raises:
            DeepOriginException: If the execution does not succeed or
                ``jobOutputs.candidates`` is missing/invalid.
        """
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
                title="UniProt discovery run did not succeed",
                message=(
                    f"Execution {eid!r} ended with status {final_status!r}: {reason!r}."
                ),
            ) from None

        candidates = _candidates_from_dto(response)
        self._candidates = candidates
        return candidates

    def _resolve_project_id(
        self,
        *,
        project_id: str | None,
    ) -> str:
        """Resolve a required project id for import.

        Args:
            project_id: Explicit project id from the import call.

        Returns:
            Non-empty project id string.

        Raises:
            DeepOriginException: If no project id can be resolved.
        """
        resolved = project_id or self._project_id
        if resolved is None and self.client is not None:
            resolved = self.client.project_id
        if resolved is None or not str(resolved).strip():
            raise DeepOriginException(
                title="Project required for UniProt import",
                message=(
                    "import_proteins requires a project_id argument, "
                    "UniprotDiscovery(project_id=...), or client.project_id."
                ),
            ) from None
        return str(resolved).strip()

    def _ensure_candidates(self) -> list[UniprotDiscoveryCandidate]:
        """Return cached candidates or run discovery.

        Returns:
            Non-quote candidate list from :meth:`run`.

        Raises:
            DeepOriginException: If discovery fails or returns a quote-only
                response unexpectedly.
        """
        if self._candidates is not None:
            return self._candidates
        candidates = self.run()
        if candidates is None:
            raise DeepOriginException(
                title="UniProt discovery did not return candidates",
                message=(
                    "Expected ranked candidates from run(); got a quote-only response."
                ),
            ) from None
        return candidates

    def _select_pdb_ids(
        self,
        candidates: list[UniprotDiscoveryCandidate],
        *,
        pdb_ids: list[str] | None,
    ) -> list[str]:
        """Resolve PDB IDs to import from candidates.

        Args:
            candidates: Discovery rows for this accession.
            pdb_ids: Explicit selections, or ``None`` for the recommended row.

        Returns:
            Normalized PDB IDs to import (order preserved).

        Raises:
            DeepOriginException: If the list is empty, no recommended row exists,
                or a requested PDB ID is not among the candidates.
        """
        if not candidates:
            raise DeepOriginException(
                title="No UniProt discovery candidates",
                message=(
                    f"No experimental PDB candidates for UniProt accession "
                    f"{self._uniprot_accession!r}."
                ),
            ) from None

        by_pdb = {row.pdb_id: row for row in candidates}

        if pdb_ids is None:
            recommended = [row for row in candidates if row.recommended]
            if not recommended:
                raise DeepOriginException(
                    title="No recommended UniProt candidate",
                    message=(
                        f"Candidates for {self._uniprot_accession!r} have no "
                        "recommended row."
                    ),
                ) from None
            return [recommended[0].pdb_id]

        selected: list[str] = []
        unknown: list[str] = []
        for raw in pdb_ids:
            try:
                pdb_id = _normalize_pdb_id(raw)
            except ValueError:
                unknown.append(raw)
                continue
            if pdb_id not in by_pdb:
                unknown.append(raw)
                continue
            if pdb_id not in selected:
                selected.append(pdb_id)

        if unknown:
            raise DeepOriginException(
                title="PDB IDs not in UniProt discovery candidates",
                message=(
                    f"These pdb_ids are not candidates for "
                    f"{self._uniprot_accession!r}: {unknown!r}."
                ),
            ) from None
        if not selected:
            raise DeepOriginException(
                title="No PDB IDs to import",
                message="pdb_ids must contain at least one candidate PDB ID.",
            ) from None
        return selected

    @beartype
    def import_proteins(
        self,
        pdb_ids: list[str] | None = None,
        *,
        project_id: str | None = None,
    ) -> list[Protein]:
        """Download and sync selected (or recommended) PDB candidates.

        Runs :meth:`run` if candidates are not already cached. Requires a
        resolvable project id. Each protein is synced with
        :attr:`~deeporigin.drug_discovery.structures.protein.Protein.uniprot_accession`
        set from this job.

        Args:
            pdb_ids: PDB IDs to import. Must appear in this accession's
                candidates. When ``None``, imports the single recommended
                candidate.
            project_id: Project to sync into. Falls back to the instance
                ``project_id``, then ``client.project_id``.

        Returns:
            Synced :class:`~deeporigin.drug_discovery.structures.protein.Protein`
            instances (one per selected PDB ID).

        Raises:
            DeepOriginException: If project is missing, candidates are empty,
                selection is invalid, or sync fails.
        """
        resolved_project = self._resolve_project_id(project_id=project_id)
        candidates = self._ensure_candidates()
        selected = self._select_pdb_ids(candidates, pdb_ids=pdb_ids)

        proteins: list[Protein] = []
        for pdb_id in selected:
            protein = Protein.from_pdb_id(pdb_id)
            protein.uniprot_accession = self._uniprot_accession
            protein.project_id = resolved_project
            protein.sync(client=self.client)
            proteins.append(protein)
        return proteins

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct a ``UniprotDiscovery`` from a tools execution DTO.

        Restores ``uniprot_accession`` from ``userInputs`` (falling back to
        ``inputs``).

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client.

        Returns:
            A ``UniprotDiscovery`` with ``id`` and domain inputs restored.

        Raises:
            ValueError: If stored inputs lack ``uniprot_accession``.
        """
        instance = super().from_dto(dto, client=client)
        inputs: dict[str, Any] = dto.get("userInputs") or dto.get("inputs") or {}
        raw = inputs.get("uniprot_accession")
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(
                "Cannot restore UniprotDiscovery: stored inputs lack uniprot_accession."
            )
        instance._uniprot_accession = _normalize_uniprot_accession(raw)
        instance._project_id = None
        try:
            instance._candidates = _candidates_from_dto(dto)
        except DeepOriginException:
            instance._candidates = None
        return instance
