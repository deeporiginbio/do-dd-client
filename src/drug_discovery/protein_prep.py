"""Recommend settings and prepare a protein with one mutable configuration.

``ProteinPrep`` is the sole public preparation session. It uses
``deeporigin.protein-prep`` v10 for :meth:`recommend` and all :meth:`run` /
:meth:`start` prepare paths. Extracting a ligand also requests one crystal-ligand
Pocket per extract (``find_pockets=from-crystal-ligand``). Novel pockets use the
platform workflow path; use :meth:`start` (not blocking :meth:`run`) for those.

Set :attr:`find_pockets` to ``"novel"`` or ``"from-crystal-ligand"`` to include
pockets in prepare. :meth:`get_results` returns the prepared
:class:`~deeporigin.drug_discovery.structures.protein.Protein`; use
:meth:`get_pockets` and :meth:`get_crystal_poses` for other prepare artifacts.
Structure reports are out of band — use :class:`~deeporigin.drug_discovery.structure_report.StructureReport`.

Usage::

    prep = ProteinPrep(protein)
    prep.recommend()
    prep.keep(kind="water")
    prep.skip(decision="review")
    prep.model_missing_loops = False
    prepared = prep.run()
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from html import escape
import re
from typing import Any, Literal, NamedTuple, Self

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery.execution import (
    Execution,
    _execution_outputs_dict,
)
from deeporigin.drug_discovery.execution_mixins import (
    AsyncExecutableMixin,
    SyncExecutableMixin,
)
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.structures.pose import Pose, PoseSet
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import (
    TOOL_KEYS_AND_VERSIONS,
    is_success_status,
    normalize_platform_status,
)
from deeporigin.utils.constants import (
    EXECUTION_LIST_ORDER_CREATED_DESC,
    PROTEIN_PREP_COMPONENT_KINDS,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_DATAFRAME_ID_COLUMN_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_DISPLAY_NONE,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_KEEP_SKIP_EMPTY_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_KEEP_SKIP_MIXED_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_NO_OUTPUT_PATHS_MSG,
    PROTEIN_PREP_NO_RECOMMENDATION_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_PDB_ID_PATTERN,
    PROTEIN_PREP_PDB_ID_REQUIRED_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_POCKETS_EXCLUDED_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_RECOMMEND_NOT_PREPARE_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_RECOMMENDATION_COLUMNS,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_REGISTERED_PROTEIN_REQUIRED_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_RUN_REQUIRES_NOVEL_START_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_SUBTYPE_REQUIRES_RECOMMENDATION_MSG,  # ty:ignore[unresolved-import]
    QUOTE_APPROVE_AMOUNT,
)

_PDB_ID_RE = re.compile(PROTEIN_PREP_PDB_ID_PATTERN)
_RESULT_TYPE_PREPARED_PROTEIN = "preparedprotein"
_RESULT_TYPE_POCKET = "pocket"
_RESULT_TYPE_POSE = "pose"
_PROTEIN_PREP_CRYSTAL_POSE_ORIGIN = "cocrystal"
_VALID_ACTIONS = frozenset({"recommend", "prepare"})
_VALID_ANALYZER_RECOMMENDATIONS = frozenset({"keep", "review", "skip", "extract"})
_VALID_DECISIONS = frozenset({"keep", "review", "skip", "extract"})
_RESOLVED_DECISIONS = frozenset({"keep", "skip", "extract"})
_PROTEIN_PREP_TOOL_KEY = TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_key"]
_DEFAULT_POCKET_COUNT = 1
_DEFAULT_POCKET_MIN_SIZE = 30
_DEFAULT_POCKET_RADIUS = 10.0
_VALID_POCKET_MODES = frozenset(
    {"auto-find", "define-by-selection", "from-crystal-ligand"}
)
_VALID_BOX_GEOMETRIES = frozenset({"ligand-extents", "fixed-radius"})
_DEFINE_BY_SELECTION_COMPOSITE_MSG = (
    "ProteinPrep does not support selection-defined pockets. "
    "Use the standalone PocketFinder tool for expert selection-defined pockets."
)

ProteinPrepAction = Literal["recommend", "prepare"]
ProteinPrepFindPockets = Literal["no", "from-crystal-ligand", "novel"]
_PrepPocketMode = Literal["auto-find", "define-by-selection", "from-crystal-ligand"]
BoxGeometry = Literal["ligand-extents", "fixed-radius"]
_VALID_FIND_POCKETS = frozenset({"no", "from-crystal-ligand", "novel"})


class _ParsedInputs(NamedTuple):
    """Fields reconstructed from a Protein Prep execution ``userInputs`` dict."""

    protein: dict[str, Any]
    action: ProteinPrepAction
    pdb_id: str | None
    selection: dict[str, Any] | None
    model_missing_loops: bool
    model_missing_loops_explicit: bool
    pocket: dict[str, Any] | None


def _selection_has_ligand_extract(selection: Mapping[str, Any] | None) -> bool:
    """Return whether a Selection extracts at least one ligand component."""
    if not isinstance(selection, Mapping):
        return False
    decisions = selection.get("decisions")
    if not isinstance(decisions, Mapping):
        return False
    return any(
        str(component_id).startswith("ligand:") and decision == "extract"
        for component_id, decision in decisions.items()
    )


def _pocket_input_from_inputs(inputs: dict[str, Any]) -> dict[str, Any] | None:
    """Extract current flat or legacy nested pocket fields from tool inputs."""
    raw_pocket = inputs.get("pocket")
    if raw_pocket is not None:
        if not isinstance(raw_pocket, dict):
            raise ValueError("Invalid pocket in execution inputs.")
        return dict(raw_pocket)

    find_pockets = inputs.get("find_pockets")
    if find_pockets not in {"novel", "from-crystal-ligand"}:
        return None
    pocket = {"find_pockets": find_pockets}
    for key in (
        "pocket_count",
        "pocket_min_size",
        "crystal_ligand",
        "box_geometry",
        "box_padding",
        "pocket_radius",
    ):
        if key in inputs:
            pocket[key] = inputs[key]
    return pocket


@dataclass
class _PrepPocketInput:
    """Internal Pocket Finder payload builder for :class:`ProteinPrep`.

    ``auto-find`` maps to platform ``find_pockets='novel'``.
    ``from-crystal-ligand`` maps to ``find_pockets='from-crystal-ligand'``.
    """

    mode: _PrepPocketMode = "auto-find"
    pocket_count: int | None = None
    pocket_min_size: int | float | None = None
    selections: list[Any] | None = None
    pocket_radius: float | None = None
    align_to_pocket: bool | None = None
    crystal_ligand: Ligand | None = None
    ligand_id: str | None = None
    component_id: str | None = None
    box_geometry: BoxGeometry | None = None
    box_padding: float | None = None
    _crystal_ligand_remote_path: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Validate mode-specific fields after construction."""
        self.validate()

    def validate(self) -> None:
        """Raise if mode and fields are inconsistent.

        Raises:
            ValueError: If mode/kwargs mixing or structural checks fail.
        """
        if self.mode not in _VALID_POCKET_MODES:
            raise ValueError(
                f"mode must be one of {sorted(_VALID_POCKET_MODES)}, got {self.mode!r}."
            )
        if self.mode == "auto-find":
            self._validate_auto_find()
        elif self.mode == "define-by-selection":
            self._validate_define_by_selection()
        else:
            self._validate_crystal_ligand()

    def _reject_auto_only(self) -> None:
        """Reject auto-find-only fields outside auto-find mode."""
        if self.pocket_count is not None or self.pocket_min_size is not None:
            raise ValueError(
                "pocket_count and pocket_min_size are only valid when mode is "
                "'auto-find'."
            )

    def _reject_selection_only(self) -> None:
        """Reject define-by-selection-only fields outside that mode."""
        if self.selections is not None or self.align_to_pocket is not None:
            raise ValueError(
                "selections and align_to_pocket are only valid when mode is "
                "'define-by-selection'."
            )

    def _reject_crystal_only(self) -> None:
        """Reject crystal-ligand-only fields outside that mode."""
        if any(
            value is not None
            for value in (
                self.crystal_ligand,
                self.ligand_id,
                self.component_id,
                self._crystal_ligand_remote_path,
            )
        ):
            raise ValueError(
                "crystal_ligand, ligand_id, and component_id are only valid "
                "when mode is 'from-crystal-ligand'."
            )
        if self.box_geometry is not None or self.box_padding is not None:
            raise ValueError(
                "box_geometry and box_padding are only valid when mode is "
                "'from-crystal-ligand'."
            )

    def _validate_auto_find(self) -> None:
        """Normalize and validate auto-find fields."""
        self._reject_selection_only()
        self._reject_crystal_only()
        if self.pocket_radius is not None:
            raise ValueError("pocket_radius is not valid when mode is 'auto-find'.")
        count = (
            _DEFAULT_POCKET_COUNT
            if self.pocket_count is None
            else int(self.pocket_count)
        )
        min_size = (
            _DEFAULT_POCKET_MIN_SIZE
            if self.pocket_min_size is None
            else float(self.pocket_min_size)
        )
        if count < 1 or min_size < 1:
            raise ValueError(
                "pocket_count and pocket_min_size must both be at least 1."
            )
        self.pocket_count = count
        self.pocket_min_size = min_size

    def _validate_define_by_selection(self) -> None:
        """Normalize and validate define-by-selection fields."""
        self._reject_auto_only()
        self._reject_crystal_only()
        from deeporigin.drug_discovery.pocket_finder import _normalize_selections

        if not isinstance(self.selections, list) or not self.selections:
            raise ValueError(
                "selections must be a non-empty list when mode is "
                "'define-by-selection'."
            )
        self.selections = _normalize_selections(self.selections)
        radius = (
            _DEFAULT_POCKET_RADIUS
            if self.pocket_radius is None
            else float(self.pocket_radius)
        )
        if radius <= 0:
            raise ValueError("pocket_radius must be greater than 0.")
        self.pocket_radius = radius
        self.align_to_pocket = (
            False if self.align_to_pocket is None else bool(self.align_to_pocket)
        )

    def _validate_crystal_ligand(self) -> None:
        """Validate from-crystal-ligand source and geometry fields."""
        self._reject_auto_only()
        self._reject_selection_only()
        sources = [
            self.crystal_ligand is not None,
            bool(self.ligand_id and str(self.ligand_id).strip()),
            bool(self.component_id and str(self.component_id).strip()),
            bool(self._crystal_ligand_remote_path),
        ]
        if sum(1 for value in sources if value) != 1:
            raise ValueError(
                "Provide exactly one of crystal_ligand, ligand_id, or component_id."
            )
        if (
            self.box_geometry is not None
            and self.box_geometry not in _VALID_BOX_GEOMETRIES
        ):
            raise ValueError(
                f"box_geometry must be one of {sorted(_VALID_BOX_GEOMETRIES)}."
            )
        if self.box_padding is not None and float(self.box_padding) < 0:
            raise ValueError("box_padding must be non-negative.")
        if self.pocket_radius is not None and float(self.pocket_radius) <= 0:
            raise ValueError("pocket_radius must be greater than 0.")

    def ensure_remote(self, *, client: DeepOriginClient) -> None:
        """Upload an external crystal ligand when present.

        Args:
            client: API client used for sync/upload.
        """
        if self.crystal_ligand is None:
            return
        _ensure_crystal_ligand_remote(self.crystal_ligand, client=client)

    def to_tool_input(self) -> dict[str, Any]:
        """Return flat ``find_pockets`` fields for preparation tool inputs.

        Returns:
            Fields to merge into the preparation tool's ``inputs`` object.

        Raises:
            ValueError: If settings are invalid or a crystal ligand path is
                missing.
        """
        self.validate()
        if self.mode == "auto-find":
            return {
                "find_pockets": "novel",
                "pocket_count": int(self.pocket_count or _DEFAULT_POCKET_COUNT),
                "pocket_min_size": (
                    self.pocket_min_size
                    if self.pocket_min_size is not None
                    else _DEFAULT_POCKET_MIN_SIZE
                ),
            }
        if self.mode == "define-by-selection":
            raise ValueError(_DEFINE_BY_SELECTION_COMPOSITE_MSG)
        if self.crystal_ligand is not None:
            path = self.crystal_ligand.remote_path
            if not path or not str(path).strip():
                raise ValueError(
                    "crystal_ligand remote_path is required; sync the crystal "
                    "ligand first."
                )
            crystal: dict[str, str] = {"file_path": str(path)}
        elif self._crystal_ligand_remote_path:
            crystal = {"file_path": str(self._crystal_ligand_remote_path)}
        elif self.ligand_id:
            crystal = {"ligand_id": str(self.ligand_id)}
        else:
            crystal = {"component_id": str(self.component_id)}
        pocket: dict[str, Any] = {
            "find_pockets": "from-crystal-ligand",
            "crystal_ligand": crystal,
        }
        if self.box_geometry == "fixed-radius" and self.pocket_radius is not None:
            pocket["pocket_radius"] = float(self.pocket_radius)
        if self.box_geometry is not None:
            pocket["box_geometry"] = self.box_geometry
        if self.box_padding is not None:
            pocket["box_padding"] = float(self.box_padding)
        return pocket

    @classmethod
    def from_tool_input(cls, data: dict[str, Any]) -> _PrepPocketInput | None:
        """Rebuild config from stored flat or legacy nested pocket inputs.

        Args:
            data: Pocket-related fields from execution ``userInputs``.

        Returns:
            Rehydrated config (``crystal_ligand`` Ligand is not restored), or
            ``None`` when ``find_pockets='from-crystal-ligand'`` was inferred
            from a Selection extract with no explicit crystal source.

        Raises:
            ValueError: If ``data`` is not a valid pocket object.
        """
        if not isinstance(data, dict):
            raise ValueError("pocket input must be an object.")
        mode = data.get("find_pockets") or data.get("mode") or "auto-find"
        if mode in {"novel", "auto-find"}:
            return cls(
                mode="auto-find",
                pocket_count=data.get("pocket_count"),
                pocket_min_size=data.get("pocket_min_size"),
            )
        if mode == "define-by-selection":
            return cls(
                mode="define-by-selection",
                selections=data.get("selections"),
                pocket_radius=data.get("pocket_radius"),
                align_to_pocket=data.get("align_to_pocket"),
            )
        crystal = data.get("crystal_ligand") or {}
        if not isinstance(crystal, dict):
            raise ValueError("pocket.crystal_ligand must be an object.")
        remote = crystal.get("file_path")
        ligand_id = crystal.get("ligand_id") or data.get("ligand_id")
        component_id = crystal.get("component_id") or data.get("component_id")
        # Loops-off extract-via-Selection serializes find_pockets alone (no
        # crystal_ligand object); rehydrate as unset pocket — get_pockets()
        # still detects the Selection extract flag.
        if not remote and not ligand_id and not component_id:
            return None
        return cls(
            mode="from-crystal-ligand",
            ligand_id=ligand_id,
            component_id=component_id,
            pocket_radius=data.get("pocket_radius"),
            box_geometry=data.get("box_geometry"),
            box_padding=data.get("box_padding"),
            _crystal_ligand_remote_path=str(remote) if remote else None,
        )


