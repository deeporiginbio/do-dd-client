"""A unified class to perform molecular docking on DeepOrigin."""

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
from deeporigin.exceptions import DeepOriginException
from deeporigin.functions.result import FunctionResult
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import (
    DOCKING_FUNCTION_KEY,
    DOCKING_FUNCTION_VERSION,
    DOCKING_TOOL_KEY,
    DOCKING_TOOL_VERSION,
)
from deeporigin.utils.constants import DOCKING_RESULTS_DATAFRAME_COLUMNS

Number = float | int


def _pose_rows_from_result_explorer(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep pose rows from a :meth:`Execution.get_results` result-explorer response.

    ``Result.get`` may return mixed result types for a ``compute_job_id``; docking
    tables only include rows where ``result_type`` is missing (legacy) or ``pose``.

    Args:
        response: Dict with a ``data`` list of result-explorer records.

    Returns:
        Pose records only, in order.
    """
    raw = response.get("data", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for record in raw:
        if not isinstance(record, dict):
            continue
        if record.get("result_type", "pose") != "pose":
            continue
        out.append(record)
    return out


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
        effort: Docking effort level (1 = fastest, 5 = most thorough).
        name: Execution label, set automatically from protein and ligands unless overridden.
    """

    tool_key: str = DOCKING_TOOL_KEY
    effort: int = 3

    def __init__(
        self,
        *,
        protein: Protein,
        pocket: Pocket,
        ligand: Ligand | None = None,
        ligands: LigandSet | None = None,
        smiles_list: list[str] | None = None,
        tool_version: str = DOCKING_TOOL_VERSION,
        effort: int = 3,
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
            effort: Docking effort level (1 = fastest, 5 = most thorough).
                Defaults to :attr:`effort` on the class (3).
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
        elif ligands is None and smiles_list is not None:
            ligands = LigandSet.from_smiles(smiles_list)

        super().__init__(client=client)
        self.tool_version = tool_version
        self.effort = effort

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

        Submits ``approveAmount=0`` via ``executions.create``. Parsing and state
        assignment are handled by
        :meth:`~deeporigin.drug_discovery.execution_mixins.QuoteMixin._quote_apply`.

        Returns:
            Raw execution dictionary from the platform.
        """
        self._ensure_platform_inputs()
        params, metadata = self._build_tool_inputs()

        payload: dict[str, Any] = {
            "inputs": params,
            "outputs": {},
            "metadata": metadata,
        }
        if self.name is not None:
            payload["name"] = self.name
        payload["approveAmount"] = 0

        return self.client.executions.create(
            data=payload,
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )

    def run(self) -> LigandSet:
        """Execute docking synchronously (blocking).

        Uses the functions API. Suitable for small ligand sets.

        Returns:
            A ``LigandSet`` of docked poses.
        """
        if not 1 <= self.effort <= 5:
            raise DeepOriginException(
                f"effort must be between 1 and 5 inclusive, got {self.effort}"
            ) from None

        client = self.client
        protein = self.protein
        pocket = self.pocket
        ligands = list(self.ligands)

        protein.sync(lazy=True, client=client)
        protein.ensure_remote_path(client=client, label="Protein")

        if pocket.center is not None:
            pocket_center = list(pocket.center)
        else:
            pocket_center = pocket.get_center().tolist()

        pocket_data: dict[str, Any] = {
            "center": pocket_center,
            "box_size_x": _docking_pocket_axis_size(pocket, "x"),
            "box_size_y": _docking_pocket_axis_size(pocket, "y"),
            "box_size_z": _docking_pocket_axis_size(pocket, "z"),
        }
        if pocket.id is not None:
            pocket_data["id"] = pocket.id

        protein_data = {"id": protein.id, "file_path": protein.remote_path}

        all_responses: list[dict[str, Any]] = []
        for ligand in ligands:
            ligand.sync(lazy=True, client=client)
            payload = {
                "effort": self.effort,
                "protein": protein_data,
                "ligands": [{"id": ligand.id, "smiles": ligand.smiles}],
                "pocket": pocket_data,
            }
            all_responses.append(
                client.functions.run(
                    key=DOCKING_FUNCTION_KEY,
                    version=DOCKING_FUNCTION_VERSION,
                    params=payload,
                    quote=False,
                )
            )

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

        return LigandSet.from_docking_results(result=result, client=client)

    def _start_impl(
        self,
        *,
        approve_amount: int | None = None,
    ) -> None:
        """Submit docking as a persisted async execution.

        Args:
            approve_amount: Pre-approved spend amount.
        """

        self._ensure_platform_inputs()
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

    def _ensure_platform_inputs(self) -> None:
        """Sync protein and ligands to the data platform.

        Docking tool inputs use only ligand ``id`` and ``smiles`` (see
        :func:`_ligand_tool_input_row`); ligand structure files are not required.
        Mutates remote state so :meth:`_build_tool_inputs` can read IDs and paths.
        """
        self.protein.sync(client=self.client, lazy=True)
        self.ligands.sync(client=self.client, lazy=True)

    def _build_tool_inputs(self) -> tuple[dict, dict]:
        """Build params and metadata for ``client.executions.create``.

        Does not sync or upload; call :meth:`_ensure_platform_inputs` first when
        inputs may not yet exist on the platform.

        Returns:
            A tuple of (params, metadata).
        """
        ligands = list(self.ligands)
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

    def get_results(self) -> pd.DataFrame | None:
        """Retrieve docking results as a table (no structure download).

        Columns: ID, protein ID, ligand ID, pocket ID, binding energy, pose_score,
        best_pose.

        Uses :meth:`~deeporigin.drug_discovery.execution.Execution.get_results` and
        keeps only pose rows.

        Returns:
            A DataFrame with one row per pose record, or ``None`` if the API
            returns no pose rows yet.

        Raises:
            ValueError: If no execution has been started.
        """
        records = _pose_rows_from_result_explorer(super().get_results())
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
                    "best_pose": data.get("best_pose"),
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
        records = _pose_rows_from_result_explorer(super().get_results())
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
