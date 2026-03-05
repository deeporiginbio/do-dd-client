"""Docking -- unified sync + async molecular docking execution.

Usage::

    docking = Docking(protein=protein, ligands=ligands, pocket=pocket)

    # sync (blocking, small sets)
    poses = docking.run()

    # async (persisted, large batches)
    docking.quote()
    docking.start()
    docking.refresh()
    poses = docking.get_results()
"""

import math
import os
from typing import Optional

from beartype import beartype
import numpy as np

from deeporigin.drug_discovery.structures.ligand import LigandSet
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.jobs.base import Execution
from deeporigin.jobs.mixins import (
    AsyncExecutableMixin,
    QuoteMixin,
    SyncExecutableMixin,
)
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import (
    DOCKING_FUNCTION_KEY,
    DOCKING_FUNCTION_VERSION,
    DOCKING_TOOL_KEY,
    DOCKING_TOOL_VERSION,
)

Number = float | int


class Docking(Execution, QuoteMixin, SyncExecutableMixin, AsyncExecutableMixin):
    """Molecular docking supporting both sync and async execution.

    Sync path (``run()``): uses the functions API for small ligand sets.
    Blocking, no execution ID, not recoverable.

    Async path (``start()``): uses the tools API for large batches.
    Creates persisted executions trackable via ``refresh()``, ``from_id()``,
    and ``list()``.

    Attributes:
        protein: Target protein structure.
        ligands: Set of ligands to dock (can be None when ``smiles_list`` is provided).
        pocket: Binding pocket defining the docking box.
        smiles_list: Alternative to ``ligands`` -- raw SMILES strings.
    """

    tool_key: str = DOCKING_TOOL_KEY
    tool_version: str = DOCKING_TOOL_VERSION

    _immutable_fields: frozenset[str] = frozenset(
        {"protein", "ligands", "pocket", "smiles_list"}
    )

    @beartype
    def __init__(
        self,
        *,
        protein: Protein,
        pocket: Pocket,
        ligands: LigandSet | None = None,
        smiles_list: list[str] | None = None,
        batch_size: int = 32,
        client: DeepOriginClient | None = None,
    ) -> None:
        """Create a Docking execution.

        Args:
            protein: Protein structure to dock into.
            pocket: Binding pocket defining the search box.
            ligands: Set of ligands. Mutually exclusive with ``smiles_list``.
            smiles_list: Raw SMILES strings. Mutually exclusive with ``ligands``.
            batch_size: Chunk size for async batching. Defaults to 32.
            client: Optional API client.
        """
        if ligands is None and smiles_list is None:
            raise ValueError("Either ligands or smiles_list must be provided.")

        super().__init__()
        self._init_async()

        with self._system_update():
            self.protein = protein
            self.pocket = pocket
            self.ligands = ligands
            self.smiles_list = smiles_list

        self._batch_size = batch_size
        self._client = client

    def quote(self) -> None:
        """Request a cost estimate for docking.

        Uses the sync functions API with ``quote=True`` to populate
        ``self.estimate``.
        """
        from deeporigin.functions.docking import dock as _dock

        client = self._resolve_client()
        ligands = self._resolve_ligands()

        result = _dock(
            protein=self.protein,
            pocket=self.pocket,
            ligand=ligands[0],
            client=client,
            quote=True,
        )

        per_ligand = result.estimate or 0
        with self._system_update():
            self.estimate = per_ligand * len(ligands)

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

        client = self._resolve_client()
        ligands = self._resolve_ligands()

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

        poses = _make_poses_from_dock_results(
            result=result,
            client=client,
        )

        with self._system_update():
            self.cost = result.cost

        return poses

    @beartype
    def start(
        self,
        *,
        client: DeepOriginClient | None = None,
        n_workers: int | None = None,
        approve_amount: int | None = None,
    ) -> None:
        """Submit docking as a persisted async execution.

        Splits ligands into batches and submits each as a separate
        tool execution. Assigns execution IDs and sets status.

        Args:
            client: Optional API client.
            n_workers: If set, overrides ``batch_size`` to distribute
                ligands across this many workers.
            approve_amount: Pre-approved spend amount.
        """
        from deeporigin.drug_discovery import utils
        from deeporigin.platform.job import Job, JobList

        client = client or self._resolve_client()
        ligands = self._resolve_ligands()

        self.protein.sync(client=client)
        if self.ligands is not None:
            self.ligands.sync(client=client)

        batch_size = self._batch_size
        if n_workers is not None:
            batch_size = math.ceil(len(ligands) / n_workers)

        box_size = float(2 * np.cbrt(self.pocket.volume))
        box_size_list = [box_size, box_size, box_size]
        pocket_center = self.pocket.get_center().tolist()

        output_dir_path = "tool-runs/docking/" + self.protein.to_hash() + "/"

        metadata = {
            "protein_file": os.path.basename(self.protein.file_path),
            "protein_hash": self.protein.to_hash(),
        }

        import more_itertools

        chunks = list(more_itertools.chunked(list(ligands), batch_size))

        jobs = []
        for chunk in chunks:
            params = {
                "box_size": box_size_list,
                "pocket_center": pocket_center,
                "protein": {"file_path": self.protein._remote_path},
                "ligands": [{"smiles": lig.smiles} for lig in chunk],
            }

            if self.protein.id is not None:
                params["protein"]["id"] = self.protein.id

            for i, lig in enumerate(chunk):
                if lig.id is not None:
                    params["ligands"][i]["id"] = lig.id

            if hasattr(self.pocket, "id") and self.pocket.id is not None:
                params["pocket_id"] = self.pocket.id

            execution_dto = utils._start_tool_run(
                params=params,
                metadata=metadata,
                tool="Docking",
                tool_version=self.tool_version,
                client=client,
                output_dir_path=output_dir_path,
                approve_amount=approve_amount,
            )
            jobs.append(Job.from_dto(execution_dto, client=client))

        with self._system_update():
            self._jobs = JobList(jobs)
            if jobs:
                self.id = jobs[0].id
                self.status = jobs[0].status

    @beartype
    def refresh(self, *, client: DeepOriginClient | None = None) -> None:
        """Sync status from the platform for all batch jobs.

        Args:
            client: Optional API client.
        """
        if not hasattr(self, "_jobs") or self._jobs is None:
            super().refresh(client=client)
            return

        self._jobs.sync()
        statuses = self._jobs.status
        with self._system_update():
            if all(s == "Succeeded" for s in statuses):
                self.status = "Succeeded"
            elif any(s == "Failed" for s in statuses.keys() if statuses.get(s, 0) > 0):
                self.status = "Failed"
            elif any(s == "Running" for s in statuses.keys() if statuses.get(s, 0) > 0):
                self.status = "Running"

    def get_results(self) -> LigandSet | None:
        """Retrieve docking results from the platform.

        Downloads result SDF files and returns a ``LigandSet``.

        Returns:
            A ``LigandSet`` of docked poses, or ``None`` if no results yet.
        """
        client = self._resolve_client()

        remote_paths: list[str] = []
        try:
            if self.protein.id is not None:
                response = client.results.get_poses(protein_id=self.protein.id)
                records = response.get("data", [])
                for record in records:
                    data = record.get("data", {})
                    fp = data.get("file_path")
                    if fp:
                        remote_paths.append(fp)
        except Exception:
            pass

        if not remote_paths:
            files = client.files.list_files_in_dir(
                remote_path="tool-runs/docking/" + self.protein.to_hash() + "/",
            )
            remote_paths = [
                f for f in files if f.endswith(".sdf") and "top_results" not in f
            ]

        if not remote_paths:
            return None

        local_paths = client.files.download_files(files=remote_paths, lazy=True)

        result = LigandSet()
        for path in local_paths:
            result.ligands += LigandSet.from_sdf(path).ligands

        return result

    def _resolve_client(self) -> DeepOriginClient:
        """Return the client, falling back to the default singleton."""
        if self._client is not None:
            return self._client
        return DeepOriginClient.get()

    def _resolve_ligands(self) -> list:
        """Return a flat list of Ligand objects from either ligands or smiles_list."""
        if self.ligands is not None:
            return list(self.ligands)

        from deeporigin.drug_discovery.structures.ligand import Ligand

        return [Ligand(smiles=s) for s in self.smiles_list]
