"""ProteinPrep -- recommend then prepare a protein (async, plus sync loops-off).

Protein Prep v2 is two steps on one tool key:

1. ``action="recommend"`` inventories chains, ligands, cofactors, and waters.
2. ``action="prepare"`` applies a digest-bound frozen Selection, then runs
   loop modelling (unless ``model_missing_loops=False``) and protonation.

``start()`` is always valid. ``run()`` is only valid for loops-off prepare
(blocks until the job finishes).

Usage::

    rec = ProteinPrep(protein)  # pdb_id optional; stored for as_prepare()
    rec.start()
    rec.wait()
    recommendation = rec.get_recommendation()

    prep = rec.as_prepare(model_missing_loops=False)
    prepared = prep.run()  # in-memory Protein; id is None
"""

from __future__ import annotations

from html import escape
import re
from typing import Any, Literal, NamedTuple, Self

from beartype import beartype

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import (
    AsyncExecutableMixin,
    SyncExecutableMixin,
)
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import (
    PROTEIN_PREP_NO_OUTPUT_PATHS_MSG,
    PROTEIN_PREP_NO_RECOMMENDATION_MSG,
    PROTEIN_PREP_PDB_ID_PATTERN,
    PROTEIN_PREP_PDB_ID_REQUIRED_MSG,
    PROTEIN_PREP_RECOMMEND_NOT_PREPARE_MSG,
    PROTEIN_PREP_RUN_REQUIRES_LOOPS_OFF_MSG,
)

_PDB_ID_RE = re.compile(PROTEIN_PREP_PDB_ID_PATTERN)
_RESULT_TYPE_PREPARED_PROTEIN = "preparedprotein"
_VALID_ACTIONS = frozenset({"recommend", "prepare"})
_VALID_DECISIONS = frozenset({"keep", "skip"})

ProteinPrepAction = Literal["recommend", "prepare"]


class _ParsedInputs(NamedTuple):
    """Fields reconstructed from a Protein Prep execution ``userInputs`` dict."""

    protein: dict[str, Any]
    action: ProteinPrepAction
    pdb_id: str | None
    selection: dict[str, Any] | None
    model_missing_loops: bool


def _protein_display_value(protein: Protein) -> str:
    """Return a short identity string for a protein used as ProteinPrep input.

    Args:
        protein: Input protein.

    Returns:
        Protein name, plus ``id`` and ``pdb_id`` when those are set.
    """
    extras: list[str] = []
    if protein.id:
        extras.append(f"id={protein.id!r}")
    if protein.pdb_id:
        extras.append(f"pdb_id={protein.pdb_id!r}")
    name = protein.name or "(unnamed)"
    if extras:
        return f"{name} ({', '.join(extras)})"
    return name


def _normalize_pdb_id(raw: str) -> str:
    """Return a validated 4-character PDB identifier.

    Args:
        raw: Candidate PDB ID.

    Returns:
        Stripped 4-character alphanumeric PDB identifier.

    Raises:
        ValueError: If ``raw`` does not match
            :data:`~deeporigin.utils.constants.PROTEIN_PREP_PDB_ID_PATTERN`.
    """
    resolved = str(raw).strip()
    if _PDB_ID_RE.fullmatch(resolved) is None:
        raise ValueError(
            "pdb_id must be a 4-character alphanumeric PDB identifier, "
            f"got {resolved!r}."
        )
    return resolved


def _optional_pdb_id(*, protein: Protein, pdb_id: str | None) -> str | None:
    """Return a PDB ID from *pdb_id* or ``protein.pdb_id``, or ``None``.

    Args:
        protein: Input protein that may already carry ``pdb_id``.
        pdb_id: Explicit override; used when set.

    Returns:
        Validated PDB ID, or ``None`` when neither source is set.

    Raises:
        ValueError: If a value is present but is not 4 alphanumeric characters.
    """
    raw = pdb_id if pdb_id is not None else protein.pdb_id
    if raw is None or not str(raw).strip():
        return None
    return _normalize_pdb_id(str(raw))


