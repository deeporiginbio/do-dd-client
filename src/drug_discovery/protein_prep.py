"""Recommend settings and prepare a protein with one mutable configuration.

Protein Prep uses two platform operations behind one user-facing object:

1. ``action="recommend"`` inventories chains, ligands, cofactors, and waters.
2. ``action="prepare"`` applies a digest-bound Selection, then runs
   loop modelling (unless ``model_missing_loops=False``) and protonation.

Usage::

    prep = ProteinPrep(protein)
    prep.recommend()
    prep.keep(["chain:A"])
    prep.skip(["ligand:LIG:A:100"])
    prep.model_missing_loops = False
    prepared = prep.run()
"""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
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
    PROTEIN_PREP_DISPLAY_NONE,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_NO_OUTPUT_PATHS_MSG,
    PROTEIN_PREP_NO_RECOMMENDATION_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_PDB_ID_PATTERN,
    PROTEIN_PREP_PDB_ID_REQUIRED_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_RECOMMEND_NOT_PREPARE_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_RUN_REQUIRES_LOOPS_OFF_MSG,  # ty:ignore[unresolved-import]
)

_PDB_ID_RE = re.compile(PROTEIN_PREP_PDB_ID_PATTERN)
_RESULT_TYPE_PREPARED_PROTEIN = "preparedprotein"
_VALID_ACTIONS = frozenset({"recommend", "prepare"})
_VALID_DECISIONS = frozenset({"keep", "review", "skip"})
_RESOLVED_DECISIONS = frozenset({"keep", "skip"})

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
    """Return a validated JSON-shape copy of a Selection.

    Args:
        selection: Selection object with ``source_sha256``, ``analyzer_version``,
            and ``decisions``.

    Returns:
        Copy with string keys and ``keep``/``review``/``skip`` decisions.

    Raises:
        ValueError: If required keys are missing, ``decisions`` is not an
            object, or a decision is not ``keep``, ``review``, or ``skip``.
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
                f"selection.decisions[{component_id!r}] must be 'keep', "
                f"'review', or 'skip', got {raw_decision!r}."
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
        Count of keep/review/skip decisions, or ``(none)`` when unset.
    """
    if selection is None:
        return PROTEIN_PREP_DISPLAY_NONE
    decisions = selection.get("decisions") or {}
    if not isinstance(decisions, dict) or not decisions:
        return PROTEIN_PREP_DISPLAY_NONE
    keep_n = sum(1 for value in decisions.values() if value == "keep")
    review_n = sum(1 for value in decisions.values() if value == "review")
    skip_n = sum(1 for value in decisions.values() if value == "skip")
    return f"{keep_n} keep, {review_n} review, {skip_n} skip"


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