def _dto_created_at(dto: dict[str, Any]) -> str:
    """Return a sortable ``createdAt`` string from an execution DTO."""
    value = dto.get("createdAt") or ""
    return str(value)


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


def _prepare_protein_card_title(protein: Protein) -> str:
    """Return the primary label for Prepare Protein notebook cards.

    Prefers platform ``id``, then ``name``, then ``pdb_id``.
    """
    if protein.id:
        return str(protein.id)
    name = (protein.name or "").strip()
    if name:
        return name
    if protein.pdb_id:
        return str(protein.pdb_id)
    return "protein"


_FIND_POCKETS_DISPLAY: dict[str, str] = {
    "no": "no",
    "from-crystal-ligand": "from crystal ligand",
    "novel": "novel",
}


def _find_pockets_display(mode: str) -> str:
    """Human-readable ``find_pockets`` value for notebook cards."""
    return _FIND_POCKETS_DISPLAY.get(mode, mode.replace("_", " "))


def _protein_prep_default_name(
    *,
    protein: Protein,
    pdb_id: str | None,
    model_missing_loops: bool,
    include_pocket: bool,
) -> str:
    """Build a short human-readable label for a prepare execution.

    Prefers ``pdb_id``, then ``protein.name``, then ``"protein"``.

    Args:
        protein: Input protein (``name`` used when ``pdb_id`` is absent).
        pdb_id: Optional 4-character PDB ID for the run.
        model_missing_loops: Whether loop modelling is enabled.
        include_pocket: Whether Pocket Finder is configured.

    Returns:
        Labels such as ``Preparing 1EBY``,
        ``Preparing and loop modelling 1EBY``,
        ``Preparing and finding pockets brd``, or
        ``Preparing, loop modelling, and finding pockets 1EBY``.
    """
    raw_label = pdb_id or protein.name or "protein"
    label = str(raw_label).strip() or "protein"
    extras: list[str] = []
    if model_missing_loops:
        extras.append("loop modelling")
    if include_pocket:
        extras.append("finding pockets")
    if not extras:
        return f"Preparing {label}"
    if len(extras) == 1:
        return f"Preparing and {extras[0]} {label}"
    return f"Preparing, {extras[0]}, and {extras[1]} {label}"


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


def _is_ligand_component_id(component_id: str) -> bool:
    """Return whether *component_id* refers to a ligand Component."""
    return str(component_id).startswith("ligand:")


def _validate_decision_for_component(component_id: str, decision: str) -> None:
    """Raise if *decision* is invalid for a Selection component id.

    Args:
        component_id: Selection / recommendation component id.
        decision: Draft or resolved decision string.

    Raises:
        ValueError: If the decision is not allowed for this component kind.
    """
    if decision == "review":
        return
    if _is_ligand_component_id(component_id):
        if decision not in {"keep", "extract"}:
            raise ValueError(
                f"selection.decisions[{component_id!r}] must be 'keep', "
                f"'extract', or 'review' for ligands, got {decision!r}."
            )
        return
    if decision not in {"keep", "skip"}:
        raise ValueError(
            f"selection.decisions[{component_id!r}] must be 'keep', 'skip', "
            f"or 'review', got {decision!r}."
        )


