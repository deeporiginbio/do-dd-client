"""A unified class to perform molecular docking on DeepOrigin."""

import concurrent.futures
import os
from typing import Any, Protocol, Self, cast

from beartype import beartype
import numpy as np

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import (
    AsyncExecutableMixin,
    QuoteMixin,
    SyncExecutableMixin,
)
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.entity import Entity
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS

Number = float | int


class _SupportsEntitySync(Protocol):
    """Structural type for :meth:`Entity.sync` (avoids confusion with execution ``sync()``)."""

    def sync(
        self,
        *,
        lazy: bool = False,
        client: DeepOriginClient | None = None,
        remote_path: str | None = None,
    ) -> None: ...


class _SupportsLigandSetSync(Protocol):
    """Structural type for :meth:`LigandSet.sync`."""

    def sync(
        self,
        *,
        lazy: bool = False,
        client: DeepOriginClient | None = None,
    ) -> None: ...


def _sync_entity(
    entity: Entity,
    *,
    lazy: bool = False,
    client: DeepOriginClient,
) -> None:
    """Call :meth:`Entity.sync` on *entity*.

    ``Docking`` also inherits ``AsyncExecutableMixin.sync(self)``, so attribute
    access to ``sync`` on nested entities can confuse static analysis; cast via
    :class:`_SupportsEntitySync` so the checker uses the entity API signature.
    """
    cast(_SupportsEntitySync, entity).sync(lazy=lazy, client=client)


def _sync_ligand_set(
    ligands: LigandSet,
    *,
    lazy: bool = False,
    client: DeepOriginClient,
) -> None:
    """Call :meth:`LigandSet.sync` for the same reason as :func:`_sync_entity`."""
    cast(_SupportsLigandSetSync, ligands).sync(lazy=lazy, client=client)


def _ensure_entity_remote_path(
    entity: Entity,
    *,
    client: DeepOriginClient,
    label: str,
) -> None:
    """Call :meth:`Entity.ensure_remote_path` without MRO ambiguity."""
    Entity.ensure_remote_path(entity, client=client, label=label)


def _ligand_tool_input_row(lig: Ligand) -> dict[str, Any]:
    """Build one ligand entry for tool ``userInputs`` (id and smiles only)."""
    return {"id": lig.id, "smiles": lig.smiles}


def _docking_pocket_axis_size(pocket: Pocket, axis: str) -> float:
    """Return box size for *axis* on *pocket*, defaulting to 20.0 Å."""
    val = getattr(pocket, f"box_size_{axis}", None)
    if val is not None:
        return float(val)
    return 20.0


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


