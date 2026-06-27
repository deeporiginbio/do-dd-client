"""Constrained molecular docking via the served tools API."""

from __future__ import annotations

import concurrent.futures
from typing import Any, Self

from beartype import beartype

from deeporigin.drug_discovery import align
from deeporigin.drug_discovery.docking_common import (
    build_docking_metadata,
    build_pocket_tool_params,
    load_docking_poses_from_execution,
    resolve_docking_box_geometry,
)
from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import SyncExecutableMixin
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.drug_discovery.utils.visualize import jupyter_visualization
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status

_CONSTRAINT_REQUIRED_KEYS = frozenset({"index", "coordinates", "energy"})


def _constrained_ligand_tool_input_row(lig: Ligand) -> dict[str, Any]:
    """Build one ligand entry for constrained docking (id, smiles, and file_path)."""
    if lig.remote_path is None:
        raise ValueError(
            "Ligand must be synced to the platform with a structure file "
            "(remote_path) for constrained docking. Use Ligand.from_file or "
            "from_sdf and call ligand.sync() before running."
        )
    return {
        "id": lig.id,
        "smiles": lig.smiles,
        "file_path": lig.remote_path,
    }


def _constrained_docking_default_name(protein: Protein, ligand: Ligand) -> str:
    """Build a short human-readable label for a ConstrainedDocking execution."""
    p = protein.name
    if ligand.name is not None and ligand.name.strip():
        lig_label = ligand.name.strip()
    else:
        lig_label = ligand.smiles if ligand.smiles else "unnamed ligand"
    return f"Constrained docking {p} to {lig_label}"


def _validate_explicit_constraints(constraints: list[dict[str, Any]]) -> None:
    """Raise if any constraint entry is missing required keys."""
    if not constraints:
        raise ValueError("constraints must contain at least one entry.")
    for idx, entry in enumerate(constraints):
        missing = sorted(_CONSTRAINT_REQUIRED_KEYS - set(entry.keys()))
        if missing:
            raise ValueError(
                f"Constraint at index {idx} missing required keys: {missing}"
            )


def _ligand_has_3d_structure(ligand: Ligand) -> bool:
    """Return True when the ligand has an RDKit conformer with coordinates."""
    mol = ligand.mol
    return mol is not None and mol.GetNumConformers() > 0


def _constraints_from_reference(
    *,
    ligand: Ligand,
    reference: Ligand,
    constraint_energy: float,
) -> list[dict[str, Any]]:
    """Compute harmonic constraints for *ligand* aligned to *reference* via MCS."""
    if not _ligand_has_3d_structure(ligand):
        raise ValueError(
            "Ligand must have a 3D structure for MCS constraint computation. "
            "Load from SDF/MOL2 or ensure conformers are present."
        )
    if not _ligand_has_3d_structure(reference):
        raise ValueError(
            "Reference ligand must have a 3D structure (e.g. a docked pose). "
            "Download the reference pose or pass a ligand with coordinates."
        )

    mcs_mol = LigandSet(ligands=[ligand, reference]).mcs()
    computed = align.compute_constraints(
        mols=[ligand.mol],
        reference=reference.mol,
        mcs_mol=mcs_mol,
        energy=constraint_energy,
    )
    return computed[0]


