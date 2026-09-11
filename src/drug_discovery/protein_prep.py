"""Recommend settings and prepare a protein with one mutable configuration.

``ProteinPrep`` is the sole public preparation session. It always recommends
via direct ``deeporigin.protein-prep``. Preparation routes by configuration:

- loops off and no ``pocket`` → direct ``deeporigin.protein-prep`` (``run`` /
  ``start``);
- loops on or any ``pocket`` → workflow ``deeporigin.target-preparation``
  (``start`` only; billable when pockets are requested).

Optional nested :class:`PocketFinderConfig` selects Pocket Finder on the
composite route. :meth:`get_results` always returns the prepared
:class:`~deeporigin.drug_discovery.structures.protein.Protein`; use
:meth:`get_report` and :meth:`get_pockets` for composite artifacts.

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
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, Protocol, Self

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
    PROTEIN_PREP_KEEP_SKIP_VIEW_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_NO_OUTPUT_PATHS_MSG,
    PROTEIN_PREP_NO_RECOMMENDATION_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_PDB_ID_PATTERN,
    PROTEIN_PREP_PDB_ID_REQUIRED_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_POCKETS_EXCLUDED_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_RECOMMEND_NOT_PREPARE_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_RECOMMENDATION_COLUMNS,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_REPORT_EXCLUDED_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_RUN_REQUIRES_LOOPS_OFF_MSG,  # ty:ignore[unresolved-import]
    PROTEIN_PREP_SUBTYPE_REQUIRES_RECOMMENDATION_MSG,  # ty:ignore[unresolved-import]
)

if TYPE_CHECKING:
    from deeporigin.drug_discovery.structure_report import StructureReportResult


_PDB_ID_RE = re.compile(PROTEIN_PREP_PDB_ID_PATTERN)
_RESULT_TYPE_PREPARED_PROTEIN = "preparedprotein"
_RESULT_TYPE_STRUCTURE_REPORT = "structurereport"
_RESULT_TYPE_POCKET = "pocket"
_VALID_ACTIONS = frozenset({"recommend", "prepare"})
_VALID_DECISIONS = frozenset({"keep", "review", "skip"})
_RESOLVED_DECISIONS = frozenset({"keep", "skip"})
_PROTEIN_PREP_TOOL_KEY = TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_key"]
_TARGET_PREP_TOOL_KEY = TOOL_KEYS_AND_VERSIONS["target_prep"]["tool_key"]
_ALLOWED_TOOL_KEYS = frozenset({_PROTEIN_PREP_TOOL_KEY, _TARGET_PREP_TOOL_KEY})
_DEFAULT_POCKET_COUNT = 1
_DEFAULT_POCKET_MIN_SIZE = 30
_DEFAULT_POCKET_RADIUS = 10.0
_VALID_POCKET_MODES = frozenset(
    {"auto-find", "define-by-selection", "from-crystal-ligand"}
)
_VALID_BOX_GEOMETRIES = frozenset({"ligand-extents", "fixed-radius"})

ProteinPrepAction = Literal["recommend", "prepare"]
PocketFinderMode = Literal["auto-find", "define-by-selection", "from-crystal-ligand"]
BoxGeometry = Literal["ligand-extents", "fixed-radius"]


class _RecommendationOwner(Protocol):
    """Structural state required by :class:`RecommendationView`."""

    _recommendation: dict[str, Any] | None
    _selection: dict[str, Any] | None


class _ParsedInputs(NamedTuple):
    """Fields reconstructed from a Protein Prep execution ``userInputs`` dict."""

    protein: dict[str, Any]
    action: ProteinPrepAction
    pdb_id: str | None
    selection: dict[str, Any] | None
    model_missing_loops: bool
    pocket: dict[str, Any] | None


@dataclass
class PocketFinderConfig:
    """Nested Pocket Finder settings for composite :class:`ProteinPrep` runs.

    When assigned to :attr:`ProteinPrep.pocket`, preparation routes to
    ``deeporigin.target-preparation`` and runs Pocket Finder after the
    prepared protein is available.

    Attributes:
        mode: Pocket Finder mode.
        pocket_count: Max pockets for ``auto-find`` (default 1).
        pocket_min_size: Minimum pocket size for ``auto-find`` (default 30).
        selections: Component selectors for ``define-by-selection``.
        pocket_radius: Half-edge of a fixed-radius pocket box.
        align_to_pocket: PCA-align define-by-selection boxes.
        crystal_ligand: External ligand file for ``from-crystal-ligand``.
        ligand_id: In-structure ligand code for ``from-crystal-ligand``.
        component_id: Protein Prep Component id resolved after extraction.
        box_geometry: Crystal-ligand box geometry.
        box_padding: Padding for ``ligand-extents`` geometry.
    """

    mode: PocketFinderMode = "auto-find"
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
        self.crystal_ligand.sync(lazy=True, client=client)
        self.crystal_ligand.ensure_remote_path(
            client=client,
            label="Crystal ligand",
        )

    def to_tool_input(self) -> dict[str, Any]:
        """Return the nested ``pocket`` object for Target Preparation inputs.

        Returns:
            Wire-shape pocket dict for ``userInputs.pocket``.

        Raises:
            ValueError: If settings are invalid or a crystal ligand path is
                missing.
        """
        self.validate()
        if self.mode == "auto-find":
            return {
                "mode": self.mode,
                "pocket_count": int(self.pocket_count or _DEFAULT_POCKET_COUNT),
                "pocket_min_size": (
                    self.pocket_min_size
                    if self.pocket_min_size is not None
                    else _DEFAULT_POCKET_MIN_SIZE
                ),
            }
        if self.mode == "define-by-selection":
            return {
                "mode": self.mode,
                "selections": list(self.selections or []),
                "pocket_radius": float(
                    self.pocket_radius
                    if self.pocket_radius is not None
                    else _DEFAULT_POCKET_RADIUS
                ),
                "align_to_pocket": bool(self.align_to_pocket),
            }
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
        pocket: dict[str, Any] = {"mode": self.mode, "crystal_ligand": crystal}
        if self.pocket_radius is not None:
            pocket["pocket_radius"] = float(self.pocket_radius)
        if self.box_geometry is not None:
            pocket["box_geometry"] = self.box_geometry
        if self.box_padding is not None:
            pocket["box_padding"] = float(self.box_padding)
        return pocket

    @classmethod
    def from_tool_input(cls, data: dict[str, Any]) -> PocketFinderConfig:
        """Rebuild config from a stored nested ``pocket`` input dict.

        Args:
            data: ``userInputs.pocket`` object from an execution DTO.

        Returns:
            Rehydrated config (``crystal_ligand`` Ligand is not restored).

        Raises:
            ValueError: If ``data`` is not a valid pocket object.
        """
        if not isinstance(data, dict):
            raise ValueError("pocket input must be an object.")
        mode = data.get("mode") or "auto-find"
        if mode == "auto-find":
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
        return cls(
            mode="from-crystal-ligand",
            ligand_id=crystal.get("ligand_id"),
            component_id=crystal.get("component_id"),
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
    client: DeepOriginClient,
    fallback_pdb_id: str | None,
    fallback_name: str | None,
) -> Protein:
    """Build a :class:`Protein` from a prepared-protein output dict.

    Args:
        data: ``jobOutputs.protein`` or result-explorer ``data`` payload.
        client: Platform client used to resolve ``protein_id``.
        fallback_pdb_id: PDB ID used when the payload omits ``pdb_id``.
        fallback_name: Input protein name used when the entity name is generic.

    Returns:
        Registered prepared protein resolved from ``protein_id``.

    Raises:
        ValueError: If ``protein_id`` is missing or empty.
    """
    raw_protein_id = data.get("protein_id")
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
    if recommendation is not None and recommendation not in _VALID_DECISIONS:
        raise ValueError(
            "recommendation must be 'keep', 'review', or 'skip', "
            f"got {recommendation!r}."
        )
    if decision is not None and decision not in _VALID_DECISIONS:
        raise ValueError(
            f"decision must be 'keep', 'review', or 'skip', got {decision!r}."
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
        TypeError: If *component_ids* is a Recommendation view or a mapping.
        ValueError: If a DataFrame has no ``id`` column.
    """
    if isinstance(component_ids, RecommendationView):
        raise TypeError(PROTEIN_PREP_KEEP_SKIP_VIEW_MSG.format(method=method))
    if isinstance(component_ids, pd.DataFrame):
        if "id" not in component_ids.columns:
            raise ValueError(PROTEIN_PREP_DATAFRAME_ID_COLUMN_MSG)
        return [str(value) for value in component_ids["id"].tolist()]
    if isinstance(component_ids, Mapping):
        raise TypeError(f"{method}() requires component IDs or keyword filters.")
    if isinstance(component_ids, str):
        return [component_ids]
    return [str(component_id) for component_id in component_ids]


