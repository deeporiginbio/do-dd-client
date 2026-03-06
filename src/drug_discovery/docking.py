"""Docking -- unified sync + async molecular docking execution.

Usage::

    docking = Docking(protein=protein, ligands=ligands, pocket=pocket)

    # sync (blocking, small sets)
    poses = docking.run()

    # async (persisted, large batches)
    docking.quote()
    docking.start()
    docking.sync()
    poses = docking.get_results()
"""

import os
from typing import Self

from beartype import beartype
import numpy as np

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import (
    AsyncExecutableMixin,
    QuoteMixin,
    SyncExecutableMixin,
)
from deeporigin.drug_discovery.structures.ligand import LigandSet
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import (
    DOCKING_TOOL_KEY,
    DOCKING_TOOL_VERSION,
)

Number = float | int


class Docking(Execution, QuoteMixin, SyncExecutableMixin, AsyncExecutableMixin):
    """Molecular docking supporting both sync and async execution.

    Sync path (``run()``): uses the functions API for small ligand sets.
    Blocking, no execution ID, not recoverable.

    Async path (``start()``): uses the tools API.
    Creates a persisted execution trackable via ``sync()``, ``from_id()``,
    and ``list()``.

    Attributes:
        protein: Target protein structure.
        ligands: Set of ligands to dock.
        pocket: Binding pocket defining the docking box.
    """

    tool_key: str = DOCKING_TOOL_KEY

    @beartype
    def __init__(
        self,
        *,
        protein: Protein,
        pocket: Pocket,
        ligands: LigandSet | None = None,
        smiles_list: list[str] | None = None,
        tool_version: str = DOCKING_TOOL_VERSION,
        client: DeepOriginClient | None = None,
    ) -> None:
        """Create a Docking execution.

        Args:
            protein: Protein structure to dock into.
            pocket: Binding pocket defining the search box.
            ligands: Set of ligands. Mutually exclusive with ``smiles_list``.
            smiles_list: Raw SMILES strings. Mutually exclusive with ``ligands``.
                Converted to a ``LigandSet`` during construction.
            tool_version: Platform tool version to run. Settable so callers
                can pin or upgrade independently of the SDK release.
            client: Optional API client.
        """

        if ligands is None and smiles_list is None:
            raise ValueError("Either ligands or smiles_list must be provided.")

        if protein.id is None:
            raise ValueError("Protein must have an ID.")

        if pocket.id is None:
            raise ValueError("Pocket must have an ID.")

        if ligands is None:
            ligands = LigandSet.from_smiles(smiles_list)

        for ligand in ligands:
            if ligand.id is None:
                raise ValueError("Ligands must have an ID.")

        super().__init__(client=client)
        self.tool_version = tool_version

        self._protein = protein
        self._pocket = pocket
        self._ligands = ligands

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

    def quote(self) -> None:
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

        poses = _make_poses_from_dock_results(
            result=result,
            client=client,
        )

        self._cost = result.cost

        return poses

    @beartype
    def start(
        self,
        *,
        approve_amount: int | None = None,
    ) -> None:
        """Submit docking as a persisted async execution.

        Args:
            approve_amount: Pre-approved spend amount.
        """
        from deeporigin.drug_discovery import utils
        from deeporigin.platform.job import Job

        params, metadata = self._build_tool_inputs()

        execution_dto = utils._start_tool_run(
            params=params,
            metadata=metadata,
            tool="Docking",
            tool_version=self.tool_version,
            client=self.client,
            approve_amount=approve_amount,
        )

        job = Job.from_dto(execution_dto, client=self.client)
        self._id = job.id
        self.status = job.status

    def _build_tool_inputs(self) -> tuple[dict, dict]:
        """Build params and metadata for a tool run.

        Syncs protein and ligands to the platform, then constructs
        the payload dicts needed by ``_start_tool_run``.

        Returns:
            A tuple of (params, metadata).
        """
        self.protein.sync(client=self.client)
        if self.ligands is not None:
            self.ligands.sync(client=self.client)

        ligands = list(self.ligands)

        box_size = float(2 * np.cbrt(self.pocket.volume))
        box_size_list = [box_size, box_size, box_size]
        pocket_center = self.pocket.get_center().tolist()

        metadata = {
            "protein_file": os.path.basename(self.protein.file_path),
            "protein_hash": self.protein.to_hash(),
        }

        params = {
            "box_size": box_size_list,
            "pocket_center": pocket_center,
            "protein": {
                "id": self.protein.id,
                "file_path": self.protein._remote_path,
            },
            "ligands": [
                {
                    "id": lig.id,
                    "smiles": lig.smiles,
                }
                for lig in ligands
            ],
        }

        if self.protein.id is not None:
            params["protein"]["id"] = self.protein.id

        for i, lig in enumerate(ligands):
            if lig.id is not None:
                params["ligands"][i]["id"] = lig.id

        if hasattr(self.pocket, "id") and self.pocket.id is not None:
            params["pocket_id"] = self.pocket.id

        return params, metadata

    @classmethod
    def from_id(
        cls,
        id: str,
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct a Docking instance from an existing platform execution ID.

        Fetches the execution record and rehydrates the protein, pocket,
        and ligands from the stored ``userInputs``.

        Args:
            id: Platform execution ID.
            client: Optional API client. Uses the default if not provided.

        Returns:
            A fully-hydrated Docking instance with status synced from
            the platform.
        """
        instance = super().from_id(id, client=client)
        inputs = instance._execution_dto["userInputs"]

        instance._protein = Protein.from_id(
            inputs["protein"]["id"],
            client=instance.client,
        )
        instance._ligands = LigandSet.from_ids(
            [lig["id"] for lig in inputs["ligands"]],
            client=instance.client,
        )
        instance._pocket = Pocket.from_id(
            inputs["pocket_id"],
            client=instance.client,
        )

        return instance

    def get_results(self) -> LigandSet | None:
        """Retrieve docking results from the platform.

        Downloads result SDF files and returns a ``LigandSet``.

        Returns:
            A ``LigandSet`` of docked poses, or ``None`` if no results yet.
        """
        response = self.client.results.get_poses(protein_id=self.protein.id)
        records = response.get("data", [])
        remote_paths: list[str] = []
        for record in records:
            data = record.get("data", {})
            fp = data.get("file_path")
            if fp:
                remote_paths.append(fp)

        if not remote_paths:
            return None

        local_paths = self.client.files.download_files(files=remote_paths, lazy=True)

        result = LigandSet()
        for path in local_paths:
            result.ligands += LigandSet.from_sdf(path).ligands

        return result
