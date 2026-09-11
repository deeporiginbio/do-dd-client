"""PocketFinder -- find binding pockets via synchronous or asynchronous execution.

Sync usage (blocking, returns pockets directly)::

    pf = PocketFinder(protein)
    pf.run(quote=True)   # populates pf.estimate; pf.status == "Quoted"
    pockets = pf.run()   # blocking; calls get_results(); populates pf.cost

Async usage (persisted execution, watch in notebook)::

    pf = PocketFinder(protein)
    pf.start()            # submits async; sets pf.id and pf.status
    await pf.watch()      # live Jupyter updates (or pf.sync() in a loop)
    pockets = pf.get_results()

Define-by-selection (one pocket from residue/ligand/cofactor selectors)::

    pf = PocketFinder(
        protein,
        mode="define-by-selection",
        selections=[{"kind": "ligand", "author": {"chain_id": "A", "resname": "LIG"}}],
        pocket_radius=10.0,
        align_to_pocket=True,
    )
    pockets = pf.run()

From-crystal-ligand (one pocket from a crystal ligand, either still embedded in
a holo structure, or already extracted into a separate ``Ligand``)::

    # ligand still embedded in the protein file; identify it by its bare
    # residue/ligand code
    pf = PocketFinder(protein, mode="from-crystal-ligand", ligand_id="635")
    pockets = pf.run()

    # ligand already extracted (also strips it from the protein structure)
    crystal_ligand = protein.extract_ligand()
    pf = PocketFinder(
        protein,
        mode="from-crystal-ligand",
        crystal_ligand=crystal_ligand,
    )
    pockets = pf.run()
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, Self, TypedDict

from beartype import beartype

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import (
    AsyncExecutableMixin,
    SyncExecutableMixin,
)
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.protein_prep import _protein_tool_input
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status

PocketFinderMode = Literal["auto-find", "define-by-selection", "from-crystal-ligand"]
PocketSelectionKind = Literal["residue", "ligand", "cofactor"]
BoxGeometry = Literal["ligand-extents", "fixed-radius"]

_VALID_MODES: frozenset[str] = frozenset(
    {"auto-find", "define-by-selection", "from-crystal-ligand"}
)
_VALID_SELECTION_KINDS: frozenset[str] = frozenset({"residue", "ligand", "cofactor"})
_VALID_BOX_GEOMETRIES: frozenset[str] = frozenset({"ligand-extents", "fixed-radius"})
_DEFAULT_POCKET_COUNT = 1
_DEFAULT_POCKET_MIN_SIZE = 30
_DEFAULT_POCKET_RADIUS = 10.0


class PocketSelectionAuthor(TypedDict):
    """PDB/mmCIF author identity for a selected component (tool wire shape)."""

    chain_id: str
    resseq: NotRequired[int]
    resname: NotRequired[str]
    icode: NotRequired[str]


class PocketSelection(TypedDict):
    """One residue, ligand, or cofactor selector for define-by-selection mode."""

    kind: PocketSelectionKind
    author: PocketSelectionAuthor


class PocketFinder(
    Execution,
    SyncExecutableMixin,
    AsyncExecutableMixin,
    NotebookWatchMixin,
):
    """Find binding pockets in a protein structure.

    Supports ``mode="auto-find"`` (classifier; default), ``mode="define-by-selection"``
    (one pocket from structured selections), and ``mode="from-crystal-ligand"``
    (one pocket from a crystal ligand, either resolved in-place within the
    supplied protein via ``ligand_id``, or supplied separately via
    ``crystal_ligand``).

    The execution request body includes ``sync`` (``true`` = blocking, ``false`` =
    immediate DTO).     :meth:`run` sets ``"sync": true`` and blocks until the run
    finishes. :meth:`start` sets ``"sync": false`` in ``inputs`` (non-blocking);
    ``start`` returns immediately with an execution DTO that you can poll with
    :meth:`sync`, wait on with :meth:`wait`, or watch in Jupyter with
    :meth:`watch`. Track async jobs with :meth:`sync`, :meth:`from_id`, and
    :meth:`list`.

    Attributes:
        protein: The protein to analyse.
        mode: ``auto-find``, ``define-by-selection``, or ``from-crystal-ligand``.
        pocket_count: Maximum pockets (auto-find).
        pocket_min_size: Minimum pocket volume in cubic Angstroms (auto-find).
        selections: Selectors for define-by-selection (tool wire dicts).
        pocket_radius: Half-edge of the docking cube in angstroms
            (define-by-selection, or from-crystal-ligand with
            ``box_geometry="fixed-radius"``).
        align_to_pocket: PCA-orient ``box.rotation_deg`` from selection atoms.
        crystal_ligand: Extracted ``Ligand`` to build the pocket from
            (from-crystal-ligand).
        ligand_id: Bare ligand/residue code resolved in-place within
            ``protein`` (from-crystal-ligand).
        box_geometry: ``"ligand-extents"`` or ``"fixed-radius"``
            (from-crystal-ligand).
        box_padding: Padding in angstroms added to ligand PCA extents when
            ``box_geometry`` is ``"ligand-extents"`` (from-crystal-ligand).
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_key"]

    def __init__(
        self,
        protein: Protein,
        *,
        mode: PocketFinderMode = "auto-find",
        pocket_count: int | None = None,
        pocket_min_size: int | None = None,
        selections: list[PocketSelection] | None = None,
        pocket_radius: float | None = None,
        align_to_pocket: bool | None = None,
        crystal_ligand: Ligand | None = None,
        ligand_id: str | None = None,
        box_geometry: BoxGeometry | None = None,
        box_padding: float | None = None,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_version"],
        client: DeepOriginClient | None = None,
    ) -> None:
        """Create a PocketFinder for the given protein.

        Args:
            protein: Protein structure to search for pockets.
            mode: ``auto-find`` (default), ``define-by-selection``, or
                ``from-crystal-ligand``.
            pocket_count: Max pockets to detect (auto-find). Defaults to 1.
            pocket_min_size: Minimum pocket size in cubic Angstroms (auto-find).
                Defaults to 30.
            selections: Residue/ligand/cofactor selectors (define-by-selection).
            pocket_radius: Half-edge of the docking cube in angstroms
                (define-by-selection, or from-crystal-ligand with
                ``box_geometry="fixed-radius"``). Defaults to 10.
            align_to_pocket: When true in define-by-selection, PCA-orient the
                box from selection atoms. Defaults to false.
            crystal_ligand: Extracted ``Ligand`` (e.g. from
                :meth:`~deeporigin.drug_discovery.structures.protein.Protein.extract_ligand`)
                to build the pocket from (from-crystal-ligand). Exactly one of
                ``crystal_ligand`` or ``ligand_id`` is required in that mode.
            ligand_id: Bare ligand/residue code (e.g. ``"IBP"``) to locate
                directly within ``protein``, when the crystal ligand is still
                embedded in the protein file (from-crystal-ligand).
            box_geometry: ``"ligand-extents"`` (PCA-align the box to ligand
                heavy-atom extents plus ``box_padding``) or ``"fixed-radius"``
                (cube of edge ``2 * pocket_radius``). Only valid with
                ``mode="from-crystal-ligand"``; platform default is
                ``"ligand-extents"``.
            box_padding: Padding in angstroms added on each side of ligand PCA
                extents when ``box_geometry`` is ``"ligand-extents"``. Only
                valid with ``mode="from-crystal-ligand"``; platform default is
                4.0.
            tool_version: Platform tool version to run. Settable so callers
                can pin or upgrade independently of the SDK release.
            client: Optional API client. Uses the default if not provided.

        Raises:
            ValueError: If mode/kwargs are inconsistent or structurally invalid.
        """
        super().__init__(client=client)
        self.tool_version = tool_version
        self._protein = protein
        self._mode: PocketFinderMode = mode
        self._pocket_count = (
            _DEFAULT_POCKET_COUNT if pocket_count is None else pocket_count
        )
        self._pocket_min_size = (
            _DEFAULT_POCKET_MIN_SIZE if pocket_min_size is None else pocket_min_size
        )
        self._selections: list[PocketSelection] | None = selections
        self._pocket_radius = _DEFAULT_POCKET_RADIUS
        if pocket_radius is not None and mode in (
            "define-by-selection",
            "from-crystal-ligand",
        ):
            try:
                self._pocket_radius = float(pocket_radius)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"pocket_radius must be a number, got {pocket_radius!r}"
                ) from exc
        if align_to_pocket is None:
            self._align_to_pocket = False
        elif isinstance(align_to_pocket, bool):
            self._align_to_pocket = align_to_pocket
        else:
            raise ValueError(
                f"align_to_pocket must be a bool, got {type(align_to_pocket).__name__}"
            ) from None
        self._crystal_ligand: Ligand | None = crystal_ligand
        self._crystal_ligand_remote_path: str | None = None
        self._ligand_id: str | None = None
        if ligand_id is not None:
            if not isinstance(ligand_id, str):
                raise ValueError(
                    f"ligand_id must be a str, got {type(ligand_id).__name__}"
                ) from None
            self._ligand_id = ligand_id.strip()
        self._box_geometry: str | None = None
        if box_geometry is not None:
            if not isinstance(box_geometry, str):
                raise ValueError(
                    f"box_geometry must be a str, got {type(box_geometry).__name__}"
                ) from None
            self._box_geometry = box_geometry
        self._box_padding: float | None = None
        if box_padding is not None:
            try:
                self._box_padding = float(box_padding)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"box_padding must be a number, got {box_padding!r}"
                ) from exc
        self._validate_construction(
            mode=mode,
            pocket_count_provided=pocket_count is not None,
            pocket_min_size_provided=pocket_min_size is not None,
            selections_provided=selections is not None,
            pocket_radius_provided=pocket_radius is not None,
            align_to_pocket_provided=align_to_pocket is not None,
            crystal_ligand_provided=crystal_ligand is not None,
            ligand_id_provided=ligand_id is not None,
            box_geometry_provided=box_geometry is not None,
            box_padding_provided=box_padding is not None,
        )

    @property
    def protein(self) -> Protein:
        """The protein to analyse."""
        return self._protein

    @property
    def mode(self) -> PocketFinderMode:
        """Pocket finder mode: ``auto-find`` or ``define-by-selection``."""
        return self._mode

    @property
    def pocket_count(self) -> int:
        """Maximum number of pockets to detect (auto-find)."""
        return self._pocket_count

    @property
    def pocket_min_size(self) -> int:
        """Minimum pocket volume in cubic Angstroms (auto-find)."""
        return self._pocket_min_size

    @property
    def selections(self) -> list[PocketSelection] | None:
        """Selectors for define-by-selection mode, or None for auto-find."""
        return self._selections

    @property
    def pocket_radius(self) -> float:
        """Half-edge of the docking cube in angstroms (define-by-selection)."""
        return self._pocket_radius

    @property
    def align_to_pocket(self) -> bool:
        """Whether to PCA-orient the box from selection atoms."""
        return self._align_to_pocket

    @property
    def crystal_ligand(self) -> Ligand | None:
        """Extracted crystal ligand (from-crystal-ligand), or None."""
        return self._crystal_ligand

    @property
    def ligand_id(self) -> str | None:
        """Bare ligand/residue code to locate in-place (from-crystal-ligand), or None."""
        return self._ligand_id

    @property
    def box_geometry(self) -> str | None:
        """Box geometry for from-crystal-ligand, or None to use the platform default."""
        return self._box_geometry

    @property
    def box_padding(self) -> float | None:
        """Padding in angstroms added to ligand PCA extents (from-crystal-ligand)."""
        return self._box_padding

    def __repr__(self) -> str:
        """Return a concise summary of the PocketFinder."""
        parts = [f"PocketFinder protein={self.protein.id!r}", f"mode={self.mode!r}"]
        if self.id:
            parts.append(f"id={self.id!r}")
        if self._mode == "define-by-selection":
            n = len(self._selections or [])
            parts.append(f"selections={n}")
            parts.append(f"pocket_radius={self.pocket_radius}")
            parts.append(f"align_to_pocket={self.align_to_pocket}")
        elif self._mode == "from-crystal-ligand":
            if self._crystal_ligand is not None:
                parts.append(f"crystal_ligand={self._crystal_ligand.name!r}")
            elif self._crystal_ligand_remote_path is not None:
                parts.append(f"crystal_ligand={self._crystal_ligand_remote_path!r}")
            else:
                parts.append(f"ligand_id={self.ligand_id!r}")
            parts.append(f"box_geometry={self.box_geometry!r}")
            parts.append(f"pocket_radius={self.pocket_radius}")
        else:
            parts.append(f"pocket_count={self.pocket_count}")
            parts.append(f"pocket_min_size={self.pocket_min_size}")
        return f"<{' '.join(parts)}>"

    def _validate_construction(
        self,
        *,
        mode: str,
        pocket_count_provided: bool,
        pocket_min_size_provided: bool,
        selections_provided: bool,
        pocket_radius_provided: bool,
        align_to_pocket_provided: bool,
        crystal_ligand_provided: bool,
        ligand_id_provided: bool,
        box_geometry_provided: bool,
        box_padding_provided: bool,
    ) -> None:
        """Raise if mode/kwargs mixing or structural checks fail."""
        if not isinstance(mode, str) or mode not in _VALID_MODES:
            raise ValueError(
                f"mode must be one of {sorted(_VALID_MODES)}, got {mode!r}"
            ) from None

        if mode == "auto-find":
            if selections_provided:
                raise ValueError(
                    "selections is only valid when mode is 'define-by-selection'"
                ) from None
            if pocket_radius_provided:
                raise ValueError(
                    "pocket_radius is only valid when mode is 'define-by-selection' "
                    "or 'from-crystal-ligand'"
                ) from None
            if align_to_pocket_provided:
                raise ValueError(
                    "align_to_pocket is only valid when mode is 'define-by-selection'"
                ) from None
            self._validate_no_crystal_ligand_params(
                crystal_ligand_provided=crystal_ligand_provided,
                ligand_id_provided=ligand_id_provided,
                box_geometry_provided=box_geometry_provided,
                box_padding_provided=box_padding_provided,
            )
            self._validate_auto_find_params()
            return

        if mode == "from-crystal-ligand":
            if pocket_count_provided:
                raise ValueError(
                    "pocket_count is only valid when mode is 'auto-find'"
                ) from None
            if pocket_min_size_provided:
                raise ValueError(
                    "pocket_min_size is only valid when mode is 'auto-find'"
                ) from None
            if selections_provided:
                raise ValueError(
                    "selections is only valid when mode is 'define-by-selection'"
                ) from None
            if align_to_pocket_provided:
                raise ValueError(
                    "align_to_pocket is only valid when mode is 'define-by-selection'"
                ) from None
            self._validate_crystal_ligand_params(
                crystal_ligand_provided=crystal_ligand_provided,
                ligand_id_provided=ligand_id_provided,
            )
            return

        # define-by-selection
        if pocket_count_provided:
            raise ValueError(
                "pocket_count is only valid when mode is 'auto-find'"
            ) from None
        if pocket_min_size_provided:
            raise ValueError(
                "pocket_min_size is only valid when mode is 'auto-find'"
            ) from None
        self._validate_no_crystal_ligand_params(
            crystal_ligand_provided=crystal_ligand_provided,
            ligand_id_provided=ligand_id_provided,
            box_geometry_provided=box_geometry_provided,
            box_padding_provided=box_padding_provided,
        )
        if (
            not selections_provided
            or not isinstance(self._selections, list)
            or not self._selections
        ):
            raise ValueError(
                "selections must be a non-empty list when mode is 'define-by-selection'"
            ) from None
        self._selections = _normalize_selections(self._selections)
        self._validate_selection_params()

    def _validate_auto_find_params(self) -> None:
        """Raise if auto-find ``pocket_count`` or ``pocket_min_size`` are invalid."""
        if self._pocket_count < 1:
            raise ValueError("pocket_count must be at least 1") from None
        if self._pocket_min_size < 1:
            raise ValueError("pocket_min_size must be at least 1") from None

    def _validate_selection_params(self) -> None:
        """Raise if define-by-selection numeric params are invalid."""
        if self._pocket_radius <= 0:
            raise ValueError("pocket_radius must be greater than 0") from None

    def _validate_no_crystal_ligand_params(
        self,
        *,
        crystal_ligand_provided: bool,
        ligand_id_provided: bool,
        box_geometry_provided: bool,
        box_padding_provided: bool,
    ) -> None:
        """Raise if crystal-ligand-only kwargs were passed for another mode."""
        if crystal_ligand_provided or ligand_id_provided:
            raise ValueError(
                "crystal_ligand/ligand_id are only valid when mode is "
                "'from-crystal-ligand'"
            ) from None
        if box_geometry_provided or box_padding_provided:
            raise ValueError(
                "box_geometry/box_padding are only valid when mode is "
                "'from-crystal-ligand'"
            ) from None

    def _validate_crystal_ligand_params(
        self,
        *,
        crystal_ligand_provided: bool,
        ligand_id_provided: bool,
    ) -> None:
        """Raise if from-crystal-ligand kwargs are missing or structurally invalid."""
        if crystal_ligand_provided and ligand_id_provided:
            raise ValueError(
                "provide exactly one of crystal_ligand or ligand_id, not both"
            ) from None
        if not crystal_ligand_provided and not ligand_id_provided:
            raise ValueError(
                "crystal_ligand or ligand_id is required when mode is "
                "'from-crystal-ligand'"
            ) from None
        if crystal_ligand_provided and not isinstance(self._crystal_ligand, Ligand):
            raise ValueError(
                "crystal_ligand must be a Ligand, got "
                f"{type(self._crystal_ligand).__name__}"
            ) from None
        if ligand_id_provided and not self._ligand_id:
            raise ValueError("ligand_id must be a non-empty string") from None
        if (
            self._box_geometry is not None
            and self._box_geometry not in _VALID_BOX_GEOMETRIES
        ):
            raise ValueError(
                f"box_geometry must be one of {sorted(_VALID_BOX_GEOMETRIES)}, "
                f"got {self._box_geometry!r}"
            ) from None
        if self._box_padding is not None and self._box_padding < 0:
            raise ValueError("box_padding must be non-negative") from None
        if self._pocket_radius <= 0:
            raise ValueError("pocket_radius must be greater than 0") from None

    def _validate_crystal_ligand_pocket_params(self) -> None:
        """Raise if from-crystal-ligand numeric params are invalid."""
        if self._pocket_radius <= 0:
            raise ValueError("pocket_radius must be greater than 0") from None

    def _validate_pocket_params(self) -> None:
        """Validate mode-specific params before submit."""
        if self._mode == "define-by-selection":
            if not self._selections:
                raise ValueError(
                    "selections must be a non-empty list when mode is "
                    "'define-by-selection'"
                ) from None
            self._validate_selection_params()
        elif self._mode == "from-crystal-ligand":
            self._validate_crystal_ligand_pocket_params()
        else:
            self._validate_auto_find_params()

    def _ensure_protein_remote(self) -> None:
        """Upload/sync protein (and crystal ligand, if set) for the API."""
        self._validate_pocket_params()

        self._protein.sync(lazy=True, client=self.client)
        self._protein.ensure_remote_path(client=self.client, label="Protein")

        if self._mode == "from-crystal-ligand" and self._crystal_ligand is not None:
            self._crystal_ligand.sync(lazy=True, client=self.client)
            self._crystal_ligand.ensure_remote_path(
                client=self.client, label="Crystal ligand"
            )

    def _make_payload(
        self,
        *,
        approve_amount: int | None,
        sync: bool,
    ) -> dict[str, Any]:
        """Build the POST body for ``executions.create``.

        ``inputs.sync`` maps to the pocket-finder tool's declared ``sync``
        input property so the platform estimator can choose direct serving vs.
        Argo workflow. A top-level ``sync`` would be silently dropped (AJV
        default ``true``).
        """
        inputs: dict[str, Any] = {
            "protein": _protein_tool_input(self._protein),
            "mode": self._mode,
            "sync": sync,
        }
        if self._mode == "define-by-selection":
            inputs["selections"] = list(self._selections or [])
            inputs["pocket_radius"] = self._pocket_radius
            inputs["align_to_pocket"] = self._align_to_pocket
        elif self._mode == "from-crystal-ligand":
            inputs["crystal_ligand"] = self._crystal_ligand_tool_input()
            inputs["pocket_radius"] = self._pocket_radius
            if self._box_geometry is not None:
                inputs["box_geometry"] = self._box_geometry
            if self._box_padding is not None:
                inputs["box_padding"] = self._box_padding
        else:
            inputs["pocket_count"] = self._pocket_count
            inputs["pocket_min_size"] = self._pocket_min_size

        payload: dict[str, Any] = {
            "inputs": inputs,
            "outputs": {},
            "metadata": {},
        }
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount
        return payload

    def _crystal_ligand_tool_input(self) -> dict[str, Any]:
        """Build the ``crystal_ligand`` wire dict (``file_path`` or ``ligand_id``)."""
        if self._crystal_ligand is not None:
            file_path = self._crystal_ligand.remote_path
            if not file_path or not str(file_path).strip():
                raise ValueError(
                    "crystal_ligand remote_path is required; sync the crystal "
                    "ligand first."
                )
            return {"file_path": str(file_path)}
        if self._crystal_ligand_remote_path is not None:
            return {"file_path": self._crystal_ligand_remote_path}
        return {"ligand_id": self._ligand_id}

    @staticmethod
    def _parse_protein_input(inputs: dict[str, Any]) -> dict[str, Any]:
        """Validate and return the ``protein`` sub-dict from execution inputs."""
        raw_protein = inputs.get("protein")
        if raw_protein is not None and not isinstance(raw_protein, dict):
            raise ValueError(
                "'protein' in execution userInputs must be a dict, got "
                f"{type(raw_protein).__name__}"
            ) from None
        protein_input = raw_protein or {}
        protein_id = protein_input.get("id")
        file_path = protein_input.get("file_path")
        if protein_id is None and (not file_path or not str(file_path).strip()):
            raise ValueError(
                "Missing 'protein.id' or 'protein.file_path' in execution "
                "userInputs; this execution may have been created with an "
                "older input schema."
            )
        return protein_input

    @staticmethod
    def _parse_mode(inputs: dict[str, Any]) -> PocketFinderMode:
        """Validate and return the ``mode`` from execution inputs."""
        raw_mode = inputs.get("mode")
        if raw_mode is None:
            raw_mode = "auto-find"
        if not isinstance(raw_mode, str) or raw_mode not in _VALID_MODES:
            raise ValueError(
                f"Invalid mode in execution inputs: {raw_mode!r}"
            ) from None
        return raw_mode  # type: ignore[return-value]

    @staticmethod
    def _parse_selection_mode_fields(inputs: dict[str, Any]) -> dict[str, Any]:
        """Parse define-by-selection fields from execution inputs."""
        raw_selections = inputs.get("selections")
        if not isinstance(raw_selections, list) or not raw_selections:
            raise ValueError(
                "Missing or empty 'selections' in define-by-selection execution inputs."
            ) from None
        selections = _normalize_selections(raw_selections)

        raw_radius = inputs.get("pocket_radius")
        try:
            pocket_radius = (
                float(raw_radius) if raw_radius is not None else _DEFAULT_POCKET_RADIUS
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid pocket_radius in execution inputs.") from exc
        if pocket_radius <= 0:
            raise ValueError(
                "pocket_radius from execution inputs must be greater than 0"
            ) from None

        raw_align = inputs.get("align_to_pocket", False)
        if not isinstance(raw_align, bool):
            raise ValueError(
                "'align_to_pocket' in execution inputs must be a bool, got "
                f"{type(raw_align).__name__}"
            ) from None

        return {
            "selections": selections,
            "pocket_radius": pocket_radius,
            "align_to_pocket": raw_align,
            "pocket_count": _DEFAULT_POCKET_COUNT,
            "pocket_min_size": _DEFAULT_POCKET_MIN_SIZE,
            "crystal_ligand": None,
            "crystal_ligand_remote_path": None,
            "ligand_id": None,
            "box_geometry": None,
            "box_padding": None,
        }

    @staticmethod
    def _parse_crystal_ligand_mode_fields(inputs: dict[str, Any]) -> dict[str, Any]:
        """Parse from-crystal-ligand fields from execution inputs.

        Rehydrates the resolved ``file_path``/``ligand_id`` only; a full
        ``Ligand`` object cannot be reconstructed from stored inputs alone
        (no RDKit ``mol`` is stored), so :attr:`crystal_ligand` stays unset
        after :meth:`from_dto` and the raw remote path is kept internally for
        resubmission.
        """
        raw_crystal_ligand = inputs.get("crystal_ligand")
        if not isinstance(raw_crystal_ligand, dict):
            raise ValueError(
                "Missing 'crystal_ligand' in from-crystal-ligand execution inputs."
            ) from None
        raw_file_path = raw_crystal_ligand.get("file_path")
        raw_ligand_id = raw_crystal_ligand.get("ligand_id")
        file_path = str(raw_file_path).strip() if raw_file_path else None
        ligand_id = str(raw_ligand_id).strip() if raw_ligand_id else None
        if not file_path and not ligand_id:
            raise ValueError(
                "'crystal_ligand' in execution inputs must set file_path or ligand_id."
            ) from None

        raw_box_geometry = inputs.get("box_geometry")
        if raw_box_geometry is not None and raw_box_geometry not in (
            _VALID_BOX_GEOMETRIES
        ):
            raise ValueError(
                f"Invalid box_geometry in execution inputs: {raw_box_geometry!r}"
            ) from None

        raw_box_padding = inputs.get("box_padding")
        try:
            box_padding = (
                float(raw_box_padding) if raw_box_padding is not None else None
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid box_padding in execution inputs.") from exc

        raw_radius = inputs.get("pocket_radius")
        try:
            pocket_radius = (
                float(raw_radius) if raw_radius is not None else _DEFAULT_POCKET_RADIUS
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid pocket_radius in execution inputs.") from exc
        if pocket_radius <= 0:
            raise ValueError(
                "pocket_radius from execution inputs must be greater than 0"
            ) from None

        return {
            "selections": None,
            "pocket_radius": pocket_radius,
            "align_to_pocket": False,
            "pocket_count": _DEFAULT_POCKET_COUNT,
            "pocket_min_size": _DEFAULT_POCKET_MIN_SIZE,
            "crystal_ligand": None,
            "crystal_ligand_remote_path": file_path,
            "ligand_id": ligand_id,
            "box_geometry": raw_box_geometry,
            "box_padding": box_padding,
        }

    @staticmethod
    def _parse_auto_find_mode_fields(inputs: dict[str, Any]) -> dict[str, Any]:
        """Parse auto-find fields from execution inputs."""
        raw_count = inputs.get("pocket_count")
        raw_min_size = inputs.get("pocket_min_size")
        try:
            pocket_count = (
                int(raw_count) if raw_count is not None else _DEFAULT_POCKET_COUNT
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid pocket_count in execution inputs.") from exc
        try:
            pocket_min_size = (
                int(raw_min_size)
                if raw_min_size is not None
                else _DEFAULT_POCKET_MIN_SIZE
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid pocket_min_size in execution inputs.") from exc
        if pocket_count < 1:
            raise ValueError("pocket_count from execution inputs must be at least 1")
        if pocket_min_size < 1:
            raise ValueError("pocket_min_size from execution inputs must be at least 1")

        return {
            "selections": None,
            "pocket_radius": _DEFAULT_POCKET_RADIUS,
            "align_to_pocket": False,
            "pocket_count": pocket_count,
            "pocket_min_size": pocket_min_size,
            "crystal_ligand": None,
            "crystal_ligand_remote_path": None,
            "ligand_id": None,
            "box_geometry": None,
            "box_padding": None,
        }

    @classmethod
    def _parse_inputs_dict(cls, inputs: dict[str, Any]) -> dict[str, Any]:
        """Parse execution ``userInputs`` into PocketFinder field values.

        Returns:
            Dict with ``protein_input``, ``mode``, and mode-specific fields.
        """
        if not isinstance(inputs, dict):
            raise ValueError(
                "Execution 'userInputs'/'inputs' must be a dict, got "
                f"{type(inputs).__name__}"
            ) from None
        protein_input = cls._parse_protein_input(inputs)
        mode = cls._parse_mode(inputs)
        if mode == "define-by-selection":
            mode_fields = cls._parse_selection_mode_fields(inputs)
        elif mode == "from-crystal-ligand":
            mode_fields = cls._parse_crystal_ligand_mode_fields(inputs)
        else:
            mode_fields = cls._parse_auto_find_mode_fields(inputs)
        return {"protein_input": protein_input, "mode": mode, **mode_fields}

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct a ``PocketFinder`` from a tools execution DTO.

        Rehydrates ``protein`` and mode-specific inputs from ``userInputs``
        (falling back to ``inputs`` for older payloads). When ``protein.id`` is
        present, the protein is loaded with
        ``Protein.from_id(..., download=False)`` and ``remote_path_override``
        from the stored input. When only ``file_path`` is present (e.g. an
        unregistered Prepared Protein), builds an in-memory Protein with that
        remote path.

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client. Uses the default if not provided.

        Returns:
            A ``PocketFinder`` with ``id``, pricing fields, and domain inputs set.

        Raises:
            ValueError: If neither ``protein.id`` nor ``protein.file_path`` is
                present in stored inputs, or selection inputs are invalid.
        """
        instance = super().from_dto(dto, client=client)
        raw_user_inputs = dto.get("userInputs")
        inputs: dict[str, Any] = (
            raw_user_inputs
            if raw_user_inputs is not None
            else (dto.get("inputs") or {})
        )
        parsed = cls._parse_inputs_dict(inputs)
        protein_input = parsed["protein_input"]

        protein_id = protein_input.get("id")
        file_path = protein_input.get("file_path")
        if protein_id is not None:
            instance._protein = Protein.from_id(
                str(protein_id),
                client=client,
                download=False,
                remote_path_override=file_path,
            )
        else:
            name = str(file_path).rsplit("/", 1)[-1] if file_path else "protein"
            instance._protein = Protein(
                name=name,
                structure=None,
                remote_path=str(file_path) if file_path else None,
            )
        instance._mode = parsed["mode"]
        instance._pocket_count = parsed["pocket_count"]
        instance._pocket_min_size = parsed["pocket_min_size"]
        instance._selections = parsed["selections"]
        instance._pocket_radius = parsed["pocket_radius"]
        instance._align_to_pocket = parsed["align_to_pocket"]
        instance._crystal_ligand = parsed["crystal_ligand"]
        instance._crystal_ligand_remote_path = parsed["crystal_ligand_remote_path"]
        instance._ligand_id = parsed["ligand_id"]
        instance._box_geometry = parsed["box_geometry"]
        instance._box_padding = parsed["box_padding"]

        return instance

    @beartype
    def get_results(self, dto: dict[str, Any] | None = None) -> list[Pocket]:
        """Load pockets for this execution from the data platform or ``jobOutputs``.

        Tries :meth:`~deeporigin.drug_discovery.structures.pocket.Pocket.from_result`
        first. On failure, parses ``jobOutputs.pockets`` from ``dto``, or from
        ``client.executions.get`` when ``dto`` is omitted (for example after
        :meth:`~deeporigin.drug_discovery.execution.Execution.from_id`).

        Args:
            dto: Optional execution payload (``executions.create`` /
                ``executions.get``). Passing it avoids an extra GET when the data
                platform path fails but the sync response included ``jobOutputs``.

        Returns:
            List of ``Pocket`` objects for this execution. Each pocket has
            :attr:`Pocket.protein` set to this finder's protein.

        Raises:
            ValueError: If :attr:`id` is unset.
            DeepOriginException: If no pockets could be loaded from the data
                platform or ``jobOutputs``.
        """
        exec_id = self._ensure_id()

        try:
            pockets = Pocket.from_result(
                execution_id=exec_id,
                client=self.client,
            )
        except Exception:
            pockets = None

        if pockets is None:
            try:
                if dto is None:
                    dto = self.client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
                jo = dto.get("jobOutputs")
                raw = jo.get("pockets", []) if isinstance(jo, dict) else []
                pockets = Pocket.from_json(raw, client=self.client)
            except Exception:
                raise DeepOriginException(
                    title="Could not load pockets",
                    message=(
                        "No pockets could be parsed from the data platform or "
                        "jobOutputs."
                    ),
                ) from None

        return self._stamp_parent_protein(pockets)

    @beartype
    def run(
        self,
        *,
        quote: bool = False,
        approve_amount: int | None = None,
    ) -> list[Pocket] | None:
        """Execute pocket finding synchronously (blocking).

        Submits one synchronous tools execution (``sync=True``) and returns the
        detected pockets via :meth:`get_results`. The server blocks until the
        run completes; use :meth:`start` for async, persisted execution.

        Pass ``quote=True`` (or ``approve_amount=0``) to request a cost estimate
        only. In that case the platform returns a ``Quoted`` DTO, the instance
        is updated with ``estimate`` and ``status="Quoted"``, and ``None`` is
        returned.

        Args:
            quote: Shorthand for ``approve_amount=0``.
            approve_amount: Spend cap forwarded to the platform as ``approveAmount``.

        Returns:
            List of ``Pocket`` objects, or ``None`` when the platform responds
            with ``Quoted`` status.

        Raises:
            DeepOriginException: If no pockets could be loaded from the data
                platform or ``jobOutputs``.
        """
        self._ensure_protein_remote()
        resolved_amount = 0 if quote else approve_amount
        dto = self._create_execution(
            data=self._make_payload(approve_amount=resolved_amount, sync=True),
        )
        self.update_from_dto(dto)

        if self.status == "Quoted":
            return None

        if not is_success_status(self.status):
            return None

        return self.get_results(dto)

    def _stamp_parent_protein(self, pockets: list[Pocket]) -> list[Pocket]:
        """Attach this finder's protein to each pocket.

        Sets :attr:`Pocket.protein` to this run's protein. Fills
        :attr:`Pocket.protein_id` when it is missing and the protein has an id.

        Args:
            pockets: Pockets loaded from the platform or job outputs.

        Returns:
            The same list, with parent protein stamped on each pocket.
        """
        for pocket in pockets:
            pocket.protein = self._protein
        return pockets

    def _start_impl(self, *, approve_amount: int | None = None, **kwargs: Any) -> None:
        """Submit pocket finding as a persisted async execution (``sync=False``).

        Sets :attr:`id`, :attr:`status`, and :attr:`_dto` from the
        platform response. Poll :meth:`sync`, block with :meth:`wait`, or use
        :meth:`watch` in Jupyter until the execution reaches a terminal state,
        then call :meth:`get_results` to retrieve the pockets.

        Args:
            approve_amount: Spend cap forwarded to the platform.
        """
        self._ensure_protein_remote()
        execution_dto = self._create_execution(
            data=self._make_payload(approve_amount=approve_amount, sync=False),
        )
        execution_id = execution_dto.get("executionId")
        if execution_id is None:
            raise ValueError("Execution response must contain 'executionId'") from None

        self._dto = execution_dto
        self._id = execution_id
        self.status = execution_dto.get("status")


def _normalize_selection_author(index: int, author: Any) -> PocketSelectionAuthor:
    """Validate and return the ``author`` sub-dict of ``selections[index]``."""
    if not isinstance(author, dict):
        raise ValueError(f"selections[{index}].author must be a dict") from None
    chain_id = author.get("chain_id")
    if chain_id is None or not str(chain_id).strip():
        raise ValueError(f"selections[{index}].author.chain_id is required") from None

    author_out: PocketSelectionAuthor = {"chain_id": str(chain_id).strip()}
    if "resseq" in author and author["resseq"] is not None:
        try:
            author_out["resseq"] = int(author["resseq"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"selections[{index}].author.resseq must be an int"
            ) from exc
    if "resname" in author and author["resname"] is not None:
        author_out["resname"] = str(author["resname"])
    if "icode" in author and author["icode"] is not None:
        author_out["icode"] = str(author["icode"])
    return author_out


def _normalize_selection_item(index: int, item: Any) -> PocketSelection:
    """Validate and return a single normalized selection dict."""
    if not isinstance(item, dict):
        raise ValueError(
            f"selections[{index}] must be a dict, got {type(item).__name__}"
        ) from None
    kind = item.get("kind")
    if not isinstance(kind, str) or kind not in _VALID_SELECTION_KINDS:
        raise ValueError(
            f"selections[{index}].kind must be one of "
            f"{sorted(_VALID_SELECTION_KINDS)}, got {kind!r}"
        ) from None
    author_out = _normalize_selection_author(index, item.get("author"))
    return {"kind": kind, "author": author_out}


def _normalize_selections(raw: list[Any]) -> list[PocketSelection]:
    """Validate and return selection dicts matching the tool wire shape.

    Args:
        raw: Caller-provided selection list (dicts).

    Returns:
        Normalized ``PocketSelection`` dicts (shallow copies of author).

    Raises:
        ValueError: If any selection is structurally invalid.
    """
    return [_normalize_selection_item(index, item) for index, item in enumerate(raw)]
