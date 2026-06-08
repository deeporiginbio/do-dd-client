"""A unified class to perform molecular docking on DeepOrigin."""

import concurrent.futures
from typing import Any, Self

from beartype import beartype
import numpy as np

from deeporigin.drug_discovery.docking_common import (
    build_docking_metadata,
    build_pocket_tool_params,
    load_docking_poses_from_execution,
    resolve_docking_box_geometry,
)
from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import (
    AsyncExecutableMixin,
    SyncExecutableMixin,
)
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.drug_discovery.utils.visualize import jupyter_visualization
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status

Number = float | int


def _ligand_tool_input_row(lig: Ligand) -> dict[str, Any]:
    """Build one ligand entry for tool ``userInputs`` (id and smiles only)."""
    return {"id": lig.id, "smiles": lig.smiles}


def _docking_default_name(protein: Protein, ligands: LigandSet) -> str:
    """Build a short human-readable label for a Docking execution.

    Uses ``protein.name`` and either the ligand count, a single ligand's name, or its SMILES.

    Args:
        protein: Target protein (``name`` is required).
        ligands: Ligands to dock.

    Returns:
        A string such as ``Docking kras to 12 ligands.`` or ``Docking kras to CCO``.
    """
    p = protein.name
    n = len(ligands)
    if n == 0:
        return f"Docking {p} to 0 ligands."
    if n == 1:
        lig = ligands.ligands[0]
        if lig.name is not None and lig.name.strip():
            lig_label = lig.name.strip()
        else:
            lig_label = lig.smiles if lig.smiles else "unnamed ligand"
        return f"Docking {p} to {lig_label}"
    return f"Docking {p} to {n} ligands."