def _selection_from_recommendation(
    recommendation: dict[str, Any],
) -> dict[str, Any]:
    """Build an editable Selection from recommendation output.

    Args:
        recommendation: ``jobOutputs.recommendation`` dict (``source_sha256``,
            ``analyzer_version``, ``components``).
    Returns:
        Selection with ``source_sha256``, ``analyzer_version``, and
        tri-state ``decisions``.

    Raises:
        ValueError: If required data is missing or a component is invalid.
    """
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
    """Recommend settings and prepare a protein.

    :meth:`recommend` blocks, updates :attr:`recommendation` and
    :attr:`selection`, and deliberately leaves :attr:`id` unset. Resolve
    ``review`` decisions with :meth:`keep` and :meth:`skip`, then call
    :meth:`run` for blocking loops-off preparation or :meth:`start` for
    asynchronous preparation.

    A prepare submission binds the object to its durable execution. Once
    :attr:`id` is set, configuration is permanently frozen.

    Attributes:
        protein: Constructor-only input protein structure.
        pdb_id: Mutable 4-character PDB ID for loop-modelling templates.
        selection: Editable keep/review/skip map. Reads return a copy.
        recommendation: Read-only analyzer evidence. Reads return a copy.
        model_missing_loops: Whether prepare models missing loops.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_key"]

    @beartype
    def __init__(
        self,
        protein: Protein,
        *,
        pdb_id: str | None = None,
        selection: dict[str, Any] | None = None,
        model_missing_loops: bool = True,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_version"],
        client: DeepOriginClient | None = None,
    ) -> None:
        """Create a ProteinPrep for the given protein.

        Call :meth:`recommend` to populate a Selection, or pass an existing
        Selection and prepare immediately.

        Args:
            protein: Protein structure to inventory or prepare. It cannot be
                replaced after construction.
            pdb_id: 4-character PDB ID for loop modelling. Inferred from
                ``protein.pdb_id`` when omitted.
            selection: Optional digest-bound Selection with ``source_sha256``,
                ``analyzer_version``, and ``decisions``.
            model_missing_loops: When ``False``, skip loop modelling and do
                not require ``pdb_id``.
            tool_version: Platform tool version pin.
            client: Optional API client. Uses the default if not provided.

        Raises:
            ValueError: If ``pdb_id`` or ``selection`` is invalid.
        """
        super().__init__(client=client)
        self.tool_version = tool_version
        self._protein = protein
        self._operation_kind: ProteinPrepAction | None = None
        self._pdb_id = _optional_pdb_id(protein=protein, pdb_id=pdb_id)
        self._selection = _copy_selection(selection) if selection is not None else None
        self._recommendation: dict[str, Any] | None = None
        self._model_missing_loops = model_missing_loops

    @property
    def protein(self) -> Protein:
        """Constructor-only protein used for recommendation and preparation."""
        return self._protein

    def _require_unbound(self, attribute: str) -> None:
        """Raise when configuration mutation follows durable submission.

        Args:
            attribute: Configuration attribute or operation being changed.

        Raises:
            AttributeError: If this object has a durable execution ID.
        """
        if self.id is not None:
            raise AttributeError(
                f"cannot assign to {attribute!r}: execution id is already set"
            )

    @property
    def pdb_id(self) -> str | None:
        """4-character PDB ID used for loop-modelling templates, if set."""
        return self._pdb_id

    @pdb_id.setter
    def pdb_id(self, value: str | None) -> None:
        """Set or clear ``pdb_id`` before this execution is submitted."""
        self._require_unbound("pdb_id")
        if value is None or not str(value).strip():
            self._pdb_id = None
            return
        self._pdb_id = _normalize_pdb_id(str(value))

    @property
    def selection(self) -> dict[str, Any] | None:
        """Editable Selection copy, or ``None`` before recommendation."""
        if self._selection is None:
            return None
        return _copy_selection(self._selection)

    @selection.setter
    def selection(self, value: dict[str, Any] | None) -> None:
        """Set or clear a copied Selection before prepare submission."""
        self._require_unbound("selection")
        self._selection = _copy_selection(value) if value is not None else None

    @property
    def recommendation(self) -> dict[str, Any] | None:
        """Analyzer evidence copy, or ``None`` when unavailable."""
        if self._recommendation is None:
            return None
        return deepcopy(self._recommendation)

    @property
    def model_missing_loops(self) -> bool:
        """Whether prepare will run loop modelling (unused for recommend)."""
        return self._model_missing_loops

    @model_missing_loops.setter
    def model_missing_loops(self, value: bool) -> None:
        """Set the loop-modelling flag before this execution is submitted."""
        self._require_unbound("model_missing_loops")
        self._model_missing_loops = bool(value)

    def _validate_for_submit(self) -> None:
        """Raise if current settings cannot prepare the protein.

        Raises:
            ValueError: If Selection is absent or unresolved, or loops-on
                prepare has no ``pdb_id``.
        """
        if self._selection is None:
            raise ValueError(
                "ProteinPrep has no selection. Call recommend() or assign selection "
                "before run() or start()."
            )
        unresolved = sorted(
            component_id
            for component_id, decision in self._selection["decisions"].items()
            if decision == "review"
        )
        if unresolved:
            joined = ", ".join(unresolved)
            raise ValueError(
                f"Resolve review decisions before preparation: {joined}. "
                "Use keep([...]) or skip([...])."
            )
        if self._model_missing_loops and not self._pdb_id:
            raise ValueError(PROTEIN_PREP_PDB_ID_REQUIRED_MSG)

    def _set_decisions(self, component_ids: Iterable[str], decision: str) -> None:
        """Set one decision for named Selection components.

        Args:
            component_ids: Iterable of component IDs to update.
            decision: ``keep`` or ``skip``.

        Raises:
            AttributeError: If this object is bound to an execution.
            TypeError: If *component_ids* is a bare string.
            ValueError: If Selection is absent or IDs are unknown.
        """
        self._require_unbound(decision)
        if isinstance(component_ids, str):
            raise TypeError(f"{decision}() requires an iterable of component IDs.")
        if self._selection is None:
            raise ValueError(
                f"{decision}() requires a selection. Call recommend() or assign "
                "selection first."
            )
        resolved_ids = [str(component_id) for component_id in component_ids]
        known_ids = self._selection["decisions"]
        unknown_ids = sorted(set(resolved_ids) - set(known_ids))
        if unknown_ids:
            joined = ", ".join(unknown_ids)
            raise ValueError(f"Unknown Selection component IDs: {joined}.")
        for component_id in resolved_ids:
            known_ids[component_id] = decision

    def keep(self, component_ids: Iterable[str]) -> None:
        """Mark named Selection components to keep.

        Args:
            component_ids: Iterable of component IDs from :attr:`recommendation`.
        """
        self._set_decisions(component_ids, "keep")

    def skip(self, component_ids: Iterable[str]) -> None:
        """Mark named Selection components to skip.

        Args:
            component_ids: Iterable of component IDs from :attr:`recommendation`.
        """
        self._set_decisions(component_ids, "skip")

    def _parameter_rows(self) -> list[tuple[str, str]]:
        """Return ``(name, value)`` rows for text and HTML display.

        Includes constructor parameters and, when set, execution ``name``,
        ``id``, and ``status``.
        """
        rows: list[tuple[str, str]] = [
            ("protein", _protein_display_value(self.protein)),
            (
                "pdb_id",
                self.pdb_id if self.pdb_id else PROTEIN_PREP_DISPLAY_NONE,
            ),
            (
                "model_missing_loops",
                str(self.model_missing_loops),
            ),
            ("selection", _format_selection_display(self.selection)),
            (
                "recommendation",
                (
                    "available"
                    if self._recommendation is not None
                    else PROTEIN_PREP_DISPLAY_NONE
                ),
            ),
            ("tool_version", str(self.tool_version)),
        ]
        if self.name:
            rows.append(("name", self.name))
        if self.id:
            rows.append(("id", self.id))
        status = getattr(self, "status", None)
        if status:
            rows.append(("status", str(status)))
        progress = getattr(self, "progress", None)
        if progress:
            rows.append(("progress", str(progress)))
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

    def _make_protein_prep_payload(
        self,
        *,
        action: ProteinPrepAction,
        sync: bool,
    ) -> dict[str, Any]:
        """Build the POST body for ``executions.create``.

        Top-level ``sync`` asks the platform to block on create (SystemPrep
        style). It is not an input field: the protein-prep schema has no
        ``sync`` property.

        Args:
            action: Internal platform operation.
            sync: Whether create blocks until completion.

        Returns:
            Payload for ``client.executions.create``.
        """
        inputs: dict[str, Any] = {
            "action": action,
            "protein": _protein_tool_input(self._protein),
        }
        if action == "prepare":
            self._validate_for_submit()
            assert self._selection is not None
            inputs["selection"] = {
                "source_sha256": self._selection["source_sha256"],
                "analyzer_version": self._selection["analyzer_version"],
                "decisions": dict(self._selection["decisions"]),
            }
            if not self._model_missing_loops:
                inputs["model_missing_loops"] = False
            if self._pdb_id:
                inputs["pdb_id"] = self._pdb_id
        return {
            "inputs": inputs,
            "outputs": {},
            "metadata": {},
            "sync": sync,
        }

    def recommend(self) -> None:
        """Recommend settings into this object without binding an execution ID.

        The platform operation is synchronous and persisted by the backend, but
        its execution ID is deliberately not copied onto this object. Repeated
        calls atomically replace :attr:`recommendation` and :attr:`selection`
        only after a complete recommendation is available.

        Raises:
            AttributeError: If this object is already bound to prepare.
            DeepOriginException: If recommendation output is unavailable.
        """
        self._require_unbound("recommend")
        self._ensure_protein_remote()
        dto = self._create_execution(
            data=self._make_protein_prep_payload(action="recommend", sync=True),
        )
        recommendation = self._recommendation_from_dto(dto)
        execution_id = dto.get("executionId")
        if recommendation is None and execution_id is not None:
            try:
                fetched = self.client.executions.get(  # ty:ignore[unresolved-attribute]
                    str(execution_id)
                )
            except Exception:
                fetched = None
            recommendation = self._recommendation_from_dto(fetched)
        if recommendation is None:
            raise DeepOriginException(
                title="Could not load protein recommendation",
                message=PROTEIN_PREP_NO_RECOMMENDATION_MSG,
            )
        selection = _selection_from_recommendation(recommendation)
        self._recommendation = deepcopy(recommendation)
        self._selection = selection

    def start(self) -> None:  # ty: ignore[invalid-method-override]
        """Submit preparation asynchronously and bind this object to it.

        Raises:
            ValueError: If already submitted or settings cannot prepare.
        """
        if self.id is not None or self.status is not None:
            raise ValueError("Cannot start: this ProteinPrep is already bound.")
        self._validate_for_submit()
        self._ensure_protein_remote()
        execution_dto = self._create_execution(
            data=self._make_protein_prep_payload(action="prepare", sync=False),
        )
        if execution_dto.get("executionId") is None:
            raise ValueError("Execution response must contain 'executionId'") from None
        self._operation_kind = "prepare"
        self.update_from_dto(execution_dto)

    def _require_loops_off_prepare(self) -> None:
        """Raise unless this instance may ``run()``.

        ``run()`` is only legal with ``model_missing_loops=False``.

        Raises:
            ValueError: If loop modelling is enabled.
        """
        if self._model_missing_loops:
            raise ValueError(PROTEIN_PREP_RUN_REQUIRES_LOOPS_OFF_MSG)

    def run(self) -> Protein:
        """Execute loops-off prepare synchronously (blocking).

        Only valid when :attr:`model_missing_loops` is ``False``.

        Returns:
            An in-memory prepared :class:`Protein`.

        Raises:
            ValueError: If already submitted or this is not loops-off prepare.
            DeepOriginException: If no prepared PDB path could be loaded.
        """
        if self.id is not None or self.status is not None:
            raise ValueError("Cannot run: this ProteinPrep is already bound.")
        self._require_loops_off_prepare()
        self._validate_for_submit()
        self._ensure_protein_remote()
        dto = self._create_execution(
            data=self._make_protein_prep_payload(action="prepare", sync=True),
        )
        self._operation_kind = "prepare"
        self.update_from_dto(dto)
        return self.get_results(dto)

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

        Rehydrates historical recommendation and preparation executions while
        keeping their operation kind private.

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
        instance._operation_kind = parsed.action
        instance._pdb_id = parsed.pdb_id
        instance._selection = parsed.selection
        instance._recommendation = instance._recommendation_from_dto(dto)
        if instance._selection is None and instance._recommendation is not None:
            instance._selection = _selection_from_recommendation(
                instance._recommendation
            )
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
        if self._operation_kind == "recommend":
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
