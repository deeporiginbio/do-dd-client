"""Docking -- unified sync + async molecular docking execution.

Usage::

    docking = Docking(protein=protein, ligands=ligands, pocket=pocket)

    # sync (blocking, small sets)
    poses = docking.run()

    # async (persisted, large batches)
    docking.quote()
    docking.start()
    # Jupyter — non-blocking cell (like legacy Job.watch):
    #     task = await docking.watch()
    # Jupyter — block until the job finishes:
    #     await docking.watch_async()
    # Script (blocking): asyncio.run(docking.watch_async())
    docking.sync()
    df = docking.get_results()
    poses = docking.get_poses()
"""

import concurrent.futures
import os
from typing import Any, Self

from beartype import beartype
import numpy as np
import pandas as pd

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import (
    AsyncExecutableMixin,
    QuoteMixin,
    SyncExecutableMixin,
)
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import (
    DOCKING_TOOL_KEY,
    DOCKING_TOOL_VERSION,
)
from deeporigin.utils.constants import DOCKING_RESULTS_DATAFRAME_COLUMNS

Number = float | int


def _ligand_tool_input_row(lig: Ligand) -> dict[str, Any]:
    """Build one ligand entry for tool ``userInputs`` (id and smiles only)."""
    return {"id": lig.id, "smiles": lig.smiles}


