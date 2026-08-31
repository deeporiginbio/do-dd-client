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
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status

PocketFinderMode = Literal["auto-find", "define-by-selection"]
PocketSelectionKind = Literal["residue", "ligand", "cofactor"]

_VALID_MODES: frozenset[str] = frozenset({"auto-find", "define-by-selection"})
_VALID_SELECTION_KINDS: frozenset[str] = frozenset({"residue", "ligand", "cofactor"})
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

    Supports ``mode="auto-find"`` (classifier; default) and
    ``mode="define-by-selection"`` (one pocket from structured selections).

    The execution request body includes ``sync`` (``true`` = blocking, ``false`` =
    immediate DTO).     :meth:`run` sets ``"sync": true`` and blocks until the run
    finishes. :meth:`start` sets ``"sync": false`` in ``inputs`` (non-blocking);
    ``start`` returns immediately with an execution DTO that you can poll with
    :meth:`sync`, wait on with :meth:`wait`, or watch in Jupyter with
    :meth:`watch`. Track async jobs with :meth:`sync`, :meth:`from_id`, and
    :meth:`list`.

    Attributes:
        protein: The protein to analyse.
        mode: ``auto-find`` or ``define-by-selection``.
        pocket_count: Maximum pockets (auto-find).
        pocket_min_size: Minimum pocket volume in cubic Angstroms (auto-find).
        selections: Selectors for define-by-selection (tool wire dicts).
        pocket_radius: Half-edge of the docking cube in angstroms (selection).
        align_to_pocket: PCA-orient ``box.rotation_deg`` from selection atoms.
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
        tool_version: str = TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_version"],
        client: DeepOriginClient | None = None,
    ) -> None:
        """Create a PocketFinder for the given protein.

        Args:
            protein: Protein structure to search for pockets.
            mode: ``auto-find`` (default) or ``define-by-selection``.
            pocket_count: Max pockets to detect (auto-find). Defaults to 1.
            pocket_min_size: Minimum pocket size in cubic Angstroms (auto-find).
                Defaults to 30.
            selections: Residue/ligand/cofactor selectors (define-by-selection).
            pocket_radius: Half-edge of the docking cube in angstroms
                (define-by-selection). Defaults to 10.
            align_to_pocket: When true in define-by-selection, PCA-orient the
                box from selection atoms. Defaults to false.
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
        if pocket_radius is not None and mode == "define-by-selection":
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
        self._validate_construction(
            mode=mode,
            pocket_count_provided=pocket_count is not None,
            pocket_min_size_provided=pocket_min_size is not None,
            selections_provided=selections is not None,
            pocket_radius_provided=pocket_radius is not None,
            align_to_pocket_provided=align_to_pocket is not None,
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
                    "pocket_radius is only valid when mode is 'define-by-selection'"
                ) from None
            if align_to_pocket_provided:
                raise ValueError(
                    "align_to_pocket is only valid when mode is 'define-by-selection'"
                ) from None
            self._validate_auto_find_params()
            return

        if pocket_count_provided:
            raise ValueError(
                "pocket_count is only valid when mode is 'auto-find'"
            ) from None
        if pocket_min_size_provided:
            raise ValueError(
                "pocket_min_size is only valid when mode is 'auto-find'"
            ) from None
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

    def _validate_pocket_params(self) -> None:
        """Validate mode-specific params before submit."""
        if self._mode == "define-by-selection":
            if not self._selections:
                raise ValueError(
                    "selections must be a non-empty list when mode is "
                    "'define-by-selection'"
                ) from None
            self._validate_selection_params()
        else:
            self._validate_auto_find_params()

    def _ensure_protein_remote(self) -> None:
        """Upload/sync protein and ensure ``remote_path`` is set for the API."""
        self._validate_pocket_params()

        self._protein.sync(lazy=True, client=self.client)
        self._protein.ensure_remote_path(client=self.client, label="Protein")

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
        mode_fields = (
            cls._parse_selection_mode_fields(inputs)
            if mode == "define-by-selection"
            else cls._parse_auto_find_mode_fields(inputs)
        )
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