def _normalize_decision_for_component(component_id: str, decision: str) -> str:
    """Return a platform-valid decision, mapping ligand skip to extract.

    Args:
        component_id: Selection component id.
        decision: Requested decision (``keep``, ``skip``, ``extract``, or
            ``review``).

    Returns:
        Normalized decision stored on the Selection.

    Raises:
        ValueError: If the decision is invalid for this component.
    """
    resolved = str(decision)
    if resolved == "skip" and _is_ligand_component_id(component_id):
        resolved = "extract"
    _validate_decision_for_component(component_id, resolved)
    return resolved


def _copy_selection(selection: dict[str, Any]) -> dict[str, Any]:
    """Return a validated JSON-shape copy of a Selection.

    Args:
        selection: Selection object with ``source_sha256``, ``analyzer_version``,
            and ``decisions``.

    Returns:
        Copy with string keys and validated per-component decisions.

    Raises:
        ValueError: If required keys are missing, ``decisions`` is not an
            object, or a decision is invalid for its component id.
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
        component_key = str(component_id)
        decision = _normalize_decision_for_component(component_key, str(raw_decision))
        decisions[component_key] = decision
    return {
        "source_sha256": str(selection["source_sha256"]),
        "analyzer_version": str(selection["analyzer_version"]),
        "decisions": decisions,
    }


def _loop_modelling_from_recommendation(recommendation: dict[str, Any]) -> bool:
    """Whether prepare should model missing loops from analyzer Chain Break facts.

    Args:
        recommendation: Analyzer ``jobOutputs.recommendation`` payload.

    Returns:
        ``True`` when ``chain_breaks`` is non-empty or ``has_chain_breaks`` is
        true. When both facts are absent (legacy analyzer), defaults to ``True``.
    """
    chain_breaks = recommendation.get("chain_breaks")
    if isinstance(chain_breaks, list):
        return len(chain_breaks) > 0
    has_breaks = recommendation.get("has_chain_breaks")
    if isinstance(has_breaks, bool):
        return has_breaks
    return True


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
    extract_n = sum(1 for value in decisions.values() if value == "extract")
    return f"{keep_n} keep, {review_n} review, {skip_n} skip, {extract_n} extract"


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
    client: DeepOriginClient,
    fallback_pdb_id: str | None,
    fallback_name: str | None,
) -> Protein:
    """Build a :class:`Protein` from a prepared-protein output dict.

    Args:
        data: ``jobOutputs.protein`` or result-explorer ``data`` payload.
        client: Platform client used to resolve ``id``.
        fallback_pdb_id: PDB ID used when the payload omits ``pdb_id``.
        fallback_name: Input protein name used when the entity name is generic.

    Returns:
        Registered prepared protein resolved from ``id``.

    Raises:
        ValueError: If ``id`` is missing or empty.
    """
    raw_protein_id = data.get("id")
    if not raw_protein_id or not str(raw_protein_id).strip():
        raise ValueError(PROTEIN_PREP_NO_OUTPUT_PATHS_MSG)
    prepared = Protein.from_id(
        str(raw_protein_id).strip(),
        client=client,
        download=False,
    )
    pdb_id = data.get("pdb_id") or fallback_pdb_id
    if pdb_id and not prepared.pdb_id:
        prepared.pdb_id = str(pdb_id)
    base_name = fallback_name.strip() if isinstance(fallback_name, str) else ""
    if base_name and prepared.name in {str(raw_protein_id), "protein"}:
        prepared.name = f"{base_name} (prepared)"
    return prepared


def _crystal_pose_output_rows(rows: list[Any]) -> list[dict[str, Any]]:
    """Return prepare ``poses[]`` dict rows, excluding non-crystal origins."""

    filtered: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        origin = str(row.get("origin") or "").strip()
        if origin != _PROTEIN_PREP_CRYSTAL_POSE_ORIGIN:
            continue
        filtered.append(row)
    return filtered


def _crystal_poses_from_output_rows(
    rows: list[dict[str, Any]],
    *,
    client: DeepOriginClient,
) -> list[Pose]:
    """Build :class:`Pose` instances from prepare ``poses[]`` job-output rows."""

    pose_rows = _crystal_pose_output_rows(rows)
    if not pose_rows:
        return []
    return PoseSet.from_json(pose_rows, client=client).poses


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
        if rec not in _VALID_ANALYZER_RECOMMENDATIONS:
            raise ValueError(
                f"recommendation.components[{index}] recommendation must be "
                f"keep, skip, extract, or review, got {raw.get('recommendation')!r}."
            )
        decisions[str(component_id)] = _normalize_decision_for_component(
            str(component_id),
            rec,
        )
    return {
        "source_sha256": str(source_sha256),
        "analyzer_version": str(analyzer_version),
        "decisions": decisions,
    }


def _ensure_crystal_ligand_remote(
    ligand: Ligand,
    *,
    client: DeepOriginClient,
) -> None:
    """Materialize in-memory crystal ligands and sync before ``file_path`` submit."""
    if ligand.remote_path and str(ligand.remote_path).strip():
        return
    if ligand.local_path is None:
        ligand.to_file()
    ligand.sync(lazy=False, client=client)
    if ligand.remote_path and str(ligand.remote_path).strip():
        return
    ligand.upload(client=client)
    if ligand.id is not None:
        ligand.update(client=client, remote_path=ligand.remote_path)
    else:
        ligand.register(client=client)
    ligand.ensure_remote_path(client=client, label="Crystal ligand")


def _kind_from_component_id(component_id: str) -> str | None:
    """Return the Component kind encoded in a transport id, if valid.

    Args:
        component_id: Selection / recommendation component id.

    Returns:
        ``chain``, ``ligand``, ``cofactor``, or ``water`` when the id prefix
        is a known kind, otherwise ``None``.
    """
    prefix = component_id.split(":", 1)[0]
    if prefix in PROTEIN_PREP_COMPONENT_KINDS:
        return prefix
    return None


def _validate_component_matchers(
    *,
    kind: str | None,
    subtype: str | None,
    recommendation: str | None,
    decision: str | None,
) -> None:
    """Raise if a table / keep matcher value is not in its allowed set.

    Args:
        kind: Optional Component kind filter.
        subtype: Optional subtype filter (any string is allowed).
        recommendation: Optional frozen analyzer-tag filter.
        decision: Optional live Selection Decision filter.

    Raises:
        ValueError: If ``kind``, ``recommendation``, or ``decision`` is set
            to a value outside its allowed set.
    """
    del subtype
    if kind is not None and kind not in PROTEIN_PREP_COMPONENT_KINDS:
        allowed = ", ".join(sorted(PROTEIN_PREP_COMPONENT_KINDS))
        raise ValueError(f"kind must be one of {allowed}, got {kind!r}.")
    if (
        recommendation is not None
        and recommendation not in _VALID_ANALYZER_RECOMMENDATIONS
    ):
        raise ValueError(
            "recommendation must be 'keep', 'review', 'skip', or 'extract', "
            f"got {recommendation!r}."
        )
    if decision is not None and decision not in _VALID_DECISIONS:
        raise ValueError(
            "decision must be 'keep', 'review', 'skip', or 'extract', "
            f"got {decision!r}."
        )


def _empty_recommendation_dataframe() -> pd.DataFrame:
    """Return an empty Component table with the canonical column order."""
    return pd.DataFrame({column: [] for column in PROTEIN_PREP_RECOMMENDATION_COLUMNS})


def _rows_to_recommendation_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Build a Component DataFrame in canonical column order.

    Args:
        rows: Component row dicts with Recommendation view keys.

    Returns:
        DataFrame with :data:`PROTEIN_PREP_RECOMMENDATION_COLUMNS`.
    """
    if not rows:
        return _empty_recommendation_dataframe()
    return pd.DataFrame(rows)[list(PROTEIN_PREP_RECOMMENDATION_COLUMNS)]


def _recommendation_rows(
    payload: dict[str, Any],
    decisions: dict[str, str],
) -> list[dict[str, Any]]:
    """Build table rows from analyzer components and live Decisions.

    Args:
        payload: Analyzer recommendation dict with ``components``.
        decisions: Current Selection ``id → decision`` map.

    Returns:
        One row dict per component, in payload order.
    """
    rows: list[dict[str, Any]] = []
    for raw in payload.get("components") or []:
        if not isinstance(raw, dict):
            continue
        component_id = str(raw.get("id") or "")
        if not component_id:
            continue
        analyzer_tag = raw.get("recommendation")
        rows.append(
            {
                "id": component_id,
                "kind": raw.get("kind"),
                "subtype": raw.get("subtype"),
                "label": raw.get("label"),
                "recommendation": analyzer_tag,
                "decision": decisions.get(component_id, analyzer_tag),
                "reason": raw.get("reason"),
                "evidence": raw.get("evidence") or {},
            }
        )
    return rows


def _selection_rows(decisions: dict[str, str]) -> list[dict[str, Any]]:
    """Build table rows from a Selection when analyzer evidence is missing.

    Args:
        decisions: Current Selection ``id → decision`` map.

    Returns:
        One row dict per Selection id. ``subtype`` / analyzer fields are empty.
    """
    rows: list[dict[str, Any]] = []
    for component_id, live_decision in decisions.items():
        rows.append(
            {
                "id": str(component_id),
                "kind": _kind_from_component_id(str(component_id)),
                "subtype": None,
                "label": None,
                "recommendation": None,
                "decision": live_decision,
                "reason": None,
                "evidence": {},
            }
        )
    return rows