@beartype
def _docking_default_name(*, protein: Protein, ligands: LigandSet) -> str:
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
        lig = ligands[0]
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
    """Molecular docking supporting both sync and async execution.

    Sync path (``run()``): uses the functions API for small ligand sets.
    Blocking, no execution ID, not recoverable.

    Async path (``start()``): uses the tools API.
    Creates a persisted execution trackable via ``sync()``, ``from_id()``,
    and ``list()``. In Jupyter, use ``await docking.watch()`` or
    ``await docking.watch_async()`` for live job HTML (see
    :class:`~deeporigin.drug_discovery.notebook_watch_mixin.NotebookWatchMixin`).

    Attributes:
        protein: Target protein structure.
        ligands: Set of ligands to dock.
        pocket: Binding pocket defining the docking box.
        name: Execution label, set automatically from protein and ligands unless overridden.
    """

    tool_key: str = DOCKING_TOOL_KEY

    def __init__(
        self,
        *,
        protein: Protein,
        pocket: Pocket,
        ligand: Ligand | None = None,
        ligands: LigandSet | None = None,
        smiles_list: list[str] | None = None,
        tool_version: str = DOCKING_TOOL_VERSION,
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
            tool_version: Platform tool version to run. Settable so callers
                can pin or upgrade independently of the SDK release.
            client: Optional API client.
            name: Optional execution label. When omitted, set from ``protein.name``
                and the ligands (e.g. ``Docking kras to 5 ligands.`` or
                ``Docking kras to <SMILES or ligand name>`` for a single ligand).
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
        elif ligands is None:
            ligands = LigandSet.from_smiles(smiles_list)

        super().__init__(client=client)
        self.tool_version = tool_version

        self._protein = protein
        self._pocket = pocket
        self._ligands = ligands

        self.name = (
            name
            if name is not None
            else _docking_default_name(protein=protein, ligands=ligands)
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

    def __repr__(self) -> str:
        """Return a concise summary of this docking execution."""
        parts = ["Docking("]

        if self.protein.id is not None:
            parts.append(f"  protein_id={self.protein.id!r},")

        if hasattr(self.pocket, "id") and self.pocket.id is not None:
            parts.append(f"  pocket_id={self.pocket.id!r},")

        try:
            box_size = float(2 * np.cbrt(self.pocket.volume))
            parts.append(f"  box_size={box_size:.2f},")
        except Exception:
            pass

        try:
            center = self.pocket.get_center().tolist()
            fmt = ", ".join(f"{c:.2f}" for c in center)
            parts.append(f"  pocket_center=[{fmt}],")
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

    def _quote_impl(self) -> None:
        """Request a cost estimate for docking.

        Submits an execution with ``approve_amount=0`` to get a quotation
        without running the job. Populates ``self.estimate``.
        """
        from deeporigin.drug_discovery import utils

        params, metadata = self._build_tool_inputs()

        execution_dto = utils._start_tool_run(
            params=params,
            metadata=metadata,
            tool="Docking",
            tool_version=self.tool_version,
            client=self.client,
            approve_amount=0,
        )

        quotation = execution_dto.get("quotationResult", {})
        successful = quotation.get("successfulQuotations", [])
        if successful:
            price = successful[0].get("priceTotal")
            if price is not None:
                self._estimate = float(price)
                self._id = execution_dto.get("executionId")
                self.status = execution_dto.get("status")

    def run(self) -> LigandSet:
        """Execute docking synchronously (blocking).

        Uses the functions API. Suitable for small ligand sets.

        Returns:
            A ``LigandSet`` of docked poses.
        """
        from deeporigin.drug_discovery.structures.protein import (
            _make_poses_from_dock_results,
        )
        from deeporigin.functions.docking import dock as _dock
        from deeporigin.functions.parallel import run_func_in_parallel
        from deeporigin.functions.result import FunctionResult

        client = self.client
        ligands = list(self.ligands)

        args = [
            {
                "protein": self.protein,
                "pocket": self.pocket,
                "ligand": ligand,
                "client": client,
                "quote": False,
            }
            for ligand in ligands
        ]

        data = run_func_in_parallel(func=_dock, args=args)
        individual_results = [r for r in data["results"] if r is not None]
        all_responses = [fr.response for fr in individual_results]

        if not all_responses:
            all_responses = [{"status": "Failed"}]

        result = FunctionResult(all_responses)

        self._id = result.id
        self._cost = result.cost

        execution_ids = [r["id"] for r in result._responses if r.get("id") is not None]
        ids_ok = self.protein.id is not None and all(
            lig.id is not None for lig in ligands
        )
        if ids_ok:
            try:
                all_poses: list[Ligand] = []
                for execution_id in execution_ids:
                    poses_ls = LigandSet.from_docking_result(
                        execution_id=execution_id,
                        client=client,
                    )
                    all_poses.extend(poses_ls.ligands)
                if all_poses:
                    return LigandSet(ligands=all_poses)
            except Exception:
                pass
            import warnings

            warnings.warn(
                "Could not load docking poses from the data platform; "
                "using function response instead. Results may be delayed.",
                stacklevel=2,
            )

        poses = _make_poses_from_dock_results(
            result=result,
            client=client,
        )

        return poses

    def _start_impl(
        self,
        *,
        approve_amount: int | None = None,
    ) -> None:
        """Submit docking as a persisted async execution.

        Args:
            approve_amount: Pre-approved spend amount.
        """

        params, metadata = self._build_tool_inputs()

        payload: dict[str, Any] = {
            "inputs": params,
            "outputs": {},
            "metadata": metadata,
        }
        if self.name is not None:
            payload["name"] = self.name
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount

        execution_dto = self.client.executions.create(
            data=payload,
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )
        self._id = execution_dto.get("executionId")
        self.status = execution_dto.get("status")

    def _build_tool_inputs(self) -> tuple[dict, dict]:
        """Build params and metadata for a tool run.

        Syncs protein and ligands to the platform, then constructs
        the params and metadata passed to ``client.executions.create``.

        Returns:
            A tuple of (params, metadata).
        """
        self.protein.sync(client=self.client)
        if self.ligands is not None:
            self.ligands.sync(client=self.client)

        ligands = list(self.ligands)
        for lig in ligands:
            lig.upload(client=self.client)

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
            "pocket": pocket_params,
            "protein": {
                "id": self.protein.id,
                "file_path": self.protein.remote_path,
            },
            "ligands": [_ligand_tool_input_row(lig) for lig in ligands],
        }

        return params, metadata

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
        inputs = instance._execution_dto["userInputs"]

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
        if fut_pocket is not None:
            instance._pocket = fut_pocket.result()
        else:
            instance._pocket = Pocket(
                id=None,
                pocket_center=pocket_input.get("center"),
                box_size_x=pocket_input.get("box_size_x"),
                box_size_y=pocket_input.get("box_size_y"),
                box_size_z=pocket_input.get("box_size_z"),
            )

        return instance

    @classmethod
    def from_id(
        cls,
        id: str,
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct a Docking instance from an existing platform execution ID.

        Fetches the execution record via the API and delegates to
        :meth:`from_dto`.

        Args:
            id: Platform execution ID.
            client: Optional API client. Uses the default if not provided.

        Returns:
            A fully-hydrated Docking instance with status synced from
            the platform.
        """
        return super().from_id(id, client=client)

    def _list_pose_records(self) -> list[dict[str, Any]]:
        """Return raw pose rows from ``client.results.get_poses`` for this job.

        Returns:
            The ``data`` list from the results API.

        Raises:
            ValueError: If no execution has been started.
        """
        if self.id is None:
            raise ValueError("No execution has been started. Call start() first.")

        response = self.client.results.get_poses(
            compute_job_id=self.id,
            limit=None,
        )
        raw = response.get("data", [])
        return raw if isinstance(raw, list) else []

    def get_results(self) -> pd.DataFrame | None:
        """Retrieve docking results as a table (no structure download).

        Columns: ID, protein ID, ligand ID, pocket ID, binding energy, pose_score.

        Returns:
            A DataFrame with one row per pose record, or ``None`` if the API
            returns no pose rows yet.

        Raises:
            ValueError: If no execution has been started.
        """
        records = self._list_pose_records()
        if not records:
            return None

        rows: list[dict[str, Any]] = []
        for record in records:
            data = record.get("data") or {}
            if not isinstance(data, dict):
                data = {}
            rows.append(
                {
                    "ID": record.get("id"),
                    "protein ID": data.get("protein_id"),
                    "ligand ID": data.get("ligand_id"),
                    "pocket ID": data.get("pocket_id"),
                    "binding energy": data.get("binding_energy"),
                    "pose_score": data.get("pose_score"),
                }
            )

        return pd.DataFrame(rows, columns=list(DOCKING_RESULTS_DATAFRAME_COLUMNS))

    def get_poses(self) -> LigandSet | None:
        """Download pose SDFs from the platform and return a ``LigandSet``.

        Returns:
            A ``LigandSet`` of docked poses, or ``None`` if no pose files yet.

        Raises:
            ValueError: If no execution has been started.
        """
        records = self._list_pose_records()
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

        local_paths = self.client.files.download_many(files=remote_paths, lazy=True)

        result = LigandSet()
        for path in local_paths:
            result.ligands += LigandSet.from_sdf(path).ligands

        return result