@beartype
class Docking(
    Execution, QuoteMixin, SyncExecutableMixin, AsyncExecutableMixin, NotebookWatchMixin
):
    """Molecular docking via the tools API (``client.executions.create``).

    The execution request body includes ``sync`` (``true`` = blocking, ``false`` =
    immediate DTO). :meth:`run` sets ``"sync": true`` for exactly **one** ligand; the
    server blocks until the run finishes and returns the completed execution.
    :meth:`quote` and :meth:`start` set ``"sync": false`` (non-blocking).

    :meth:`start` is for multiple ligands only: one ``create`` with all ligands. The
    call **returns immediately** with an execution DTO. For a single ligand, use
    :meth:`run` instead of :meth:`start`. Track async jobs with ``.sync()``,
    ``from_id()``, and ``list()``. In Jupyter, use
    ``await docking.watch()`` or ``await docking.watch_async()`` (see
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

    def _get_quote(self) -> dict[str, Any]:
        """Build the docking quote payload and return the tools API execution DTO.

        Submits ``approveAmount=0`` and ``batchSize`` via ``executions.create`` (same
        as :meth:`_start_impl` for batching). Parsing and state assignment are handled
        by :meth:`~deeporigin.drug_discovery.execution_mixins.QuoteMixin._quote_apply`.

        Returns:
            Raw execution dictionary from the platform.
        """
        self._ensure_platform_inputs()
        payload = self._make_payload(approve_amount=0, sync=False)

        return self.client.executions.create(  # ty:ignore[union-attr]
            data=payload,
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )

    def start(self, **kwargs: Any) -> None:  # type: ignore[override]
        """Submit a persisted async execution. Requires at least two ligands.

        For a single ligand, use :meth:`run` instead.
        """
        if len(self.ligands) == 1:
            raise ValueError(
                "Cannot start: Docking with a single ligand must use run(), not start()."
            )
        super().start(**kwargs)

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

    def run(self) -> LigandSet:
        """Execute docking synchronously (blocking).

        Submits one synchronous tools execution and returns docked poses from the
        data platform. Requires exactly one ligand in :attr:`ligands`; use
        :meth:`start` for multiple ligands.

        Returns:
            A ``LigandSet`` of docked poses.

        Raises:
            ValueError: If :attr:`ligands` does not contain exactly one ligand.
            DeepOriginException: If ``effort`` is outside 1–5, the execution does not
                succeed, or poses could not be loaded.
        """
        self._ensure_inputs_for_sync_run()
        dto = self.client.executions.create(  # ty:ignore[unresolved-attribute]
            data=self._make_payload(sync=True),
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )
        self.update_from_dto(dto)

        final_status = dto.get("status")
        if final_status != "Succeeded":
            eid = dto.get("executionId")
            reason = dto.get("statusReason") or final_status
            raise DeepOriginException(
                title="Docking run did not succeed",
                message=(
                    f"Execution {eid!r} ended with status {final_status!r}: {reason!r}."
                ),
            ) from None

        # returning all poses because we are running a sync tool
        return self.get_results(dto, all_poses=True)

    def _start_impl(self, **kwargs) -> None:
        """Submit docking as a persisted async execution."""
        self._ensure_platform_inputs()
        payload = self._make_payload(sync=False)

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
        _sync_entity(self.protein, client=self.client, lazy=True)
        _sync_ligand_set(self.ligands, client=self.client, lazy=True)

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
        default_box = float(2 * np.cbrt(self.pocket.volume or 0))
        box_size_x = (
            self.pocket.box_size_x
            if self.pocket.box_size_x is not None
            else default_box
        )
        box_size_y = (
            self.pocket.box_size_y
            if self.pocket.box_size_y is not None
            else default_box
        )
        box_size_z = (
            self.pocket.box_size_z
            if self.pocket.box_size_z is not None
            else default_box
        )
        pocket_center = self.pocket.get_center().tolist()

        protein_ref = self.protein.local_path or self.protein.remote_path
        protein_hash = ""
        if self.protein.structure is not None:
            protein_hash = self.protein.to_hash()
        metadata = {
            "protein_file": os.path.basename(str(protein_ref)) if protein_ref else "",
            "protein_hash": protein_hash,
        }

        pocket_params = {
            "box_size_x": box_size_x,
            "box_size_y": box_size_y,
            "box_size_z": box_size_z,
            "center": pocket_center,
        }
        if self.pocket.id is not None:
            pocket_params["id"] = self.pocket.id

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

    def _make_payload(
        self,
        *,
        ligand_set: LigandSet | None = None,
        approve_amount: int | None = None,
        sync: bool = False,
    ) -> dict[str, Any]:
        """Build the body dict for :meth:`_get_quote`, :meth:`_start_impl`, and :meth:`run`.

        Args:
            ligand_set: Subset of ligands for tool ``inputs`` (default: all
                :attr:`ligands`). Omitted by :meth:`run`, which requires a single ligand.
            approve_amount: When not ``None``, sets ``approveAmount`` on the payload.
                Use ``0`` for quoting.
            sync: ``False`` = async (immediate execution DTO). ``True`` = blocking
                response; use only with a **single** ligand in ``inputs.ligands``.

        Returns:
            DTO for ``client.executions.create`` (``inputs``, ``outputs``, ``metadata``,
            ``sync``, optional ``name``, optional ``approveAmount``, ``batchSize``).
        """
        params, metadata = self._build_tool_inputs(ligand_set=ligand_set)
        payload: dict[str, Any] = {
            "inputs": params,
            "outputs": {},
            "metadata": metadata,
            "sync": sync,
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
        execution = instance._execution_dto
        if execution is None:
            raise RuntimeError("from_dto did not set _execution_dto")
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
        exec_id = self._ensure_id()

        best_pose: bool | None = None if all_poses else True

        try:
            return LigandSet.from_result(
                execution_id=exec_id,
                best_pose=best_pose,
                client=self.client,
            )
        except Exception:
            # we can still potentially get results from the jobOutputs
            pass

        try:
            if dto is None:
                dto = self.client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
            jo = dto.get("jobOutputs")
            raw = jo.get("poses", []) if isinstance(jo, dict) else []
            return LigandSet.from_json(raw, client=self.client)
        except Exception as exc:
            raise DeepOriginException(
                title="Could not load docking poses",
                message=(
                    "No poses could be parsed from the data platform or jobOutputs."
                ),
            ) from exc

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

    def get_poses(self, *, all_poses: bool = False) -> LigandSet | None:
        """Download pose SDFs from the platform and return a ``LigandSet``.

        Args:
            all_poses: If True, download all poses for each ligand. If False (default),
                download only the best pose per ligand.

        Returns:
            A ``LigandSet`` of docked poses, or ``None`` if no pose files yet.

        Raises:
            ValueError: If no execution has been started.
        """
        filter_dict = None if all_poses else {"best_pose": {"eq": True}}
        response = super().get_results(filter_dict=filter_dict, limit=None)
        records = response.get("data", [])
        remote_paths: list[str] = []
        for record in records:
            data = record.get("data", {})
            if not isinstance(data, dict):
                continue
            fp = data.get("file_path")
            if fp:
                remote_paths.append(fp)

        if not remote_paths:
            return None

        paths_by_remote = self.client.files.download_many(files=remote_paths, lazy=True)

        result = LigandSet()
        for rp in remote_paths:
            result.ligands += LigandSet.from_sdf(paths_by_remote[rp]).ligands

        return result