class ConstrainedDocking(Execution, SyncExecutableMixin, NotebookWatchMixin):
    """Harmonic constrained docking via ``deeporigin.constrained-docking``.

    Dock exactly one ligand with atom-position constraints. Supply either
    explicit ``constraints`` or a docked ``reference`` ligand; MCS alignment
    derives constraints from the reference pose when ``reference`` is used.

    Execution is synchronous only: call :meth:`run`, or :meth:`run` with
    ``quote=True`` for a cost estimate. There is no async :meth:`start` path for
    this tool.

    Attributes:
        protein: Target protein structure.
        ligand: Ligand to dock (must have a structure file on the platform).
        pocket: Binding pocket defining the docking box.
        constraints: Harmonic constraints sent to the tool.
        effort: Docking effort level (1 = fastest, 5 = most thorough).
        name: Execution label, set automatically unless overridden.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["constrained_docking"]["tool_key"]
    effort: int = 1

    def __init__(
        self,
        *,
        protein: Protein,
        pocket: Pocket,
        ligand: Ligand,
        constraints: list[dict[str, Any]] | None = None,
        reference: Ligand | None = None,
        constraint_energy: float = 5.0,
        effort: int = 1,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["constrained_docking"][
            "tool_version"
        ],
        client: DeepOriginClient | None = None,
        name: str | None = None,
    ) -> None:
        """Create a ConstrainedDocking execution.

        Args:
            protein: Protein structure to dock into.
            pocket: Binding pocket defining the search box.
            ligand: Single ligand to dock. Must be syncable with a structure file.
            constraints: Explicit harmonic constraints. Mutually exclusive with
                ``reference``.
            reference: Reference ligand with 3D coordinates; constraints are
                computed via MCS alignment. Mutually exclusive with
                ``constraints``.
            constraint_energy: Energy weight when deriving constraints from
                ``reference`` (default 5.0).
            effort: Docking effort level (1–5).
            tool_version: Platform tool version for :meth:`run` and :meth:`quote`.
            client: Optional API client.
            name: Optional execution label.
        """
        if (constraints is None) == (reference is None):
            raise ValueError(
                "Exactly one of constraints or reference must be provided."
            )

        if protein.id is None:
            raise ValueError("Protein must have an ID.")

        if not 1 <= effort <= 5:
            raise DeepOriginException(
                f"effort must be between 1 and 5 inclusive, got {effort}"
            ) from None

        if constraints is not None:
            _validate_explicit_constraints(constraints)
            resolved_constraints = constraints
        else:
            assert reference is not None
            resolved_constraints = _constraints_from_reference(
                ligand=ligand,
                reference=reference,
                constraint_energy=constraint_energy,
            )

        super().__init__(client=client)
        self.tool_version = tool_version
        self.effort = effort
        self._protein = protein
        self._pocket = pocket
        self._ligand = ligand
        self._constraints = resolved_constraints
        self._reference = reference
        self.name = (
            name
            if name is not None
            else _constrained_docking_default_name(protein, ligand)
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
    def ligand(self) -> Ligand:
        """Ligand to dock."""
        return self._ligand

    @property
    def constraints(self) -> list[dict[str, Any]]:
        """Harmonic constraints submitted to the tool."""
        return self._constraints

    @property
    def reference(self) -> Ligand | None:
        """Reference ligand used to derive constraints, if any."""
        return self._reference

    def _validate_sync_run_params(self) -> None:
        """Raise if :meth:`run` preconditions are not met."""
        if not 1 <= self.effort <= 5:
            raise DeepOriginException(
                f"effort must be between 1 and 5 inclusive, got {self.effort}"
            ) from None

    def _ensure_platform_inputs(self) -> None:
        """Sync protein and ligand to the data platform with structure files."""
        self.protein.sync(lazy=True, client=self.client)
        self.ligand.sync(lazy=True, client=self.client)
        if self.ligand.remote_path is None:
            raise ValueError(
                "Ligand must have a structure file on the platform for constrained "
                "docking. Load from SDF/MOL2 with Ligand.from_file or from_sdf "
                "and call ligand.sync()."
            )

    def _build_tool_inputs(self) -> tuple[dict[str, Any], dict[str, str]]:
        """Build params and metadata for ``client.executions.create``."""
        pocket_center, box_size = resolve_docking_box_geometry(self.pocket)
        metadata = build_docking_metadata(self.protein)
        pocket_params = build_pocket_tool_params(self.pocket, pocket_center, box_size)

        params: dict[str, Any] = {
            "effort": self.effort,
            "pocket": pocket_params,
            "protein": {
                "id": self.protein.id,
                "file_path": self.protein.remote_path,
            },
            "ligands": [_constrained_ligand_tool_input_row(self.ligand)],
            "constraints": self._constraints,
        }
        return params, metadata

    def _build_create_payload(
        self,
        *,
        approve_amount: int | None = None,
    ) -> dict[str, Any]:
        """Build the body dict for ``client.executions.create``."""
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
        return payload

    def run(
        self,
        *,
        quote: bool = False,
        approve_amount: int | None = None,
    ) -> LigandSet | None:
        """Execute constrained docking synchronously (blocking).

        Args:
            quote: Shorthand for ``approve_amount=0``.
            approve_amount: Spend cap forwarded to the platform as ``approveAmount``.

        Returns:
            A ``LigandSet`` of docked poses, or ``None`` when quoted.

        Raises:
            DeepOriginException: If the execution does not succeed or poses
                could not be loaded.
        """
        self._validate_sync_run_params()
        self._ensure_platform_inputs()
        resolved_amount = 0 if quote else approve_amount
        dto = self._create_execution(
            data=self._build_create_payload(approve_amount=resolved_amount),
        )
        self.update_from_dto(dto)

        if self.status == "Quoted":
            return None

        final_status = dto.get("status")
        if not is_success_status(final_status):
            eid = dto.get("executionId")
            reason = dto.get("statusReason") or final_status
            raise DeepOriginException(
                title="Constrained docking run did not succeed",
                message=(
                    f"Execution {eid!r} ended with status {final_status!r}: {reason!r}."
                ),
            ) from None

        return self.get_results(dto, all_poses=True)

    @classmethod
    def from_dto(
        cls,
        dto: dict,
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct a ConstrainedDocking instance from an execution DTO."""
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
        if len(ligands_input) != 1:
            raise ValueError(
                "Constrained docking requires exactly one ligand in userInputs."
            )

        raw_constraints = inputs.get("constraints")
        if not raw_constraints:
            raise ValueError("Missing 'constraints' in execution userInputs.")

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            fut_protein = executor.submit(
                Protein.from_id,
                protein_id,
                client=instance.client,
                download=False,
                remote_path_override=protein_input.get("file_path"),
            )
            fut_ligand = executor.submit(
                LigandSet.from_ids,
                [ligands_input[0]["id"]],
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
        ligand_set = fut_ligand.result()
        instance._ligand = ligand_set.ligands[0]
        instance._constraints = list(raw_constraints)
        instance._reference = None
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

    @beartype
    def get_results(
        self,
        dto: dict[str, Any] | None = None,
        *,
        all_poses: bool = False,
    ) -> LigandSet:
        """Load docked poses for this execution from the data platform or ``jobOutputs``."""
        return load_docking_poses_from_execution(
            self._ensure_id(),
            client=self.client,
            dto=dto,
            all_poses=all_poses,
        )

    def get_poses(self, *, all_poses: bool = False) -> LigandSet:
        """Download pose SDFs from the platform and return a ``LigandSet``."""
        poses = self.get_results(all_poses=all_poses)
        poses.download(client=self.client, lazy=True)
        return poses

    @jupyter_visualization
    def show_box(self) -> str:
        """Visualize the protein with the docking search box in a Jupyter notebook."""
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
        pocket_center, box_size = resolve_docking_box_geometry(self.pocket)

        from deeporigin_molstar import DockingViewer

        return DockingViewer().render_bounding_box(
            protein_data=protein_file,
            protein_format="pdb",
            box_center=pocket_center,
            box_size=box_size,
        )