def _copy_selection(selection: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-shape copy of a frozen Selection.

    Args:
        selection: Selection object with ``source_sha256``, ``analyzer_version``,
            and ``decisions``.

    Returns:
        Copy with string keys and ``keep``/``skip`` decision values.

    Raises:
        ValueError: If required keys are missing, ``decisions`` is not an
            object, or a decision is not ``keep`` or ``skip``.
    """
    for key in ("source_sha256", "analyzer_version", "decisions"):
        if key not in selection:
            raise ValueError(f"selection must include {key!r}.")
    decisions_raw = selection["decisions"]
    if not isinstance(decisions_raw, dict):
        raise ValueError("selection.decisions must be an object.")
    if not decisions_raw:
        raise ValueError("selection.decisions must not be empty.")
    decisions: dict[str, str] = {}
    for component_id, raw_decision in decisions_raw.items():
        decision = str(raw_decision)
        if decision not in _VALID_DECISIONS:
            raise ValueError(
                f"selection.decisions[{component_id!r}] must be 'keep' or "
                f"'skip', got {raw_decision!r}."
            )
        decisions[str(component_id)] = decision
    return {
        "source_sha256": str(selection["source_sha256"]),
        "analyzer_version": str(selection["analyzer_version"]),
        "decisions": decisions,
    }


def _format_selection_display(selection: dict[str, Any] | None) -> str:
    """Format a frozen Selection for ProteinPrep display.

    Args:
        selection: Current selection, or ``None`` on a recommend run.

    Returns:
        Count of keep/skip decisions, or ``(none)`` when unset.
    """
    if selection is None:
        return "(none)"
    decisions = selection.get("decisions") or {}
    if not isinstance(decisions, dict) or not decisions:
        return "(none)"
    keep_n = sum(1 for value in decisions.values() if value == "keep")
    skip_n = sum(1 for value in decisions.values() if value == "skip")
    return f"{keep_n} keep, {skip_n} skip"


def _protein_tool_input(protein: Protein) -> dict[str, Any]:
    """Build the tool ``protein`` object from a Protein instance.

    Args:
        protein: Input protein with ``remote_path`` set.

    Returns:
        ``file_path`` plus ``id`` when the protein is registered.

    Raises:
        ValueError: If ``remote_path`` is missing.
    """
    file_path = protein.remote_path
    if not file_path or not str(file_path).strip():
        raise ValueError("Protein remote_path is required; sync the protein first.")
    payload: dict[str, Any] = {"file_path": str(file_path)}
    if protein.id:
        payload["id"] = str(protein.id)
    return payload


def _protein_from_prepared_data(
    data: dict[str, Any],
    *,
    fallback_pdb_id: str | None,
    fallback_name: str | None,
) -> Protein:
    """Build an in-memory Protein from a prepared-protein output dict.

    Args:
        data: ``jobOutputs.protein`` or result-explorer ``data`` payload.
        fallback_pdb_id: PDB ID used when the payload omits ``pdb_id``.
        fallback_name: Input protein name used to label the result.

    Returns:
        Protein with ``id`` unset and ``remote_path`` set to the prepared PDB.

    Raises:
        ValueError: If ``protein_pdb_file_path`` is missing or empty.
    """
    path = data.get("protein_pdb_file_path")
    if not path or not str(path).strip():
        raise ValueError(PROTEIN_PREP_NO_OUTPUT_PATHS_MSG)
    pdb_id = data.get("pdb_id") or fallback_pdb_id
    base_name = fallback_name.strip() if isinstance(fallback_name, str) else ""
    name = f"{base_name} (prepared)" if base_name else "prepared protein"
    return Protein(
        name=name,
        pdb_id=str(pdb_id) if pdb_id else None,
        structure=None,
        remote_path=str(path),
    )


def selection_from_recommendation(
    recommendation: dict[str, Any],
    *,
    resolve_review_as: str = "skip",
) -> dict[str, Any]:
    """Build a frozen Selection from a recommend ``jobOutputs`` payload.

    Each component's tri-state recommendation becomes a binary ``keep`` or
    ``skip``. Items marked ``review`` are mapped with *resolve_review_as*
    (default ``skip``).

    Args:
        recommendation: ``jobOutputs.recommendation`` dict (``source_sha256``,
            ``analyzer_version``, ``components``).
        resolve_review_as: Decision to apply to every ``review`` component.
            Must be ``keep`` or ``skip``.

    Returns:
        Selection with ``source_sha256``, ``analyzer_version``, and
        ``decisions``.

    Raises:
        ValueError: If the recommendation is missing required fields, a
            component has no id, or *resolve_review_as* is invalid.
    """
    if resolve_review_as not in _VALID_DECISIONS:
        raise ValueError(
            f"resolve_review_as must be 'keep' or 'skip', got {resolve_review_as!r}."
        )
    source_sha256 = recommendation.get("source_sha256")
    analyzer_version = recommendation.get("analyzer_version")
    components = recommendation.get("components")
    if not source_sha256 or not str(source_sha256).strip():
        raise ValueError("recommendation must include source_sha256.")
    if not analyzer_version or not str(analyzer_version).strip():
        raise ValueError("recommendation must include analyzer_version.")
    if not isinstance(components, list) or not components:
        raise ValueError("recommendation must include a non-empty components list.")

    decisions: dict[str, str] = {}
    for index, raw in enumerate(components):
        if not isinstance(raw, dict):
            raise ValueError(f"recommendation.components[{index}] must be an object.")
        component_id = raw.get("id")
        if not component_id or not str(component_id).strip():
            raise ValueError(f"recommendation.components[{index}] must include id.")
        rec = str(raw.get("recommendation") or "")
        if rec == "review":
            rec = resolve_review_as
        if rec not in _VALID_DECISIONS:
            raise ValueError(
                f"recommendation.components[{index}] recommendation must be "
                f"keep, skip, or review, got {raw.get('recommendation')!r}."
            )
        decisions[str(component_id)] = rec
    return {
        "source_sha256": str(source_sha256),
        "analyzer_version": str(analyzer_version),
        "decisions": decisions,
    }


class ProteinPrep(
    Execution,
    SyncExecutableMixin,
    AsyncExecutableMixin,
    NotebookWatchMixin,
):
    """Prepare a protein via ``deeporigin.protein-prep``.

    :meth:`start` is always valid. With no ``selection``, it runs
    ``action=recommend``. After that job finishes, :meth:`as_prepare` (or
    :meth:`from_recommendation`) builds a prepare run.

    :meth:`run` is only valid for prepare with ``model_missing_loops=False``
    (skips loop modelling). It blocks until the job finishes and returns an
    in-memory :class:`Protein` via :meth:`get_results`. Recommend and
    loops-on prepare must use :meth:`start`. Quoting is unused (billing is
    skipped).

    Displaying the object (``print(prep)`` or a notebook cell) lists every
    input you can set and its current value.

    Attributes:
        protein: Input protein structure (unchanged after the run).
        action: ``recommend`` or ``prepare``.
        pdb_id: 4-character PDB ID for loop-modelling templates (prepare).
        selection: Frozen keep/skip map (prepare only).
        model_missing_loops: When ``False``, prepare skips loop modelling.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_key"]

    @beartype
    def __init__(
        self,
        protein: Protein,
        *,
        action: ProteinPrepAction | None = None,
        pdb_id: str | None = None,
        selection: dict[str, Any] | None = None,
        model_missing_loops: bool = True,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_version"],
        client: DeepOriginClient | None = None,
    ) -> None:
        """Create a ProteinPrep for the given protein.

        With no ``selection``, this is a recommend run. Pass ``selection``
        (or use :meth:`as_prepare`) for prepare.

        Args:
            protein: Protein structure to inventory or prepare.
            action: ``recommend`` or ``prepare``. Inferred from whether
                ``selection`` is set when omitted.
            pdb_id: 4-character PDB ID for loop modelling. Inferred from
                ``protein.pdb_id`` when omitted. Required for prepare unless
                ``model_missing_loops`` is ``False``. Stored on recommend runs
                so :meth:`as_prepare` can reuse it.
            selection: Digest-bound frozen Selection (``source_sha256``,
                ``analyzer_version``, ``decisions``). Required for prepare.
            model_missing_loops: When ``False``, skip loop modelling and do
                not require ``pdb_id``. Ignored for recommend (must stay
                ``True``).
            tool_version: Platform tool version pin.
            client: Optional API client. Uses the default if not provided.

        Raises:
            ValueError: If ``action``/``selection`` disagree, ``pdb_id`` is
                missing for loops-on prepare, ``pdb_id`` is malformed, or
                ``selection`` is invalid.
        """
        super().__init__(client=client)
        self.tool_version = tool_version
        self._protein = protein
        resolved_action = _resolve_action(action=action, selection=selection)
        if resolved_action == "recommend" and not model_missing_loops:
            raise ValueError(
                "model_missing_loops=False requires action='prepare' and a "
                "selection. Run recommend first, then "
                "as_prepare(model_missing_loops=False)."
            )
        self._action: ProteinPrepAction = resolved_action
        self._pdb_id = _optional_pdb_id(protein=protein, pdb_id=pdb_id)
        self._selection = _copy_selection(selection) if selection is not None else None
        self._model_missing_loops = (
            True if resolved_action == "recommend" else model_missing_loops
        )
        if (
            resolved_action == "prepare"
            and self._model_missing_loops
            and not self._pdb_id
        ):
            raise ValueError(PROTEIN_PREP_PDB_ID_REQUIRED_MSG)

    @property
    def protein(self) -> Protein:
        """Input protein structure used for recommendation or preparation."""
        return self._protein

    @property
    def action(self) -> str:
        """``recommend`` or ``prepare``."""
        return self._action

    @property
    def pdb_id(self) -> str | None:
        """4-character PDB ID used for loop-modelling templates, if set."""
        return self._pdb_id

    @property
    def selection(self) -> dict[str, Any] | None:
        """Frozen Selection for prepare; ``None`` on a recommend run."""
        return self._selection

    @property
    def model_missing_loops(self) -> bool:
        """Whether prepare will run loop modelling (unused for recommend)."""
        return self._model_missing_loops

    def _parameter_rows(self) -> list[tuple[str, str]]:
        """Return ``(name, value)`` rows for text and HTML display.

        Includes constructor parameters and, when set, execution ``name``,
        ``id``, and ``status``.
        """
        rows: list[tuple[str, str]] = [
            ("protein", _protein_display_value(self.protein)),
            ("action", self.action),
            ("pdb_id", self.pdb_id if self.pdb_id else "(none)"),
            (
                "model_missing_loops",
                str(self.model_missing_loops),
            ),
            ("selection", _format_selection_display(self.selection)),
            ("tool_version", str(self.tool_version)),
        ]
        if self.name:
            rows.append(("name", self.name))
        if self.id:
            rows.append(("id", self.id))
        status = getattr(self, "status", None)
        if status:
            rows.append(("status", str(status)))
        return rows

    def __repr__(self) -> str:
        """Return a table of controllable parameters and their values."""
        from tabulate import tabulate

        return "ProteinPrep\n" + tabulate(
            self._parameter_rows(),
            headers=["Parameter", "Value"],
            tablefmt="rounded_grid",
        )

    __str__ = __repr__

    def _repr_html_(self) -> str:
        """Return an HTML table of parameters for Jupyter display.

        Returns:
            HTML fragment with a Parameter/Value table. Values are escaped.
        """
        header = (
            "<tr>"
            "<th style='text-align:left;padding:4px 16px 4px 0'>Parameter</th>"
            "<th style='text-align:left;padding:4px 0'>Value</th>"
            "</tr>"
        )
        body_parts: list[str] = []
        for name, value in self._parameter_rows():
            body_parts.append(
                "<tr>"
                "<td style='padding:4px 16px 4px 0;font-family:ui-monospace,"
                "SFMono-Regular,Menlo,monospace;white-space:nowrap'>"
                f"{escape(name, quote=False)}</td>"
                "<td style='padding:4px 0;font-family:ui-monospace,"
                "SFMono-Regular,Menlo,monospace'>"
                f"{escape(value, quote=False)}</td>"
                "</tr>"
            )
        return (
            "<div>"
            "<div style='font-weight:600;margin-bottom:4px'>ProteinPrep</div>"
            "<table style='border-collapse:collapse'>"
            f"<thead>{header}</thead><tbody>{''.join(body_parts)}</tbody>"
            "</table></div>"
        )

    def _ensure_protein_remote(self) -> None:
        """Upload/sync the protein and ensure ``remote_path`` is set."""
        self._protein.sync(lazy=True, client=self.client)
        self._protein.ensure_remote_path(client=self.client, label="Protein")

    def _make_payload(
        self,
        *,
        approve_amount: int | None,
        sync: bool,
    ) -> dict[str, Any]:
        """Build the POST body for ``executions.create``.

        Top-level ``sync`` asks the platform to block on create (SystemPrep
        style). It is not an input field: the protein-prep schema has no
        ``sync`` property.

        Args:
            approve_amount: Spend cap; omitted from the body when ``None``.
            sync: ``True`` for :meth:`run` (blocking create); ``False`` for
                :meth:`start`.

        Returns:
            Payload for ``client.executions.create``.
        """
        inputs: dict[str, Any] = {
            "action": self._action,
            "protein": _protein_tool_input(self._protein),
        }
        if self._action == "prepare":
            if self._selection is None:
                raise ValueError("prepare requires a selection.")
            inputs["selection"] = {
                "source_sha256": self._selection["source_sha256"],
                "analyzer_version": self._selection["analyzer_version"],
                "decisions": dict(self._selection["decisions"]),
            }
            if not self._model_missing_loops:
                inputs["model_missing_loops"] = False
            if self._pdb_id:
                inputs["pdb_id"] = self._pdb_id
        payload: dict[str, Any] = {
            "inputs": inputs,
            "outputs": {},
            "metadata": {},
            "sync": sync,
        }
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount
        return payload

    def _start_impl(self, *, approve_amount: int | None = None, **kwargs: Any) -> None:
        """Submit protein prep as a persisted async execution.

        Args:
            approve_amount: Spend cap forwarded to the platform. ``None`` omits
                the field (the tool has no quote).
            **kwargs: Unused; accepted for mixin compatibility.
        """
        _ = kwargs
        self._ensure_protein_remote()
        execution_dto = self._create_execution(
            data=self._make_payload(approve_amount=approve_amount, sync=False),
        )
        if execution_dto.get("executionId") is None:
            raise ValueError("Execution response must contain 'executionId'") from None
        self.update_from_dto(execution_dto)

    def _require_loops_off_prepare(self) -> None:
        """Raise unless this instance may ``run()``.

        ``run()`` is only legal for ``action='prepare'`` with
        ``model_missing_loops=False``.

        Raises:
            ValueError: If this is a recommend run or loops-on prepare.
        """
        if self._action != "prepare" or self._model_missing_loops:
            raise ValueError(PROTEIN_PREP_RUN_REQUIRES_LOOPS_OFF_MSG)

    def run(
        self,
        *,
        quote: bool = False,
        approve_amount: int | None = None,
    ) -> Protein | None:
        """Execute loops-off prepare synchronously (blocking).

        Only valid when :attr:`action` is ``prepare`` and
        :attr:`model_missing_loops` is ``False``. Recommend and loops-on
        prepare must use :meth:`start`.

        Pass ``quote=True`` (or ``approve_amount=0``) to request a cost
        estimate only. Billing is skipped for this tool, so quoting is
        unused. If the platform returns a ``Quoted`` DTO, ``None`` is
        returned.

        Args:
            quote: Shorthand for ``approve_amount=0``.
            approve_amount: Spend cap forwarded to the platform as
                ``approveAmount``.

        Returns:
            An in-memory :class:`Protein`, or ``None`` when the platform
            responds with ``Quoted`` status.

        Raises:
            ValueError: If this is not loops-off prepare.
            DeepOriginException: If no prepared PDB path could be loaded.
        """
        self._require_loops_off_prepare()
        self._ensure_protein_remote()
        resolved_amount = 0 if quote else approve_amount
        dto = self._create_execution(
            data=self._make_payload(approve_amount=resolved_amount, sync=True),
        )
        self.update_from_dto(dto)

        if self.status == "Quoted":
            return None

        return self.get_results(dto)

    @staticmethod
    def selection_from_recommendation(
        recommendation: dict[str, Any],
        *,
        resolve_review_as: str = "skip",
    ) -> dict[str, Any]:
        """Build a frozen Selection from a recommend result.

        See :func:`selection_from_recommendation`.
        """
        return selection_from_recommendation(
            recommendation,
            resolve_review_as=resolve_review_as,
        )

    @classmethod
    def from_recommendation(
        cls,
        protein: Protein,
        recommendation: dict[str, Any],
        *,
        pdb_id: str | None = None,
        model_missing_loops: bool = True,
        resolve_review_as: str = "skip",
        tool_version: str = TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_version"],
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Build a prepare ``ProteinPrep`` from a recommend payload.

        Args:
            protein: Same protein that was recommended (same structure bytes).
            recommendation: ``jobOutputs.recommendation`` dict.
            pdb_id: PDB ID for loop modelling. Inferred from
                ``protein.pdb_id`` when omitted.
            model_missing_loops: When ``False``, skip loop modelling.
            resolve_review_as: Binary decision for every ``review`` component.
            tool_version: Platform tool version pin.
            client: Optional API client.

        Returns:
            A ``ProteinPrep`` with ``action='prepare'`` ready for ``start()``
            or, when ``model_missing_loops=False``, ``run()``.
        """
        selection = selection_from_recommendation(
            recommendation,
            resolve_review_as=resolve_review_as,
        )
        return cls(
            protein,
            action="prepare",
            pdb_id=pdb_id,
            selection=selection,
            model_missing_loops=model_missing_loops,
            tool_version=tool_version,
            client=client,
        )

    def as_prepare(
        self,
        *,
        pdb_id: str | None = None,
        model_missing_loops: bool = True,
        resolve_review_as: str = "skip",
    ) -> ProteinPrep:
        """Return a prepare ``ProteinPrep`` from this completed recommend run.

        Args:
            pdb_id: PDB ID for loop modelling. Defaults to this instance's
                ``pdb_id`` (constructor / ``protein.pdb_id``).
            model_missing_loops: When ``False``, skip loop modelling.
            resolve_review_as: Binary decision for every ``review`` component.

        Returns:
            A new ``ProteinPrep`` with ``action='prepare'``. Call ``run()``
            when ``model_missing_loops=False``, or ``start()`` otherwise.

        Raises:
            ValueError: If this instance is not a recommend run, or no
                recommendation is available yet.
        """
        if self._action != "recommend":
            raise ValueError(
                "as_prepare() requires a recommend run. Construct ProteinPrep "
                "without selection and call start() first."
            )
        recommendation = self.get_recommendation()
        resolved_pdb_id = pdb_id if pdb_id is not None else self._pdb_id
        return type(self).from_recommendation(
            self._protein,
            recommendation,
            pdb_id=resolved_pdb_id,
            model_missing_loops=model_missing_loops,
            resolve_review_as=resolve_review_as,
            tool_version=self.tool_version,
            client=self.client,
        )

    @staticmethod
    def _parse_inputs_dict(inputs: dict[str, Any]) -> _ParsedInputs:
        """Parse stored userInputs into protein, action, and prepare fields.

        Accepts Protein Prep v2 (``action`` + optional ``selection``) and v1
        (keep/remove lists, treated as prepare with no selection).

        Args:
            inputs: Execution ``userInputs`` (or ``inputs``) dict.

        Returns:
            Parsed protein dict, action, optional ``pdb_id``, optional
            selection, and ``model_missing_loops``.

        Raises:
            ValueError: If ``protein`` is not an object, ``action`` is
                unknown, or ``pdb_id`` / ``selection`` are invalid.
        """
        protein_input = inputs.get("protein") or {}
        if not isinstance(protein_input, dict):
            raise ValueError("Missing 'protein' object in execution userInputs.")

        raw_action = inputs.get("action")
        if raw_action is None:
            action: ProteinPrepAction = "prepare"
        elif raw_action in _VALID_ACTIONS:
            action = raw_action  # type: ignore[assignment]
        else:
            raise ValueError(
                f"Unknown ProteinPrep action {raw_action!r}; expected "
                "'recommend' or 'prepare'."
            )

        raw_pdb_id = inputs.get("pdb_id")
        pdb_id: str | None = None
        if raw_pdb_id is not None and str(raw_pdb_id).strip():
            pdb_id = _normalize_pdb_id(str(raw_pdb_id))

        raw_selection = inputs.get("selection")
        selection: dict[str, Any] | None = None
        if raw_selection is not None:
            if not isinstance(raw_selection, dict):
                raise ValueError("Invalid selection in execution inputs.")
            selection = _copy_selection(raw_selection)

        raw_loops = inputs.get("model_missing_loops")
        model_missing_loops = True if raw_loops is None else bool(raw_loops)

        return _ParsedInputs(
            protein=protein_input,
            action=action,
            pdb_id=pdb_id,
            selection=selection,
            model_missing_loops=model_missing_loops,
        )

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct a ``ProteinPrep`` from a tools execution DTO.

        Rehydrates ``protein``, ``action``, ``pdb_id``, ``selection``, and
        ``model_missing_loops`` from ``userInputs`` (falling back to
        ``inputs``).

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client. Uses the default if not provided.

        Returns:
            A ``ProteinPrep`` with ``id``, lifecycle fields, and domain inputs
            set.

        Raises:
            ValueError: If stored inputs are missing ``protein`` or use an
                unknown ``action``.
        """
        instance = super().from_dto(dto, client=client)
        inputs: dict[str, Any] = dto.get("userInputs") or dto.get("inputs") or {}
        parsed = cls._parse_inputs_dict(inputs)

        protein_id = parsed.protein.get("id")
        file_path = parsed.protein.get("file_path")
        if protein_id is not None:
            instance._protein = Protein.from_id(
                str(protein_id),
                client=client,
                download=False,
                remote_path_override=file_path,
            )
        else:
            if parsed.pdb_id:
                name = parsed.pdb_id
            elif file_path:
                name = str(file_path).rsplit("/", 1)[-1]
            else:
                name = "protein"
            instance._protein = Protein(
                name=name,
                pdb_id=parsed.pdb_id,
                structure=None,
                remote_path=file_path,
            )
        instance._action = parsed.action
        instance._pdb_id = parsed.pdb_id
        instance._selection = parsed.selection
        instance._model_missing_loops = parsed.model_missing_loops
        return instance

    def _protein_from_outputs(self, data: dict[str, Any]) -> Protein:
        """Build the in-memory result Protein from an output dict.

        Args:
            data: Prepared-protein payload (``jobOutputs.protein`` or explorer
                ``data``).

        Returns:
            In-memory Protein wrapping the prepared PDB path.
        """
        return _protein_from_prepared_data(
            data,
            fallback_pdb_id=self._pdb_id,
            fallback_name=self._protein.name,
        )

    def _recommendation_from_dto(
        self,
        dto: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Return ``jobOutputs.recommendation`` from *dto* when present."""
        if not isinstance(dto, dict):
            return None
        job_outputs = dto.get("jobOutputs")
        if not isinstance(job_outputs, dict):
            return None
        recommendation = job_outputs.get("recommendation")
        if isinstance(recommendation, dict) and recommendation.get("components"):
            return recommendation
        return None

    @beartype
    def get_recommendation(self, dto: dict[str, Any] | None = None) -> dict[str, Any]:
        """Load the component inventory from a recommend run.

        Args:
            dto: Optional execution payload. Passing it avoids an extra GET
                when ``jobOutputs.recommendation`` is already in hand.

        Returns:
            The ``recommendation`` object (``source_sha256``,
            ``analyzer_version``, ``components``, ``chain_id_mapping``).

        Raises:
            ValueError: If :attr:`id` is unset.
            DeepOriginException: If no recommendation could be loaded.
        """
        exec_id = self._ensure_id()
        for candidate in (dto, self._dto):
            recommendation = self._recommendation_from_dto(candidate)
            if recommendation is not None:
                return recommendation
        try:
            exec_dto = self.client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
        except Exception:
            exec_dto = None
        recommendation = self._recommendation_from_dto(exec_dto)
        if recommendation is not None:
            return recommendation
        raise DeepOriginException(
            title="Could not load protein recommendation",
            message=PROTEIN_PREP_NO_RECOMMENDATION_MSG,
        )

    @beartype
    def get_results(self, dto: dict[str, Any] | None = None) -> Protein:
        """Load the prepared protein as an in-memory :class:`Protein`.

        Tries result-explorer rows for this execution
        (``result_type=preparedprotein``), then ``jobOutputs.protein``. Does not
        PATCH or create a proteins-table record; the returned Protein has
        ``id is None`` and ``remote_path`` set to the prepared PDB.

        Args:
            dto: Optional execution payload. Passing it avoids an extra GET
                when the result-explorer path fails but ``jobOutputs`` is
                already in hand.

        Returns:
            An in-memory :class:`Protein` for the prepared structure.

        Raises:
            ValueError: If :attr:`id` is unset.
            DeepOriginException: If this was a recommend run, or no prepared
                PDB path could be loaded.
        """
        exec_id = self._ensure_id()
        if self._action == "recommend":
            raise DeepOriginException(
                title="Could not load prepared protein",
                message=PROTEIN_PREP_RECOMMEND_NOT_PREPARE_MSG,
            )

        try:
            response = self.client.results.get(
                result_type=_RESULT_TYPE_PREPARED_PROTEIN,
                compute_job_id=exec_id,
                limit=1,
            )
            records = response.get("data") or []
            if records:
                data = records[0].get("data") or {}
                if isinstance(data, dict) and data.get("protein_pdb_file_path"):
                    return self._protein_from_outputs(data)
        except Exception:
            pass

        try:
            exec_dto = dto
            if exec_dto is None:
                exec_dto = self.client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
            jo = exec_dto.get("jobOutputs") if isinstance(exec_dto, dict) else None
            protein_out = jo.get("protein") if isinstance(jo, dict) else None
            if isinstance(protein_out, dict):
                return self._protein_from_outputs(protein_out)
        except ValueError:
            pass

        raise DeepOriginException(
            title="Could not load prepared protein",
            message=PROTEIN_PREP_NO_OUTPUT_PATHS_MSG,
        )


def _resolve_action(
    *,
    action: str | None,
    selection: dict[str, Any] | None,
) -> ProteinPrepAction:
    """Infer or validate ``recommend`` vs ``prepare``.

    Args:
        action: Explicit action, or ``None`` to infer from *selection*.
        selection: Frozen Selection, or ``None`` for recommend.

    Returns:
        ``recommend`` or ``prepare``.

    Raises:
        ValueError: If *action* is unknown, or *action* and *selection*
            disagree.
    """
    if action is not None and action not in _VALID_ACTIONS:
        raise ValueError(f"action must be 'recommend' or 'prepare', got {action!r}.")
    if action == "recommend":
        if selection is not None:
            raise ValueError("action='recommend' does not accept a selection.")
        return "recommend"
    if action == "prepare":
        if selection is None:
            raise ValueError(
                "action='prepare' requires a selection. Run recommend first, "
                "or pass selection= from selection_from_recommendation()."
            )
        return "prepare"
    return "prepare" if selection is not None else "recommend"