class Docking(Execution, SyncExecutableMixin, AsyncExecutableMixin, NotebookWatchMixin):
    """Molecular docking via the tools API (``client.executions.create``).

    The execution request body includes ``sync`` (``true`` = blocking, ``false`` =
    immediate DTO). :meth:`run` sets ``"sync": true`` for exactly **one** ligand; the
    server blocks until the run finishes and returns the completed execution.
    :meth:`quote` (default ``mode="async"``) and :meth:`start` set ``"sync": false`` (non-blocking).

    :meth:`start` is for multiple ligands only: one ``create`` with all ligands. The
    call **returns immediately** with an execution DTO. For a single ligand, use
    :meth:`run` instead of :meth:`start`. Track async jobs with ``.sync()``,
    ``.wait()``, ``from_id()``, and ``list()``. In Jupyter, use
    ``await docking.watch()`` (see
    :class:`~deeporigin.drug_discovery.notebook_watch_mixin.NotebookWatchMixin`).

    Attributes:
        protein: Target protein structure.
        ligands: Set of ligands to dock.
        pocket: Binding pocket defining the docking box.
        effort: Docking effort level (1 = fastest, 5 = most thorough).
        name: Execution label, set automatically from protein and ligands unless overridden.
        batch_size: For async :meth:`start`, workflow batch size (ligands per workflow
            batch), a positive multiple of 4. Defaults to 16. Sent as ``batchSize`` on
            the execution create payload.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["docking"]["tool_key"]
    effort: int = 1

    def __init__(
        self,
        *,
        protein: Protein,
        pocket: Pocket,
        ligand: Ligand | None = None,
        ligands: LigandSet | None = None,
        smiles_list: list[str] | None = None,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["docking"]["tool_version"],
        effort: int = 1,
        batch_size: int = 16,
        client: DeepOriginClient | None = None,
        name: str | None = None,
    ) -> None:
        """Create a Docking execution.

        Args:
            protein: Protein structure to dock into.
            pocket: Binding pocket defining the search box.
            ligand: Single ligand. Mutually exclusive with ``ligands`` and
                ``smiles_list``. Converted to a ``LigandSet`` during construction.
            ligands: Set of ligands. Mutually exclusive with ``ligand`` and
                ``smiles_list``.
            smiles_list: Raw SMILES strings. Mutually exclusive with ``ligand``
                and ``ligands``. Converted to a ``LigandSet`` during construction.
            tool_version: Platform tool version for :meth:`quote`, :meth:`start`, and
                :meth:`run` (all use ``client.executions.create``).
            effort: Docking effort level (1 = fastest, 5 = most thorough).
                Defaults to :attr:`effort` on the class (3).
            client: Optional API client.
            name: Optional execution label. When omitted, set from ``protein.name``
                and the ligands (e.g. ``Docking kras to 5 ligands.`` or
                ``Docking kras to <SMILES or ligand name>`` for a single ligand).
            batch_size: Passed to the platform as ``batchSize`` on :meth:`start` so the
                docking workflow can batch ligands. Must be a positive multiple of 4.
                Defaults to 16.
        """
        provided = sum(x is not None for x in (ligand, ligands, smiles_list))
        if provided != 1:
            raise ValueError(
                "Exactly one of ligand, ligands, or smiles_list must be provided."
            )

        if protein.id is None:
            raise ValueError("Protein must have an ID.")

        if ligand is not None:
            ligands = LigandSet(ligands=[ligand])
        elif ligands is None and smiles_list is not None:
            ligands = LigandSet.from_smiles(smiles_list)
        assert ligands is not None  # guaranteed by exactly-one-of validation above

        if batch_size <= 0:
            raise ValueError("batch_size must be a positive integer.")
        if batch_size % 4 != 0:
            raise ValueError("batch_size must be a multiple of 4.")
        super().__init__(client=client)
        self.tool_version = tool_version
        self.effort = effort
        self._batch_size = batch_size

        self._protein = protein
        self._pocket = pocket
        self._ligands = ligands

        self.name = (
            name if name is not None else _docking_default_name(protein, ligands)
        )

    @property
    def protein(self) -> Protein:
        """Target protein structure."""
        return self._protein

    @property
    def pocket(self) -> Pocket:
        """Binding pocket defining the docking box."""
        return self._pocket

    @property
    def ligands(self) -> LigandSet:
        """Set of ligands to dock."""
        return self._ligands

    @property
    def batch_size(self) -> int:
        """Workflow batch size for async :meth:`start` (default 16)."""
        return self._batch_size

    def __repr__(self) -> str:
        """Return a concise summary of this docking execution."""
        parts = ["Docking("]

        if self.protein.id is not None:
            parts.append(f"  protein_id={self.protein.id!r},")

        if hasattr(self.pocket, "id") and self.pocket.id is not None:
            parts.append(f"  pocket_id={self.pocket.id!r},")

        vol = self.pocket.volume
        if vol is not None:
            try:
                box_size = float(2 * np.cbrt(vol))
                parts.append(f"  box_size={box_size:.2f},")
            except Exception:
                pass

        try:
            center = self.pocket.get_center().tolist()
            fmt = ", ".join(f"{c:.2f}" for c in center)
            parts.append(f"  center=[{fmt}],")
        except Exception:
            pass

        n = len(self.ligands)
        if n == 1:
            lig = list(self.ligands)[0]
            if lig.id is not None:
                parts.append(f"  ligands=1 (id={lig.id!r}),")
            elif hasattr(lig, "smiles") and lig.smiles:
                parts.append(f"  ligands=1 (smiles={lig.smiles!r}),")
            else:
                parts.append("  ligands=1,")
        else:
            parts.append(f"  ligands={n},")

        parts.append(")")
        return "\n".join(parts)

    def _make_payload(
        self,
        *,
        approve_amount: int | None,
        sync: bool,
    ) -> dict[str, Any]:
        """Build payload for ``executions.create`` (sync or async path)."""
        self._ensure_platform_inputs()
        return self._build_docking_create_payload(
            ligand_set=None,
            approve_amount=approve_amount,
            sync=sync,
        )

    def start(
        self,
        *,
        quote: bool = False,
        approve_amount: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Submit a persisted async execution. Requires at least two ligands.

        For a single ligand, use :meth:`run` instead.

        Args:
            quote: Shorthand for ``approve_amount=0``.
            approve_amount: Spend cap forwarded to the platform.
            **kwargs: Forwarded to ``_start_impl``.
        """
        if len(self.ligands) == 1 and not quote:
            raise ValueError(
                "Cannot start: Docking with a single ligand must use run(), not start()."
            )
        super().start(quote=quote, approve_amount=approve_amount, **kwargs)

    def _validate_sync_run_params(self) -> None:
        """Raise if :meth:`run` preconditions are not met (ligand count, effort)."""
        if len(self.ligands) != 1:
            raise ValueError(
                "run() requires exactly one ligand; use start() for multiple ligands."
            ) from None
        if not 1 <= self.effort <= 5:
            raise DeepOriginException(
                f"effort must be between 1 and 5 inclusive, got {self.effort}"
            ) from None

    def _ensure_inputs_for_sync_run(self) -> None:
        """Validate sync-run parameters and sync protein and ligands for the API."""
        self._validate_sync_run_params()
        self._ensure_platform_inputs()

    def run(
        self,
        *,
        quote: bool = False,
        approve_amount: int | None = None,
    ) -> LigandSet | None:
        """Execute docking synchronously (blocking).

        Submits one synchronous tools execution and returns docked poses from the
        data platform. Requires exactly one ligand in :attr:`ligands`; use
        :meth:`start` for multiple ligands.

        Pass ``quote=True`` (or ``approve_amount=0``) to request a cost estimate
        only. In that case the platform returns a ``Quoted`` DTO, the instance
        is updated with ``estimate`` and ``status="Quoted"``, and ``None`` is
        returned.

        Args:
            quote: Shorthand for ``approve_amount=0``.
            approve_amount: Spend cap forwarded to the platform as ``approveAmount``.

        Returns:
            A ``LigandSet`` of docked poses, or ``None`` when the platform
            responds with ``Quoted`` status.

        Raises:
            ValueError: If :attr:`ligands` does not contain exactly one ligand.
            DeepOriginException: If ``effort`` is outside 1–5, the execution does not
                succeed, or poses could not be loaded.
        """
        self._ensure_inputs_for_sync_run()
        resolved_amount = 0 if quote else approve_amount
        dto = self.client.executions.create(  # ty:ignore[unresolved-attribute]
            data=self._build_docking_create_payload(
                sync=True, approve_amount=resolved_amount
            ),
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )
        self.update_from_dto(dto)

        if self.status == "Quoted":
            return None

        final_status = dto.get("status")
        if not is_success_status(final_status):
            eid = dto.get("executionId")
            reason = dto.get("statusReason") or final_status
            raise DeepOriginException(
                title="Docking run did not succeed",
                message=(
                    f"Execution {eid!r} ended with status {final_status!r}: {reason!r}."
                ),
            ) from None

        return self.get_results(dto, all_poses=True)

    def _start_impl(self, *, approve_amount: int | None = None, **kwargs) -> None:
        """Submit docking as a persisted async execution."""
        self._ensure_platform_inputs()
        payload = self._build_docking_create_payload(
            sync=False, approve_amount=approve_amount
        )

        execution_dto = self.client.executions.create(  # ty:ignore[unresolved-attribute]
            data=payload,
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )
        self._id = execution_dto.get("executionId")
        self.status = execution_dto.get("status")

    def _ensure_platform_inputs(self) -> None:
        """Sync protein and ligands to the data platform.

        Docking tool inputs use only ligand ``id`` and ``smiles`` (see
        :func:`_ligand_tool_input_row`); ligand structure files are not required.
        Mutates remote state so :meth:`_build_tool_inputs` can read IDs and paths.
        """
        self.protein.sync(lazy=True, client=self.client)
        self.ligands.sync(lazy=True, client=self.client)

    def _resolve_docking_box_geometry(self) -> tuple[list[float], list[float]]:
        """Resolve pocket center and box extents used for docking and visualization."""
        return resolve_docking_box_geometry(self.pocket)

    def _build_tool_inputs(
        self, *, ligand_set: LigandSet | None = None
    ) -> tuple[dict, dict]:
        """Build params and metadata for ``client.executions.create``.

        Does not sync or upload; call :meth:`_ensure_platform_inputs` first when
        inputs may not yet exist on the platform.

        Args:
            ligand_set: Ligands to include in tool ``inputs`` (default: all
                :attr:`ligands`). :meth:`run` uses the default set (must be exactly one
                ligand).

        Returns:
            A tuple of (params, metadata).
        """
        to_dock = self.ligands if ligand_set is None else ligand_set
        ligands = list(to_dock)
        pocket_center, box_size = self._resolve_docking_box_geometry()
        metadata = build_docking_metadata(self.protein)
        pocket_params = build_pocket_tool_params(self.pocket, pocket_center, box_size)

        params = {
            "effort": self.effort,
            "pocket": pocket_params,
            "protein": {
                "id": self.protein.id,
                "file_path": self.protein.remote_path,
            },
            "ligands": [_ligand_tool_input_row(lig) for lig in ligands],
        }

        return params, metadata

    def _build_docking_create_payload(
        self,
        *,
        ligand_set: LigandSet | None = None,
        approve_amount: int | None = None,
        sync: bool = False,
    ) -> dict[str, Any]:
        """Build the body dict for ``client.executions.create`` (:meth:`_start_impl`, :meth:`run`).

        Args:
            ligand_set: Subset of ligands for tool ``inputs`` (default: all
                :attr:`ligands`). Omitted by :meth:`run`, which requires a single ligand.
            approve_amount: When not ``None``, sets ``approveAmount`` on the payload.
                Use ``0`` for quoting.
            sync: ``False`` = async (immediate execution DTO). ``True`` = blocking
                response; use only with a **single** ligand in ``inputs.ligands``.
                Nested under ``inputs`` because the docking tool definition
                declares it as an input property; the platform's estimator
                reads ``inputs.sync`` to pick direct serving vs. Argo workflow.
                A top-level ``sync`` would be silently dropped (AJV would fall
                back to the schema default of ``true``).

        Returns:
            DTO for ``client.executions.create`` (``inputs`` -- which carries
            ``sync`` -- ``outputs``, ``metadata``, optional ``name``, optional
            ``approveAmount``, ``batchSize``).
        """
        params, metadata = self._build_tool_inputs(ligand_set=ligand_set)
        params["sync"] = sync
        payload: dict[str, Any] = {
            "inputs": params,
            "outputs": {},
            "metadata": metadata,
        }
        if self.name is not None:
            payload["name"] = self.name
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount
        payload["batchSize"] = self._batch_size
        return payload

    @classmethod
    def from_dto(
        cls,
        dto: dict,
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct a Docking instance from an execution DTO.

        Rehydrates the protein, pocket, and ligands from the stored
        ``userInputs``. Protein and ligand structure files are not downloaded;
        ``Protein.remote_path`` and each ligand's ``remote_path`` are set from
        the execution payload (and API metadata) so you can call
        :meth:`~deeporigin.drug_discovery.structures.entity.Entity.download`
        later if needed.

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client. Uses the default if not provided.

        Returns:
            A fully-hydrated Docking instance with status from the DTO.
        """
        instance = super().from_dto(dto, client=client)
        execution = instance._dto
        if execution is None:
            raise RuntimeError("from_dto did not set _dto")
        inputs = execution.get("userInputs", {})

        pocket_input = inputs.get("pocket", {})
        pocket_id = pocket_input.get("id") or inputs.get("pocket_id")

        protein_input = inputs.get("protein", {})
        protein_id = protein_input.get("id")
        if protein_id is None:
            raise ValueError(
                "Missing 'protein.id' in execution userInputs; "
                "this execution may have been created with an older input schema."
            )

        ligands_input = inputs.get("ligands", [])
        if not ligands_input:
            raise ValueError(
                "Missing 'ligands' in execution userInputs; "
                "this execution may have been created with an older input schema."
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            fut_protein = executor.submit(
                Protein.from_id,
                protein_id,
                client=instance.client,
                download=False,
                remote_path_override=protein_input.get("file_path"),
            )
            fut_ligands = executor.submit(
                LigandSet.from_ids,
                [lig["id"] for lig in ligands_input],
                client=instance.client,
                download=False,
                ligand_inputs=ligands_input,
            )
            if pocket_id is not None:
                fut_pocket = executor.submit(
                    Pocket.from_id,
                    pocket_id,
                    client=instance.client,
                )
            else:
                fut_pocket = None

        instance._protein = fut_protein.result()
        instance._ligands = fut_ligands.result()
        raw_effort = inputs.get("effort")
        instance.effort = int(raw_effort) if raw_effort is not None else cls.effort
        if fut_pocket is not None:
            instance._pocket = fut_pocket.result()
        else:
            instance._pocket = Pocket(
                id=None,
                center=pocket_input.get("center"),
                box_size_x=pocket_input.get("box_size_x"),
                box_size_y=pocket_input.get("box_size_y"),
                box_size_z=pocket_input.get("box_size_z"),
            )

        meta = execution.get("metadata") or {}
        raw_batch = execution.get("batchSize")
        if raw_batch is None:
            raw_batch = meta.get("batchSize")
        try:
            bs = int(raw_batch) if raw_batch is not None else 16
        except (TypeError, ValueError):
            bs = 16
        instance._batch_size = bs if bs > 0 else 16

        return instance

    @beartype
    def get_results(
        self,
        dto: dict[str, Any] | None = None,
        *,
        all_poses: bool = False,
    ) -> LigandSet:
        """Load docked poses for this execution from the data platform or ``jobOutputs``.

        Tries :meth:`~deeporigin.drug_discovery.structures.ligand.LigandSet.from_result`
        first (fast metadata path, no SDF download). On failure, parses
        ``jobOutputs.poses`` from ``dto``, or fetches the execution DTO via
        ``client.executions.get`` when ``dto`` is omitted.

        To convert the result to a DataFrame::

            poses = docking.get_results()
            df = poses.to_dataframe()

        Args:
            dto: Optional execution payload (``executions.create`` /
                ``executions.get``). Passing it avoids an extra GET when the data
                platform path fails but the sync response included ``jobOutputs``.
            all_poses: When ``True``, include every pose instead of only the
                best pose per ligand.

        Returns:
            A ``LigandSet`` of docked poses.

        Raises:
            ValueError: If :attr:`id` is unset.
            DeepOriginException: If no poses could be loaded from the data
                platform or ``jobOutputs``.
        """
        return load_docking_poses_from_execution(
            self._ensure_id(),
            client=self.client,
            dto=dto,
            all_poses=all_poses,
        )

    def get_undocked_ligands(self) -> LigandSet | None:
        """Get a list of ligands that failed to dock.

        Note: we cannot rely on the tool progress report to determine failed ligands,
        because catastrophic tool failures will not update the progress report.

        Returns:
            A ``LigandSet`` of failed ligands, or ``None`` if no failed ligands yet.
        """

        results = self.client.results.get_poses(
            compute_job_id=self.id,
            best_pose=True,
            limit=None,  # important -- pass limit=None to get all results
        )
        results = results["data"]
        docked_ids = {result["data"]["ligand_id"] for result in results}
        all_ids = {ligand.id for ligand in self.ligands}
        missing_ids = all_ids.difference(docked_ids)
        return LigandSet(
            [ligand for ligand in self.ligands if ligand.id in missing_ids]
        )

    def get_poses(self, *, all_poses: bool = False) -> LigandSet:
        """Download pose SDFs from the platform and return a ``LigandSet``.

        Args:
            all_poses: If True, download all poses for each ligand. If False (default),
                download only the best pose per ligand.

        Returns:
            A ``LigandSet`` of docked poses.

        Raises:
            ValueError: If no execution has been started.
            DeepOriginException: If no poses could be loaded.
        """
        poses = self.get_results(all_poses=all_poses)
        poses.download(client=self.client, lazy=True)
        return poses

    @jupyter_visualization
    def show_box(self) -> str:
        """Visualize the protein with the docking search box in a Jupyter notebook.

        Renders the target protein and a wireframe box from :attr:`pocket` center and
        ``box_size_x`` / ``box_size_y`` / ``box_size_z`` (same geometry as
        :meth:`run` and :meth:`start` submit to the docking tool). Requires the
        ``tools`` optional dependency (``deeporigin-molstar``).

        Returns:
            HTML string for the Mol* viewer (wrapped for display by
            :func:`~deeporigin.drug_discovery.utils.visualize.jupyter_visualization`).

        Raises:
            DeepOriginException: If the protein structure cannot be loaded locally.
        """
        if self.protein.structure is None:
            self.protein.download(client=self.client)
        if self.protein.structure is None:
            raise DeepOriginException(
                title="Cannot visualize docking box",
                message=(
                    "Protein structure is not available locally. Download the "
                    "protein or call protein.load_structure_from_local() first."
                ),
            ) from None

        protein_file = self.protein._dump_state()
        pocket_center, box_size = self._resolve_docking_box_geometry()

        from deeporigin_molstar import DockingViewer

        return DockingViewer().render_bounding_box(
            protein_data=protein_file,
            protein_format="pdb",
            box_center=pocket_center,
            box_size=box_size,
        )