class RecommendationView:
    """Callable notebook table of Protein Prep Components.

    Uncalled, Jupyter displays the full inventory. Calling AND-filters rows
    and returns a :class:`~pandas.DataFrame`. Live Selection Decisions are
    read from the parent preparation session on each access.

    Attributes:
        raw: Deep copy of the analyzer recommendation payload.
    """

    def __init__(self, prep: _RecommendationOwner) -> None:
        """Bind this view to a preparation session with analyzer evidence.

        Args:
            prep: Parent ProteinPrep session.
        """
        self._prep = prep

    @property
    def raw(self) -> dict[str, Any]:
        """Deep copy of the analyzer recommendation payload."""
        payload = self._prep._recommendation
        if payload is None:
            return {}
        return deepcopy(payload)

    def _dataframe(self) -> pd.DataFrame:
        """Return the unfiltered Component table with live Decisions."""
        payload = self._prep._recommendation
        if not isinstance(payload, dict):
            return _empty_recommendation_dataframe()
        decisions: dict[str, str] = {}
        if self._prep._selection is not None:
            decisions = dict(self._prep._selection["decisions"])
        return _rows_to_recommendation_dataframe(
            _recommendation_rows(payload, decisions)
        )

    def __call__(
        self,
        *,
        kind: str | None = None,
        subtype: str | None = None,
        recommendation: str | None = None,
        decision: str | None = None,
    ) -> pd.DataFrame:
        """Return a DataFrame of Components matching all provided filters.

        Args:
            kind: Component kind (``chain``, ``ligand``, ``cofactor``,
                ``water``).
            subtype: Analyzer subtype string.
            recommendation: Frozen analyzer keep/review/skip tag.
            decision: Live Selection Decision.

        Returns:
            Filtered Component table. Unfiltered when no kwargs are set.
        """
        return _filter_recommendation_dataframe(
            self._dataframe(),
            kind=kind,
            subtype=subtype,
            recommendation=recommendation,
            decision=decision,
        )

    def __repr__(self) -> str:
        """Return the Component table as text."""
        return self._dataframe().to_string()

    def _repr_html_(self) -> str:
        """Return the Component table as HTML for Jupyter."""
        return self._dataframe()._repr_html_()