def _filter_recommendation_dataframe(
    df: pd.DataFrame,
    *,
    kind: str | None = None,
    subtype: str | None = None,
    recommendation: str | None = None,
    decision: str | None = None,
) -> pd.DataFrame:
    """Return rows matching all provided Component matchers (AND).

    Args:
        df: Component table.
        kind: Optional kind equality filter.
        subtype: Optional subtype equality filter.
        recommendation: Optional frozen analyzer-tag filter.
        decision: Optional live Decision filter.

    Returns:
        Filtered copy with a reset index. Empty when nothing matches.

    Raises:
        ValueError: If a matcher value is invalid.
    """
    _validate_component_matchers(
        kind=kind,
        subtype=subtype,
        recommendation=recommendation,
        decision=decision,
    )
    if df.empty:
        return df.copy()
    mask = pd.Series(True, index=df.index)
    if kind is not None:
        mask &= df["kind"] == kind
    if subtype is not None:
        mask &= df["subtype"] == subtype
    if recommendation is not None:
        mask &= df["recommendation"] == recommendation
    if decision is not None:
        mask &= df["decision"] == decision
    return df.loc[mask].reset_index(drop=True)


def _ids_from_positional(
    component_ids: str | Iterable[str] | pd.DataFrame,
    *,
    method: str,
) -> list[str]:
    """Normalize keep/skip positional ids from a string, iterable, or DataFrame.

    Args:
        component_ids: Single id, iterable of ids, or DataFrame with ``id``.
        method: ``keep`` or ``skip``, for error messages.

    Returns:
        Component ids as strings, preserving order.

    Raises:
        TypeError: If *component_ids* is a mapping.
        ValueError: If a DataFrame has no ``id`` column.
    """
    if isinstance(component_ids, pd.DataFrame):
        if "id" not in component_ids.columns:
            raise ValueError(PROTEIN_PREP_DATAFRAME_ID_COLUMN_MSG)
        return [str(value) for value in component_ids["id"].tolist()]
    if isinstance(component_ids, Mapping):
        raise TypeError(f"{method}() requires component IDs or keyword filters.")
    if isinstance(component_ids, str):
        return [component_ids]
    return [str(component_id) for component_id in component_ids]