class ProteinPrep(
    Execution,
    SyncExecutableMixin,
    AsyncExecutableMixin,
    NotebookWatchMixin,
):
    """Recommend settings and prepare a protein.

    :meth:`recommend` always uses direct ``deeporigin.protein-prep``.
    Preparation routes to the same tool when loops are off and ``pocket`` is
    unset; otherwise it uses workflow ``deeporigin.target-preparation``.
    Blocking :meth:`run` is only for the direct loops-off path. Composite
    callers use :meth:`start` (with ``quote`` / ``approve_amount`` when
    pockets are billable).

    Attributes:
        protein: Constructor-only input protein structure.
        pdb_id: Mutable 4-character PDB ID for loop-modelling templates.
        selection: Editable keep/review/skip map. Reads return a copy.
        recommendation: Callable Component table, or ``None`` before
            recommend. Analyzer payload is :attr:`RecommendationView.raw`.
        model_missing_loops: Whether prepare models missing loops.
        pocket: Optional nested Pocket Finder settings for the composite route.
    """

    tool_key: str = _PROTEIN_PREP_TOOL_KEY

    @beartype
    def __init__(
        self,
        protein: Protein,
        *,
        pdb_id: str | None = None,
        selection: dict[str, Any] | None = None,
        model_missing_loops: bool = True,
        pocket: PocketFinderConfig | None = None,
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
            pocket: Optional Pocket Finder config. When set, preparation uses
                Target Preparation and finds pockets on the prepared protein.
            tool_version: Platform tool version pin for the direct protein-prep
                route. Composite runs use the pinned Target Preparation major.
            client: Optional API client. Uses the default if not provided.
            name: Optional execution label for prepare submissions. When
                omitted, :meth:`run` and :meth:`start` choose a label from the
                loops / pocket settings and ``pdb_id`` (or protein name).

        Raises:
            ValueError: If ``pdb_id``, ``selection``, or ``pocket`` is invalid.
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
        self._model_missing_loops = model_missing_loops
        self._pocket = pocket

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
    def recommendation(self) -> RecommendationView | None:
        """Callable Component table, or ``None`` when analyzer evidence is missing."""
        if self._recommendation is None:
            return None
        return RecommendationView(self)

    @property
    def model_missing_loops(self) -> bool:
        """Whether prepare will run loop modelling (unused for recommend)."""
        return self._model_missing_loops

    @model_missing_loops.setter
    def model_missing_loops(self, value: bool) -> None:
        """Set the loop-modelling flag before this execution is submitted."""
        self._require_unbound("model_missing_loops")
        self._model_missing_loops = bool(value)

    @property
    def pocket(self) -> PocketFinderConfig | None:
        """Optional Pocket Finder settings for the composite preparation route."""
        return self._pocket

    @pocket.setter
    def pocket(self, value: PocketFinderConfig | None) -> None:
        """Set or clear nested Pocket Finder settings before submission."""
        self._require_unbound("pocket")
        if value is not None:
            value.validate()
        self._pocket = value

    def _uses_composite_route(self) -> bool:
        """Return whether prepare must use Target Preparation."""
        return bool(self._model_missing_loops) or self._pocket is not None

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
            include_pocket=self._pocket is not None,
        )

    def _apply_runtime_route(self, *, composite: bool) -> None:
        """Set instance ``tool_key`` / ``tool_version`` for the next create.

        Args:
            composite: When ``True``, route to Target Preparation major 2.
        """
        if composite:
            self.tool_key = _TARGET_PREP_TOOL_KEY
            self.tool_version = TOOL_KEYS_AND_VERSIONS["target_prep"]["tool_version"]
        else:
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
                "Use keep() or skip()."
            )
        if self._model_missing_loops and not self._pdb_id:
            raise ValueError(PROTEIN_PREP_PDB_ID_REQUIRED_MSG)
        if self._pocket is not None:
            self._pocket.validate()

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
            known_ids[component_id] = decision

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

    def _parameter_rows(self) -> list[tuple[str, str]]:
        """Return ``(name, value)`` rows for text and HTML display.

        Includes constructor parameters and, when set, execution ``name``,
        ``id``, and ``status``.
        """
        pocket_display = PROTEIN_PREP_DISPLAY_NONE
        if self._pocket is not None:
            pocket_display = f"mode={self._pocket.mode}"
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
            ("pocket", pocket_display),
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

        Omits ``progress``: platform progress reports are nested trees that
        overwhelm a Parameter/Value table. Use ``prep.progress`` directly.

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
            if name == "progress":
                continue
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
        """Upload/sync the protein and optional crystal ligand."""
        self._protein.sync(lazy=True, client=self.client)
        self._protein.ensure_remote_path(client=self.client, label="Protein")
        if self._pocket is not None:
            self._pocket.ensure_remote(client=self.client)

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
        if self.name is not None and action == "prepare":
            payload["name"] = self.name
        return payload

    def _make_target_prep_payload(
        self,
        *,
        approve_amount: int | None,
    ) -> dict[str, Any]:
        """Build the POST body for action-less Target Preparation 2.0.

        Args:
            approve_amount: Optional spend cap (``0`` for quote-only).

        Returns:
            Payload for ``client.executions.create``.
        """
        self._validate_for_submit()
        assert self._selection is not None
        inputs: dict[str, Any] = {
            "protein": _protein_tool_input(self._protein),
            "selection": {
                "source_sha256": self._selection["source_sha256"],
                "analyzer_version": self._selection["analyzer_version"],
                "decisions": dict(self._selection["decisions"]),
            },
            "model_missing_loops": self._model_missing_loops,
        }
        if self._pdb_id:
            inputs["pdb_id"] = self._pdb_id
        if self._pocket is not None:
            inputs["pocket"] = self._pocket.to_tool_input()
        payload: dict[str, Any] = {
            "inputs": inputs,
            "outputs": {},
            "metadata": {},
        }
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount
        if self.name is not None:
            payload["name"] = self.name
        return payload

    def recommend(self) -> RecommendationView:
        """Recommend settings into this object without binding an execution ID.

        Always uses direct ``deeporigin.protein-prep``. The platform operation
        is synchronous and persisted by the backend, but its execution ID is
        deliberately not copied onto this object. Repeated calls atomically
        replace :attr:`recommendation` and :attr:`selection` only after a
        complete recommendation is available.

        Returns:
            The :class:`RecommendationView` table for this inventory.

        Raises:
            AttributeError: If this object is already bound to prepare.
            DeepOriginException: If recommendation output is unavailable.
        """
        self._require_unbound("recommend")
        self._ensure_protein_remote()
        self._apply_runtime_route(composite=False)
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
        view = self.recommendation
        assert view is not None
        return view

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
        composite = self._uses_composite_route()
        self._apply_runtime_route(composite=composite)
        if composite:
            data = self._make_target_prep_payload(approve_amount=approve_amount)
        else:
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
            ValueError: If loop modelling is enabled or ``pocket`` is set.
        """
        if self._model_missing_loops or self._pocket is not None:
            raise ValueError(PROTEIN_PREP_RUN_REQUIRES_LOOPS_OFF_MSG)

    def run(
        self,
        *,
        quote: bool = False,
        approve_amount: int | None = None,
    ) -> Protein | None:
        """Execute loops-off, no-pocket prepare synchronously (blocking).

        Only valid when :attr:`model_missing_loops` is ``False`` and
        :attr:`pocket` is unset.

        Args:
            quote: Shorthand for ``approve_amount=0``.
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
        self._apply_runtime_route(composite=False)
        resolved_amount = 0 if quote else approve_amount
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
        """Apply tools execution fields, accepting either routed tool key.

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).

        Raises:
            ValueError: If the DTO tool key is not protein-prep or
                target-preparation.
        """
        tool_info = dto["tool"]
        dto_tool_key = tool_info["key"]
        if dto_tool_key not in _ALLOWED_TOOL_KEYS:
            raise ValueError(
                "Cannot apply execution DTO: "
                f"tool key mismatch (dto={dto_tool_key!r}, "
                f"allowed={sorted(_ALLOWED_TOOL_KEYS)!r})."
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

        Accepts Protein Prep v2 (``action`` + optional ``selection``), Target
        Preparation 2.0 (action-less with optional ``pocket``), and v1
        (keep/remove lists, treated as prepare with no selection).

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
        model_missing_loops = True if raw_loops is None else bool(raw_loops)

        raw_pocket = inputs.get("pocket")
        pocket: dict[str, Any] | None = None
        if raw_pocket is not None:
            if not isinstance(raw_pocket, dict):
                raise ValueError("Invalid pocket in execution inputs.")
            pocket = dict(raw_pocket)

        return _ParsedInputs(
            protein=protein_input,
            action=action,
            pdb_id=pdb_id,
            selection=selection,
            model_missing_loops=model_missing_loops,
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

        Rehydrates historical recommendation and preparation executions from
        either routed tool key.

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
        instance._pocket = (
            PocketFinderConfig.from_tool_input(parsed.pocket)
            if parsed.pocket is not None
            else None
        )
        instance._direct_tool_version = TOOL_KEYS_AND_VERSIONS["protein_prep"][
            "tool_version"
        ]
        return instance

    @classmethod
    def from_id(cls, id: str, *, client: DeepOriginClient | None = None) -> Self:
        """Construct from either protein-prep or target-preparation execution id.

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
        """List executions across both ProteinPrep tool keys.

        Args:
            client: Optional API client.
            status: Optional status filter on hydrated instances.

        Returns:
            Instances for both tool keys, newest ``createdAt`` first.
        """
        if client is None:
            from deeporigin.platform.client import DeepOriginClient as _Client

            client = _Client()
        all_dtos: list[dict[str, Any]] = []
        for tool_key in (_PROTEIN_PREP_TOOL_KEY, _TARGET_PREP_TOOL_KEY):
            page = client.executions.list(  # ty:ignore[unresolved-attribute]
                fetch_all_pages=True,
                tool_key=tool_key,
            ).get("data", [])
            all_dtos.extend(
                dto
                for dto in page
                if isinstance(dto, dict) and dto.get("tool", {}).get("key") == tool_key
            )
        all_dtos.sort(key=_dto_created_at, reverse=True)
        instances = [cls.from_dto(dto, client=client) for dto in all_dtos]
        if status is not None:
            instances = [item for item in instances if item.status in status]
        return instances

    @classmethod
    def from_last_run(cls, *, client: DeepOriginClient | None = None) -> Self:
        """Return the newest execution across both routed tool keys.

        Args:
            client: Optional API client.

        Returns:
            Rehydrated :class:`ProteinPrep` for the newest matching execution.

        Raises:
            ValueError: If no executions exist for either tool key.
        """
        if client is None:
            from deeporigin.platform.client import DeepOriginClient as _Client

            client = _Client()
        candidates: list[dict[str, Any]] = []
        for tool_key in (_PROTEIN_PREP_TOOL_KEY, _TARGET_PREP_TOOL_KEY):
            response = client.executions.list(  # ty:ignore[unresolved-attribute]
                tool_key=tool_key,
                order=EXECUTION_LIST_ORDER_CREATED_DESC,
                page=0,
                page_size=1,
            )
            dtos = response.get("data") or []
            if dtos and isinstance(dtos[0], dict):
                candidates.append(dtos[0])
        if not candidates:
            raise ValueError(
                "No executions found for ProteinPrep "
                f"(tool_keys={sorted(_ALLOWED_TOOL_KEYS)!r})."
            )
        candidates.sort(key=_dto_created_at, reverse=True)
        return cls.from_dto(candidates[0], client=client)

    def _protein_from_outputs(self, data: dict[str, Any]) -> Protein:
        """Build the result Protein from an output dict.

        Args:
            data: Prepared-protein payload (``jobOutputs.protein`` or explorer
                ``data``).

        Returns:
            Prepared :class:`Protein`, usually registered via ``protein_id``.
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

    def _result_rows(self, result_type: str) -> list[dict[str, Any]]:
        """Return result-explorer data payloads for one child result type.

        Args:
            result_type: Indexed result type string.

        Returns:
            Data dicts for this execution id, or an empty list on failure.
        """
        exec_id = self._ensure_id()
        try:
            response = self.client.results.get(
                filter_dict={"tool_key": {"eq": self.tool_key}},
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
                if isinstance(data, dict) and data.get("protein_id"):
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

    def get_report(
        self,
        dto: dict[str, Any] | None = None,
    ) -> StructureReportResult | None:
        """Return the prepared Structure Report when this run requested one.

        Args:
            dto: Optional execution payload used as a job-output fallback.

        Returns:
            Prepared report, or ``None`` when requested but not yet published.

        Raises:
            ValueError: If :attr:`id` is unset, or the direct protein-prep path
                ran (report excluded).
        """
        from deeporigin.drug_discovery.structure_report import StructureReportResult

        self._ensure_id()
        if self.tool_key != _TARGET_PREP_TOOL_KEY:
            raise ValueError(PROTEIN_PREP_REPORT_EXCLUDED_MSG)
        indexed = self._result_rows(_RESULT_TYPE_STRUCTURE_REPORT)
        for row in indexed:
            if row.get("report_role") == "prepared":
                return StructureReportResult.from_json(row)
        outputs = self._execution_outputs(dto)
        rows = outputs.get("structure_reports")
        if not isinstance(rows, list):
            return None
        for row in rows:
            if (
                isinstance(row, dict)
                and row.get("report_role", "prepared") == "prepared"
            ):
                return StructureReportResult.from_json(row)
        return None

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
            ValueError: If :attr:`id` is unset, or ``pocket`` was not configured.
        """
        self._ensure_id()
        if self._pocket is None:
            raise ValueError(PROTEIN_PREP_POCKETS_EXCLUDED_MSG)
        indexed = self._result_rows(_RESULT_TYPE_POCKET)
        outputs = self._execution_outputs(dto)
        raw: Any = indexed if indexed else outputs.get("pockets")
        if not isinstance(raw, list):
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