class ProteinPrep(
    Execution,
    SyncExecutableMixin,
    AsyncExecutableMixin,
    NotebookWatchMixin,
):
    """Recommend settings and prepare a protein.

    All operations use ``deeporigin.protein-prep`` (v10). Blocking :meth:`run`
    supports served prepare including loop modelling. Novel pocket finding uses
    the platform workflow path — use :meth:`start` (with ``quote`` /
    ``approve_amount`` when pockets are billable). Structure reports are not
    produced by this tool; use :class:`~deeporigin.drug_discovery.structure_report.StructureReport`.

    Attributes:
        protein: Constructor-only input protein structure.
        pdb_id: Mutable 4-character PDB ID for loop-modelling templates.
        selection: Editable keep/review/skip/extract map. Reads return a copy.
        recommendation: Component table as a :class:`~pandas.DataFrame`, or
            ``None`` before recommend. Refreshes live ``decision`` values on
            each read.
        recommendation_payload: Deep copy of analyzer JSON, or ``None``.
        model_missing_loops: Whether prepare models missing loops.
        pocket: Optional Pocket Finder settings.
    """

    tool_key: str = _PROTEIN_PREP_TOOL_KEY

    def __init__(
        self,
        protein: Protein,
        *,
        pdb_id: str | None = None,
        selection: dict[str, Any] | None = None,
        model_missing_loops: bool | None = None,
        find_pockets: ProteinPrepFindPockets | None = None,
        pocket_count: int | None = None,
        pocket_min_size: int | float | None = None,
        crystal_ligand: Ligand | None = None,
        ligand_id: str | None = None,
        component_id: str | None = None,
        box_geometry: BoxGeometry | None = None,
        box_padding: float | None = None,
        pocket_radius: int | float | None = None,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_version"],
        client: DeepOriginClient | None = None,
        name: str | None = None,
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
                not require ``pdb_id`` on the direct path.
            find_pockets: Whether to find pockets during prepare (``"no"``,
                ``"from-crystal-ligand"``, or ``"novel"``).
            pocket_count: Max pockets when ``find_pockets="novel"`` (default 1).
            pocket_min_size: Minimum pocket volume when ``find_pockets="novel"``
                (default 30).
            crystal_ligand: External ligand for ``from-crystal-ligand``.
            ligand_id: In-structure ligand code for ``from-crystal-ligand``.
            component_id: Component id for ``from-crystal-ligand``.
            box_geometry: Crystal-ligand box geometry.
            box_padding: Padding for ``ligand-extents`` geometry.
            pocket_radius: Half-edge for ``fixed-radius`` geometry.
            tool_version: Platform ``deeporigin.protein-prep`` version pin
                (default from :data:`~deeporigin.platform.constants.TOOL_KEYS_AND_VERSIONS`).
            client: Optional API client. Uses the default if not provided.
            name: Optional execution label for prepare submissions. When
                omitted, :meth:`run` and :meth:`start` choose a label from the
                loops / pocket settings and ``pdb_id`` (or protein name).

        Raises:
            ValueError: If ``pdb_id``, ``selection``, or pocket settings are invalid.
        """
        super().__init__(client=client)
        self.tool_version = tool_version
        self._direct_tool_version = tool_version
        self.name = name
        self._protein = protein
        self._operation_kind: ProteinPrepAction | None = None
        self._pdb_id = _optional_pdb_id(protein=protein, pdb_id=pdb_id)
        self._selection = _copy_selection(selection) if selection is not None else None
        self._recommendation: dict[str, Any] | None = None
        if model_missing_loops is None:
            self._model_missing_loops = True
            self._model_missing_loops_user_configured = False
        else:
            self._model_missing_loops = bool(model_missing_loops)
            self._model_missing_loops_user_configured = True
        self._find_pockets: ProteinPrepFindPockets = "no"
        self._pocket_count = _DEFAULT_POCKET_COUNT
        self._pocket_min_size = float(_DEFAULT_POCKET_MIN_SIZE)
        self._crystal_ligand: Ligand | None = None
        self._ligand_id: str | None = None
        self._component_id: str | None = None
        self._box_geometry: BoxGeometry | None = box_geometry
        self._box_padding: float | None = box_padding
        self._pocket_radius: float | None = (
            float(pocket_radius) if pocket_radius is not None else None
        )
        self._crystal_ligand_remote_path: str | None = None
        self._find_pockets_user_configured = False
        if find_pockets is not None:
            if find_pockets == "no":
                self._find_pockets = "no"
                self._find_pockets_user_configured = True
            else:
                self.find_pockets = find_pockets
        if pocket_count is not None:
            self.pocket_count = pocket_count
        if pocket_min_size is not None:
            self.pocket_min_size = pocket_min_size
        if crystal_ligand is not None:
            self.crystal_ligand = crystal_ligand
        if ligand_id is not None:
            self.ligand_id = ligand_id
        if component_id is not None:
            self.component_id = component_id

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
    def recommendation(self) -> pd.DataFrame | None:
        """Component table, or ``None`` when analyzer evidence is missing."""
        if self._recommendation is None:
            return None
        return self._component_dataframe()

    @property
    def recommendation_payload(self) -> dict[str, Any] | None:
        """Deep copy of the analyzer recommendation payload."""
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
        self._model_missing_loops_user_configured = True

    def _resolved_find_pockets(self) -> ProteinPrepFindPockets:
        """Pocket mode for display and prepare payloads."""
        if self._find_pockets == "novel":
            return "novel"
        if self._find_pockets == "from-crystal-ligand":
            return "from-crystal-ligand"
        if self._find_pockets_user_configured and self._find_pockets == "no":
            return "no"
        if not self._find_pockets_user_configured and _selection_has_ligand_extract(
            self._selection
        ):
            return "from-crystal-ligand"
        return "no"

    @property
    def find_pockets(self) -> ProteinPrepFindPockets:
        """Whether prepare runs Pocket Finder (``no``, ``from-crystal-ligand``, ``novel``).

        Infers ``from-crystal-ligand`` when the Selection extracts a ligand and
        pocket mode has not been set explicitly.
        """
        return self._resolved_find_pockets()

    @find_pockets.setter
    def find_pockets(self, value: ProteinPrepFindPockets) -> None:
        """Set pocket-finding mode before submission."""
        self._require_unbound("find_pockets")
        resolved = str(value).strip()
        if resolved not in _VALID_FIND_POCKETS:
            raise ValueError(
                "find_pockets must be 'no', 'from-crystal-ligand', or 'novel', "
                f"got {value!r}."
            )
        self._find_pockets = resolved  # type: ignore[assignment]
        self._find_pockets_user_configured = True

    @property
    def pocket_count(self) -> int:
        """Max pockets when :attr:`find_pockets` is ``\"novel\"``."""
        return self._pocket_count

    @pocket_count.setter
    def pocket_count(self, value: int) -> None:
        """Set novel pocket count (requires :attr:`find_pockets` ``\"novel\"``)."""
        self._require_unbound("pocket_count")
        if self._find_pockets != "novel":
            raise ValueError("pocket_count is only used when find_pockets='novel'.")
        count = int(value)
        if count < 1:
            raise ValueError("pocket_count must be at least 1.")
        self._pocket_count = count

    @property
    def pocket_min_size(self) -> float:
        """Minimum pocket size when :attr:`find_pockets` is ``\"novel\"``."""
        return self._pocket_min_size

    @pocket_min_size.setter
    def pocket_min_size(self, value: int | float) -> None:
        """Set novel pocket minimum size (requires :attr:`find_pockets` ``\"novel\"``)."""
        self._require_unbound("pocket_min_size")
        if self._find_pockets != "novel":
            raise ValueError("pocket_min_size is only used when find_pockets='novel'.")
        min_size = float(value)
        if min_size < 1:
            raise ValueError("pocket_min_size must be at least 1.")
        self._pocket_min_size = min_size

    @property
    def crystal_ligand(self) -> Ligand | None:
        """External ligand file for ``find_pockets='from-crystal-ligand'``."""
        return self._crystal_ligand

    @crystal_ligand.setter
    def crystal_ligand(self, value: Ligand | None) -> None:
        """Set external crystal ligand (clears ``ligand_id`` / ``component_id``)."""
        self._require_unbound("crystal_ligand")
        self._crystal_ligand = value
        if value is not None:
            self._ligand_id = None
            self._component_id = None
            self._crystal_ligand_remote_path = None

    @property
    def ligand_id(self) -> str | None:
        """In-structure ligand code for ``find_pockets='from-crystal-ligand'``."""
        return self._ligand_id

    @ligand_id.setter
    def ligand_id(self, value: str | None) -> None:
        """Set in-structure ligand id (clears other crystal-ligand sources)."""
        self._require_unbound("ligand_id")
        self._ligand_id = None if value is None else str(value).strip() or None
        if self._ligand_id is not None:
            self._crystal_ligand = None
            self._component_id = None
            self._crystal_ligand_remote_path = None

    @property
    def component_id(self) -> str | None:
        """Component id for ``find_pockets='from-crystal-ligand'``."""
        return self._component_id

    @component_id.setter
    def component_id(self, value: str | None) -> None:
        """Set component id (clears other crystal-ligand sources)."""
        self._require_unbound("component_id")
        self._component_id = None if value is None else str(value).strip() or None
        if self._component_id is not None:
            self._crystal_ligand = None
            self._ligand_id = None
            self._crystal_ligand_remote_path = None

    @property
    def box_geometry(self) -> BoxGeometry | None:
        """Crystal-ligand box geometry when :attr:`find_pockets` is crystal mode."""
        return self._box_geometry

    @box_geometry.setter
    def box_geometry(self, value: BoxGeometry | None) -> None:
        """Set crystal-ligand box geometry before submission."""
        self._require_unbound("box_geometry")
        self._box_geometry = value

    @property
    def box_padding(self) -> float | None:
        """Padding for ``ligand-extents`` crystal-ligand boxes."""
        return self._box_padding

    @box_padding.setter
    def box_padding(self, value: float | None) -> None:
        """Set crystal-ligand box padding before submission."""
        self._require_unbound("box_padding")
        self._box_padding = None if value is None else float(value)

    @property
    def pocket_radius(self) -> float | None:
        """Half-edge for ``fixed-radius`` crystal-ligand boxes."""
        return self._pocket_radius

    @pocket_radius.setter
    def pocket_radius(self, value: float | None) -> None:
        """Set crystal-ligand fixed-radius half-edge before submission."""
        self._require_unbound("pocket_radius")
        self._pocket_radius = None if value is None else float(value)

    def _prep_pocket_input(self) -> _PrepPocketInput | None:
        """Build validated pocket input for explicit ``find_pockets`` modes."""
        if self._find_pockets == "novel":
            return _PrepPocketInput(
                mode="auto-find",
                pocket_count=self._pocket_count,
                pocket_min_size=self._pocket_min_size,
            )
        if self._find_pockets == "from-crystal-ligand":
            return _PrepPocketInput(
                mode="from-crystal-ligand",
                crystal_ligand=self._crystal_ligand,
                ligand_id=self._ligand_id,
                component_id=self._component_id,
                box_geometry=self._box_geometry,
                box_padding=self._box_padding,
                pocket_radius=self._pocket_radius,
                _crystal_ligand_remote_path=self._crystal_ligand_remote_path,
            )
        return None

    def _merge_find_pockets_into_inputs(
        self,
        inputs: dict[str, Any],
        *,
        allow_extract_inference: bool,
    ) -> None:
        """Set flat ``find_pockets`` tool fields on a prepare payload."""
        pocket = self._prep_pocket_input()
        if pocket is not None:
            inputs.update(pocket.to_tool_input())
            return
        if allow_extract_inference:
            inputs["find_pockets"] = self._resolved_find_pockets()
        else:
            inputs["find_pockets"] = self._find_pockets

    def _pockets_explicitly_requested(self) -> bool:
        """Return whether prepare will request pockets on this object."""
        return self.find_pockets in {"novel", "from-crystal-ligand"}

    def _apply_pocket_from_stored_inputs(self, pocket: dict[str, Any] | None) -> None:
        """Rehydrate pocket-related attributes from execution inputs."""
        self._find_pockets = "no"
        self._crystal_ligand = None
        self._ligand_id = None
        self._component_id = None
        self._box_geometry = None
        self._box_padding = None
        self._pocket_radius = None
        self._crystal_ligand_remote_path = None
        if pocket is None:
            return
        parsed = _PrepPocketInput.from_tool_input(pocket)
        if parsed is None:
            return
        if parsed.mode == "auto-find":
            self._find_pockets = "novel"
            self._pocket_count = int(parsed.pocket_count or _DEFAULT_POCKET_COUNT)
            self._pocket_min_size = float(
                parsed.pocket_min_size or _DEFAULT_POCKET_MIN_SIZE
            )
            return
        if parsed.mode == "define-by-selection":
            raise ValueError(_DEFINE_BY_SELECTION_COMPOSITE_MSG)
        self._find_pockets = "from-crystal-ligand"
        self._crystal_ligand = parsed.crystal_ligand
        self._ligand_id = parsed.ligand_id
        self._component_id = parsed.component_id
        self._box_geometry = parsed.box_geometry
        self._box_padding = parsed.box_padding
        self._pocket_radius = parsed.pocket_radius
        self._crystal_ligand_remote_path = parsed._crystal_ligand_remote_path

    def _ensure_prepare_name(self) -> None:
        """Set a descriptive prepare name when the caller did not provide one.

        Reflects the current loops / pocket configuration and prefers
        :attr:`pdb_id` over ``protein.name``.
        """
        if self.name is not None:
            return
        self.name = _protein_prep_default_name(
            protein=self._protein,
            pdb_id=self._pdb_id,
            model_missing_loops=self._model_missing_loops,
            include_pocket=self._find_pockets in {"novel", "from-crystal-ligand"},
        )

    def _apply_protein_prep_tool(self) -> None:
        """Pin ``tool_key`` / ``tool_version`` for the next execution create."""
        self.tool_key = _PROTEIN_PREP_TOOL_KEY
        self.tool_version = self._direct_tool_version

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
                "Use keep(), skip(), or extract()."
            )
        if not self._protein.id:
            raise ValueError(PROTEIN_PREP_REGISTERED_PROTEIN_REQUIRED_MSG)
        if self._model_missing_loops and not self._pdb_id:
            raise ValueError(PROTEIN_PREP_PDB_ID_REQUIRED_MSG)
        pocket = self._prep_pocket_input()
        if pocket is not None:
            pocket.validate()

    def _component_dataframe(self) -> pd.DataFrame:
        """Return the Component table used by keep/skip matchers.

        Uses analyzer evidence when :attr:`recommendation` is set, otherwise
        Selection ids with kind inferred from the id prefix.

        Returns:
            DataFrame with :data:`PROTEIN_PREP_RECOMMENDATION_COLUMNS`.
        """
        decisions: dict[str, str] = {}
        if self._selection is not None:
            decisions = dict(self._selection["decisions"])
        if self._recommendation is not None:
            return _rows_to_recommendation_dataframe(
                _recommendation_rows(self._recommendation, decisions)
            )
        return _rows_to_recommendation_dataframe(_selection_rows(decisions))

    def _ids_matching(
        self,
        *,
        kind: str | None,
        subtype: str | None,
        decision: str | None,
    ) -> list[str]:
        """Return Selection component ids matching AND keep/skip kwargs.

        Args:
            kind: Optional Component kind.
            subtype: Optional subtype. Requires analyzer evidence.
            decision: Optional live Selection Decision.

        Returns:
            Matching ids in table order. Empty when nothing matches.

        Raises:
            ValueError: If a matcher is invalid, or ``subtype`` is used
                without a recommendation.
        """
        if subtype is not None and self._recommendation is None:
            raise ValueError(PROTEIN_PREP_SUBTYPE_REQUIRES_RECOMMENDATION_MSG)
        filtered = _filter_recommendation_dataframe(
            self._component_dataframe(),
            kind=kind,
            subtype=subtype,
            decision=decision,
        )
        return [str(value) for value in filtered["id"].tolist()]

    def _apply_decisions(
        self,
        component_ids: str | Iterable[str] | pd.DataFrame | None,
        *,
        decision_value: str,
        kind: str | None,
        subtype: str | None,
        decision: str | None,
    ) -> None:
        """Resolve ids from positional args or matchers, then set Decisions.

        Args:
            component_ids: Optional ids, DataFrame, or ``None`` when using
                keyword matchers.
            decision_value: ``keep`` or ``skip``.
            kind: Optional kind matcher.
            subtype: Optional subtype matcher.
            decision: Optional live Decision matcher.

        Raises:
            AttributeError: If this object is bound to an execution.
            TypeError: If positional ids have the wrong type.
            ValueError: If Selection is missing, styles are mixed, matchers
                are invalid, or named ids are unknown.
        """
        self._require_unbound(decision_value)
        if self._selection is None:
            raise ValueError(
                f"{decision_value}() requires a selection. Call recommend() or "
                "assign selection first."
            )
        has_positional = component_ids is not None
        has_kwargs = any(value is not None for value in (kind, subtype, decision))
        if has_positional and has_kwargs:
            raise ValueError(PROTEIN_PREP_KEEP_SKIP_MIXED_MSG)
        if not has_positional and not has_kwargs:
            raise ValueError(
                PROTEIN_PREP_KEEP_SKIP_EMPTY_MSG.format(method=decision_value)
            )
        if has_kwargs:
            resolved = self._ids_matching(kind=kind, subtype=subtype, decision=decision)
        else:
            assert component_ids is not None
            resolved = _ids_from_positional(component_ids, method=decision_value)
        self._set_decisions(resolved, decision_value)

    def _set_decisions(self, component_ids: Iterable[str], decision: str) -> None:
        """Set one decision for named Selection components.

        Args:
            component_ids: Iterable of component IDs to update.
            decision: ``keep`` or ``skip``.

        Raises:
            TypeError: If *component_ids* is a bare string.
            ValueError: If IDs are unknown.
        """
        if isinstance(component_ids, str):
            raise TypeError(f"{decision}() requires an iterable of component IDs.")
        assert self._selection is not None
        known_ids = self._selection["decisions"]
        resolved_ids = [str(component_id) for component_id in component_ids]
        unknown_ids = sorted(set(resolved_ids) - set(known_ids))
        if unknown_ids:
            joined = ", ".join(unknown_ids)
            raise ValueError(f"Unknown Selection component IDs: {joined}.")
        for component_id in resolved_ids:
            known_ids[component_id] = _normalize_decision_for_component(
                component_id,
                decision,
            )

    def keep(
        self,
        component_ids: str | Iterable[str] | pd.DataFrame | None = None,
        *,
        kind: str | None = None,
        subtype: str | None = None,
        decision: str | None = None,
    ) -> Self:
        """Mark matching Selection components to keep.

        Pass ids (a string, iterable, or DataFrame ``id`` column) *or*
        keyword matchers, not both. ``kind="water"`` is equivalent to
        passing every water component id.

        Args:
            component_ids: Component ids to keep.
            kind: Keep every Component of this kind.
            subtype: Keep every Component of this subtype.
            decision: Keep every Component with this live Decision.

        Returns:
            This :class:`ProteinPrep` (for chaining).
        """
        self._apply_decisions(
            component_ids,
            decision_value="keep",
            kind=kind,
            subtype=subtype,
            decision=decision,
        )
        return self

    def skip(
        self,
        component_ids: str | Iterable[str] | pd.DataFrame | None = None,
        *,
        kind: str | None = None,
        subtype: str | None = None,
        decision: str | None = None,
    ) -> Self:
        """Mark matching Selection components to skip.

        Same calling styles as :meth:`keep`.

        Args:
            component_ids: Component ids to skip.
            kind: Skip every Component of this kind.
            subtype: Skip every Component of this subtype.
            decision: Skip every Component with this live Decision.

        Returns:
            This :class:`ProteinPrep` (for chaining).
        """
        self._apply_decisions(
            component_ids,
            decision_value="skip",
            kind=kind,
            subtype=subtype,
            decision=decision,
        )
        return self

    def extract(
        self,
        component_ids: str | Iterable[str] | pd.DataFrame | None = None,
        *,
        kind: str | None = None,
        subtype: str | None = None,
        decision: str | None = None,
    ) -> Self:
        """Mark matching ligand Selection components to extract.

        Same calling styles as :meth:`keep`. Non-ligand ids raise
        :class:`ValueError`.

        Args:
            component_ids: Component ids to extract.
            kind: Extract every ligand Component of this kind (typically
                ``ligand``).
            subtype: Extract every Component of this subtype.
            decision: Extract every Component with this live Decision.

        Returns:
            This :class:`ProteinPrep` (for chaining).
        """
        self._apply_decisions(
            component_ids,
            decision_value="extract",
            kind=kind,
            subtype=subtype,
            decision=decision,
        )
        return self

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
                    f"{len(self._recommendation.get('components') or [])} components"
                    if self._recommendation is not None
                    else PROTEIN_PREP_DISPLAY_NONE
                ),
            ),
            ("find_pockets", self.find_pockets),
            (
                "pocket_count",
                (
                    str(self._pocket_count)
                    if self.find_pockets == "novel"
                    else PROTEIN_PREP_DISPLAY_NONE
                ),
            ),
            (
                "pocket_min_size",
                (
                    str(self._pocket_min_size)
                    if self.find_pockets == "novel"
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

    def _sync_model_missing_loops_from_recommendation(
        self,
        recommendation: dict[str, Any],
    ) -> None:
        """Align loop modelling with analyzer Chain Break facts when unbound."""
        if self.id is not None:
            return
        if self._model_missing_loops_user_configured:
            return
        self._model_missing_loops = _loop_modelling_from_recommendation(recommendation)

    def _summary_repr_text(self) -> str:
        """Plain-text summary for ``__repr__``, ``__str__``, and fallback HTML."""
        lines = ["ProteinPrep("]
        indent = "  "
        for name, value in self._parameter_rows():
            if name == "progress":
                continue
            lines.append(f"{indent}{name}: {value}")
        lines.append(")")
        return "\n".join(lines)

    def _chain_break_summary(self) -> str | None:
        """Short Chain Break line for display, or ``None`` before recommend."""
        if self._recommendation is None:
            return None
        chain_breaks = self._recommendation.get("chain_breaks")
        if isinstance(chain_breaks, list):
            if not chain_breaks:
                return "no chain breaks detected"
            preview = ", ".join(str(label) for label in chain_breaks[:3])
            if len(chain_breaks) > 3:
                preview += f" (+{len(chain_breaks) - 3} more)"
            return f"{len(chain_breaks)} chain break(s): {preview}"
        has_breaks = self._recommendation.get("has_chain_breaks")
        if isinstance(has_breaks, bool):
            return "chain breaks detected" if has_breaks else "no chain breaks detected"
        return None

    def _render_view(self) -> str:
        """Render a LigandSet-style summary card for notebooks."""
        title_label = escape(
            _prepare_protein_card_title(self.protein),
            quote=False,
        )
        html_parts = [
            "<div style='width: 520px; padding: 15px; border: 1px solid #ddd; "
            "border-radius: 6px; background-color: #f9f9f9;'>",
            "<h3 style='margin-top: 0; color: #333;'>"
            f"Prepare Protein {title_label}</h3>",
        ]

        if self.pdb_id:
            html_parts.append(
                f"<p style='margin: 8px 0;'><strong>PDB ID:</strong> "
                f"{escape(self.pdb_id, quote=False)}</p>"
            )

        if self._recommendation is not None:
            components = self._recommendation.get("components") or []
            n_components = len(components) if isinstance(components, list) else 0
            html_parts.append(
                f"<p style='margin: 8px 0;'><strong>Recommendation:</strong> "
                f"{n_components} component{'s' if n_components != 1 else ''}</p>"
            )
            chain_summary = self._chain_break_summary()
            if chain_summary:
                html_parts.append(
                    f"<p style='margin: 8px 0;'><strong>Chain breaks:</strong> "
                    f"{escape(chain_summary, quote=False)}</p>"
                )
        else:
            html_parts.append(
                "<p style='margin: 8px 0; color: #666;'><em>"
                "No recommendation yet — call <code>.recommend()</code></em></p>"
            )

        selection_display = _format_selection_display(self.selection)
        if selection_display != PROTEIN_PREP_DISPLAY_NONE:
            html_parts.append(
                f"<p style='margin: 8px 0;'><strong>Selection:</strong> "
                f"{escape(selection_display, quote=False)}</p>"
            )

        loops_state = "on" if self.model_missing_loops else "off"
        pockets_state = escape(
            _find_pockets_display(self.find_pockets),
            quote=False,
        )
        html_parts.append(
            "<p style='margin: 8px 0;'>"
            f"<strong>Loop modelling:</strong> {loops_state} "
            f"&nbsp;&middot;&nbsp; <strong>Find pockets:</strong> {pockets_state}"
            "</p>"
        )

        if self.id:
            status = getattr(self, "status", None)
            status_bit = (
                f" &mdash; <strong>status:</strong> {escape(str(status), quote=False)}"
                if status
                else ""
            )
            html_parts.append(
                f"<p style='margin: 8px 0;'><strong>Execution:</strong> "
                f"<code>{escape(str(self.id), quote=False)}</code>{status_bit}</p>"
            )
        elif self.name:
            html_parts.append(
                f"<p style='margin: 8px 0;'><strong>Name:</strong> "
                f"{escape(self.name, quote=False)}</p>"
            )

        action_hints = self._notebook_action_hints()
        html_parts.append(
            "<div style='margin-top: 12px; padding-top: 12px; border-top: 1px solid #ddd;'>"
            "<p style='margin: 4px 0; font-size: 0.9em; color: #666;'>"
            f"<em>{'; '.join(action_hints)}</em>"
            "</p></div>"
        )
        html_parts.append("</div>")
        return "".join(html_parts)

    def _prepare_submit_action_hint(self) -> str | None:
        """Next-step prepare hint for notebooks, keyed on :attr:`find_pockets`."""
        if self.id is not None or self.selection is None:
            return None
        if self.find_pockets == "novel":
            return "Call <code>.start()</code> to prepare and find pockets"
        return "Call <code>.run()</code> to prepare"

    def _notebook_action_hints(self) -> list[str]:
        """Footer hints for the ProteinPrep notebook card."""
        hints: list[str] = []
        if self._recommendation is None:
            hints.append("Call <code>.recommend()</code> to inventory components")
        else:
            hints.append(
                "Use <code>.keep()</code>, <code>.skip()</code>, or "
                "<code>.extract()</code> to edit the selection"
            )
            hints.append("View <code>.recommendation</code> for the component table")
        submit_hint = self._prepare_submit_action_hint()
        if submit_hint is not None:
            hints.append(submit_hint)
        return hints

    def __repr__(self) -> str:
        """Return a plain-text summary of configuration and execution state."""
        return self._summary_repr_text()

    __str__ = __repr__

    def _repr_html_(self) -> str:
        """Return a summary card for Jupyter display.

        Omits ``progress``: platform progress reports are nested trees that
        overwhelm the card. Use ``prep.progress`` directly.

        Returns:
            HTML fragment with configuration summary and action hints.
        """
        return self._render_view()

    def _ensure_protein_remote(self) -> None:
        """Upload/sync the protein and optional crystal ligand."""
        self._protein.sync(lazy=True, client=self.client)
        self._protein.ensure_remote_path(client=self.client, label="Protein")
        pocket = self._prep_pocket_input()
        if pocket is not None:
            pocket.ensure_remote(client=self.client)

    def _make_protein_prep_payload(
        self,
        *,
        action: ProteinPrepAction,
        sync: bool,
        approve_amount: int | None = None,
    ) -> dict[str, Any]:
        """Build the POST body for direct ``deeporigin.protein-prep``.

        Args:
            action: Internal platform operation.
            sync: Whether create blocks until completion.
            approve_amount: Optional spend cap (usually omitted).

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
            inputs["model_missing_loops"] = bool(self._model_missing_loops)
            if self._pdb_id:
                inputs["pdb_id"] = self._pdb_id
            self._merge_find_pockets_into_inputs(
                inputs,
                allow_extract_inference=True,
            )
        payload: dict[str, Any] = {
            "inputs": inputs,
            "outputs": {},
            "metadata": {},
            "sync": sync,
        }
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount
        if self.name is not None and action == "prepare":
            payload["name"] = self.name
        return payload

    def recommend(self) -> pd.DataFrame:
        """Recommend settings into this object without binding an execution ID.

        Always uses direct ``deeporigin.protein-prep``. The platform operation
        is synchronous and persisted by the backend, but its execution ID is
        deliberately not copied onto this object. Repeated calls atomically
        replace :attr:`recommendation` and :attr:`selection` only after a
        complete recommendation is available.

        Returns:
            Component inventory table for this structure.

        Raises:
            AttributeError: If this object is already bound to prepare.
            DeepOriginException: If recommendation output is unavailable.
        """
        self._require_unbound("recommend")
        self._ensure_protein_remote()
        self._apply_protein_prep_tool()
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
        self._sync_model_missing_loops_from_recommendation(recommendation)
        table = self.recommendation
        assert table is not None
        return table

    def _start_impl(self, *, approve_amount: int | None = None, **kwargs: Any) -> None:
        """Submit preparation asynchronously and bind this object to it.

        Args:
            approve_amount: Spend cap (``0`` for quote-only on billable pocket
                runs).
            **kwargs: Unused; accepted for mixin compatibility.
        """
        del kwargs
        if self.id is not None:
            raise ValueError("Cannot start: this ProteinPrep is already bound.")
        self._validate_for_submit()
        self._ensure_prepare_name()
        self._ensure_protein_remote()
        self._apply_protein_prep_tool()
        data = self._make_protein_prep_payload(
            action="prepare",
            sync=False,
            approve_amount=approve_amount,
        )
        execution_dto = self._create_execution(data=data)
        if execution_dto.get("executionId") is None:
            raise ValueError("Execution response must contain 'executionId'") from None
        self._operation_kind = "prepare"
        self.update_from_dto(execution_dto)

    def _require_direct_blocking_prepare(self) -> None:
        """Raise unless this instance may ``run()``.

        Raises:
            ValueError: If novel pocket finding is enabled (workflow path).
        """
        if self.find_pockets == "novel":
            raise ValueError(PROTEIN_PREP_RUN_REQUIRES_NOVEL_START_MSG)

    def run(
        self,
        *,
        quote: bool = False,
        approve_amount: int | None = None,
    ) -> Protein | None:
        """Execute served prepare synchronously (blocking).

        Valid for loops on or off when :attr:`find_pockets` is not ``\"novel\"``.

        Args:
            quote: Shorthand for :data:`~deeporigin.utils.constants.QUOTE_APPROVE_AMOUNT`.
            approve_amount: Optional spend cap (usually omitted on this path).

        Returns:
            An in-memory prepared :class:`Protein`, or ``None`` when Quoted.

        Raises:
            ValueError: If already submitted or this is not the direct path.
            DeepOriginException: If no prepared PDB path could be loaded.
        """
        if self.id is not None or self.status is not None:
            raise ValueError("Cannot run: this ProteinPrep is already bound.")
        self._require_direct_blocking_prepare()
        self._validate_for_submit()
        self._ensure_prepare_name()
        self._ensure_protein_remote()
        self._apply_protein_prep_tool()
        resolved_amount = QUOTE_APPROVE_AMOUNT if quote else approve_amount
        dto = self._create_execution(
            data=self._make_protein_prep_payload(
                action="prepare",
                sync=True,
                approve_amount=resolved_amount,
            ),
        )
        self._operation_kind = "prepare"
        self.update_from_dto(dto)
        if self.status == "Quoted":
            return None
        return self.get_results(dto)

    def update_from_dto(self, dto: dict[str, Any]) -> None:
        """Apply tools execution fields from a protein-prep execution DTO.

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).

        Raises:
            ValueError: If the DTO tool key is not ``deeporigin.protein-prep``.
        """
        tool_info = dto["tool"]
        dto_tool_key = tool_info["key"]
        if dto_tool_key != _PROTEIN_PREP_TOOL_KEY:
            raise ValueError(
                "Cannot apply execution DTO: "
                f"tool key mismatch (dto={dto_tool_key!r}, "
                f"expected={_PROTEIN_PREP_TOOL_KEY!r})."
            )
        self.tool_key = dto_tool_key
        self._id = dto["executionId"]
        self._estimate = None
        self._cost = None
        self.tool_version = tool_info["version"]
        self.status = normalize_platform_status(dto.get("status"))
        self.progress = dto.get("progressReport")
        self.app = dto.get("app")
        self.approve_amount = dto.get("approveAmount")
        self.created_at = dto.get("createdAt")
        self.created_by = dto.get("createdBy")
        self.started_at = dto.get("startedAt")
        self.completed_at = dto.get("completedAt")
        self.session = dto.get("session")
        self._dto = dto
        self._name = dto.get("name")
        price = self._quotation_total(dto)
        if price is not None:
            self._estimate = price
            if is_success_status(self.status):
                self._cost = price

    @staticmethod
    def _parse_inputs_dict(inputs: dict[str, Any]) -> _ParsedInputs:
        """Parse stored userInputs into protein, action, and prepare fields.

        Accepts current flat ``find_pockets`` fields, legacy nested ``pocket``
        fields, and v1 keep/remove lists (treated as prepare with no selection).

        Args:
            inputs: Execution ``userInputs`` (or ``inputs``) dict.

        Returns:
            Parsed protein dict, action, optional ``pdb_id``, optional
            selection, ``model_missing_loops``, and optional pocket dict.

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
        model_missing_loops_explicit = raw_loops is not None
        model_missing_loops = True if raw_loops is None else bool(raw_loops)

        pocket = _pocket_input_from_inputs(inputs)

        return _ParsedInputs(
            protein=protein_input,
            action=action,
            pdb_id=pdb_id,
            selection=selection,
            model_missing_loops=model_missing_loops,
            model_missing_loops_explicit=model_missing_loops_explicit,
            pocket=pocket,
        )

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct a ``ProteinPrep`` from a tools execution DTO.

        Rehydrates protein-prep recommendation and preparation executions.

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
        instance._model_missing_loops_user_configured = (
            parsed.model_missing_loops_explicit
        )
        instance._model_missing_loops = parsed.model_missing_loops
        if (
            instance._recommendation is not None
            and parsed.action == "recommend"
            and not parsed.model_missing_loops_explicit
        ):
            instance._model_missing_loops = _loop_modelling_from_recommendation(
                instance._recommendation
            )
        instance._apply_pocket_from_stored_inputs(parsed.pocket)
        if parsed.action == "prepare":
            instance._find_pockets_user_configured = True
        elif not hasattr(instance, "_find_pockets_user_configured"):
            instance._find_pockets_user_configured = False
        instance._direct_tool_version = TOOL_KEYS_AND_VERSIONS["protein_prep"][
            "tool_version"
        ]
        return instance

    @classmethod
    def from_id(cls, id: str, *, client: DeepOriginClient | None = None) -> Self:
        """Construct from a protein-prep execution id.

        Args:
            id: Platform execution ID.
            client: Optional API client.

        Returns:
            Rehydrated :class:`ProteinPrep`.
        """
        if client is None:
            from deeporigin.platform.client import DeepOriginClient as _Client

            client = _Client()
        dto = client.executions.get(id)  # ty:ignore[unresolved-attribute]
        return cls.from_dto(dto, client=client)

    @classmethod
    def list(
        cls,
        *,
        client: DeepOriginClient | None = None,
        status: list[str] | None = None,
    ) -> list[Self]:
        """List protein-prep executions for this session type.

        Args:
            client: Optional API client.
            status: Optional status filter on hydrated instances.

        Returns:
            Instances for ``deeporigin.protein-prep``, newest ``createdAt`` first.
        """
        if client is None:
            from deeporigin.platform.client import DeepOriginClient as _Client

            client = _Client()
        page = client.executions.list(  # ty:ignore[unresolved-attribute]
            fetch_all_pages=True,
            tool_key=_PROTEIN_PREP_TOOL_KEY,
        ).get("data", [])
        all_dtos = [
            dto
            for dto in page
            if isinstance(dto, dict)
            and dto.get("tool", {}).get("key") == _PROTEIN_PREP_TOOL_KEY
        ]
        all_dtos.sort(key=_dto_created_at, reverse=True)
        instances = [cls.from_dto(dto, client=client) for dto in all_dtos]
        if status is not None:
            instances = [item for item in instances if item.status in status]
        return instances

    @classmethod
    def from_last_run(cls, *, client: DeepOriginClient | None = None) -> Self:
        """Return the newest protein-prep execution.

        Args:
            client: Optional API client.

        Returns:
            Rehydrated :class:`ProteinPrep` for the newest matching execution.

        Raises:
            ValueError: If no protein-prep executions exist.
        """
        if client is None:
            from deeporigin.platform.client import DeepOriginClient as _Client

            client = _Client()
        response = client.executions.list(  # ty:ignore[unresolved-attribute]
            tool_key=_PROTEIN_PREP_TOOL_KEY,
            order=EXECUTION_LIST_ORDER_CREATED_DESC,
            page=0,
            page_size=1,
        )
        dtos = response.get("data") or []
        if not dtos or not isinstance(dtos[0], dict):
            raise ValueError(
                "No executions found for ProteinPrep "
                f"(tool_key={_PROTEIN_PREP_TOOL_KEY!r})."
            )
        return cls.from_dto(dtos[0], client=client)

    def _protein_from_outputs(self, data: dict[str, Any]) -> Protein:
        """Build the result Protein from an output dict.

        Args:
            data: Prepared-protein payload (``jobOutputs.protein`` or explorer
                ``data``).

        Returns:
            Prepared :class:`Protein`, usually registered via ``id``.
        """
        return _protein_from_prepared_data(
            data,
            client=self.client,
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

    def _result_rows(
        self,
        result_type: str,
        *,
        filter_by_tool_key: bool = True,
    ) -> list[dict[str, Any]]:
        """Return result-explorer data payloads for one child result type.

        Args:
            result_type: Indexed result type string.
            filter_by_tool_key: When False, match only ``compute_job_id``.

        Returns:
            Data dicts for this execution id, or an empty list on failure.
        """
        exec_id = self._ensure_id()
        filter_dict: dict[str, Any] | None = None
        if filter_by_tool_key:
            filter_dict = {"tool_key": {"eq": self.tool_key}}
        try:
            response = self.client.results.get(
                filter_dict=filter_dict,
                result_type=result_type,
                compute_job_id=exec_id,
            )
        except Exception:
            return []
        rows: list[dict[str, Any]] = []
        for record in response.get("data") or []:
            if not isinstance(record, dict) or record.get("compute_job_id") != exec_id:
                continue
            data = record.get("data")
            if isinstance(data, dict):
                rows.append(data)
        return rows

    def _execution_outputs(
        self,
        dto: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return jobOutputs for this execution, fetching when needed.

        Args:
            dto: Optional execution payload already in hand.

        Returns:
            ``jobOutputs`` dict, or ``{}`` when unavailable.
        """
        exec_id = self._ensure_id()
        if dto is None:
            try:
                dto = self.client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
            except Exception:
                dto = {}
        return _execution_outputs_dict(dto if isinstance(dto, dict) else {})

    @beartype
    def get_results(self, dto: dict[str, Any] | None = None) -> Protein:
        """Load the prepared protein as an in-memory :class:`Protein`.

        Works for either routed tool key. Tries result-explorer rows
        (``result_type=preparedprotein``), then ``jobOutputs.protein``.

        Args:
            dto: Optional execution payload. Passing it avoids an extra GET
                when the result-explorer path fails but ``jobOutputs`` is
                already in hand.

        Returns:
            An in-memory :class:`Protein` for the prepared structure.

        Raises:
            ValueError: If :attr:`id` is unset.
            DeepOriginException: If this was a recommend run, or no prepared
                protein could be loaded.
        """
        exec_id = self._ensure_id()
        if self._operation_kind == "recommend":
            raise DeepOriginException(
                title="Could not load prepared protein",
                message=PROTEIN_PREP_RECOMMEND_NOT_PREPARE_MSG,
            )

        try:
            response = self.client.results.get(
                filter_dict={"tool_key": {"eq": self.tool_key}},
                result_type=_RESULT_TYPE_PREPARED_PROTEIN,
                compute_job_id=exec_id,
                limit=1,
            )
            records = response.get("data") or []
            if records:
                data = records[0].get("data") or {}
                if isinstance(data, dict) and data.get("id"):
                    return self._protein_from_outputs(data)
        except Exception:
            pass

        try:
            outputs = self._execution_outputs(dto)
            protein_out = outputs.get("protein")
            if isinstance(protein_out, dict):
                return self._protein_from_outputs(protein_out)
        except ValueError:
            pass

        raise DeepOriginException(
            title="Could not load prepared protein",
            message=PROTEIN_PREP_NO_OUTPUT_PATHS_MSG,
        )

    def get_crystal_poses(
        self,
        dto: dict[str, Any] | None = None,
    ) -> PoseSet | None:
        """Return crystal poses extracted during prepare when ``extract`` was selected.

        Tries result-explorer rows (``result_type=pose``), then
        ``jobOutputs.poses``. Rows use the Protein Prep Pose shape
        (``origin: cocrystal``, prepared ``protein_id``, ``ligand_id``,
        ``file_path``, ``component_id``). Coordinates are not downloaded;
        call :meth:`~deeporigin.drug_discovery.structures.pose.Pose.download`
        on individual poses when needed.

        Args:
            dto: Optional execution payload used as a job-output fallback.

        Returns:
            A :class:`~deeporigin.drug_discovery.structures.pose.PoseSet` of
            crystal poses, an empty set when prepare completed with none, or
            ``None`` when outputs are not published yet.

        Raises:
            ValueError: If :attr:`id` is unset.
            DeepOriginException: If this was a recommend-only run.
        """
        self._ensure_id()
        if self._operation_kind == "recommend":
            raise DeepOriginException(
                title="Could not load crystal poses",
                message=PROTEIN_PREP_RECOMMEND_NOT_PREPARE_MSG,
            )

        indexed = self._result_rows(
            _RESULT_TYPE_POSE,
            filter_by_tool_key=False,
        )
        outputs = self._execution_outputs(dto)
        raw: Any = indexed if indexed else outputs.get("poses")
        if raw is None:
            return None
        if not isinstance(raw, list):
            return None

        poses = _crystal_poses_from_output_rows(
            raw,
            client=self.client,
        )
        return PoseSet(poses=poses)

    def get_pockets(
        self,
        dto: dict[str, Any] | None = None,
    ) -> list[Pocket] | None:
        """Return Pocket Finder results when this run requested pockets.

        Args:
            dto: Optional execution payload used as a job-output fallback.

        Returns:
            Pocket list (possibly empty for a valid zero-pocket result), or
            ``None`` when requested but not yet published.

        Raises:
            ValueError: If :attr:`id` is unset, or this run did not request pockets.
        """
        self._ensure_id()
        requested = self._pockets_explicitly_requested()
        indexed = self._result_rows(_RESULT_TYPE_POCKET)
        outputs = self._execution_outputs(dto)
        raw: Any = indexed if indexed else outputs.get("pockets")
        if not isinstance(raw, list):
            if not requested:
                raise ValueError(PROTEIN_PREP_POCKETS_EXCLUDED_MSG)
            return None
        try:
            pockets = Pocket.from_json(raw, client=self.client)
        except Exception:
            return None
        prepared: Protein | None = None
        try:
            prepared = self.get_results(dto)
        except Exception:
            prepared = None
        for pocket in pockets:
            pocket.protein = prepared or self._protein
        return pockets
