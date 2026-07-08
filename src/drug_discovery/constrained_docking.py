"""Constrained molecular docking via the served tools API."""

from __future__ import annotations

import concurrent.futures
from typing import Any, Self

from beartype import beartype

from deeporigin.drug_discovery.docking_common import (
    build_docking_metadata,
    build_pocket_tool_params,
    load_docking_poses_from_execution,
    load_reference_pose_from_execution,
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


def _constrained_ligand_tool_input_row(lig: Ligand) -> dict[str, Any]:
    """Build one test-ligand entry for constrained docking tool inputs."""
    if lig.remote_path is None:
        raise ValueError(
            "Ligand must be synced to the platform with a structure file "
            "(remote_path) for constrained docking. Use Ligand.from_file or "
            "from_sdf and call ligand.sync() before running."
        )
    row: dict[str, Any] = {
        "id": lig.id,
        "file_path": lig.remote_path,
    }
    if lig.smiles is not None:
        row["smiles"] = lig.smiles
    return row


def _reference_ligand_tool_input_row(lig: Ligand) -> dict[str, Any]:
    """Build the reference.ligand entry for constrained docking tool inputs."""
    if lig.remote_path is None:
        raise ValueError(
            "Reference ligand must be synced to the platform with a structure file "
            "(remote_path). Load from SDF/MOL2 and call reference_ligand.sync()."
        )
    row: dict[str, Any] = {
        "id": lig.id,
        "file_path": lig.remote_path,
    }
    if lig.smiles is not None:
        row["smiles"] = lig.smiles
    return row


def _reference_pose_tool_input_row(lig: Ligand) -> dict[str, Any]:
    """Build the reference.pose entry for constrained docking tool inputs."""
    if lig.remote_path is None:
        raise ValueError(
            "Reference pose must be synced to the platform with a structure file "
            "(remote_path). Load from SDF/MOL2 and call reference_pose.sync()."
        )
    row: dict[str, Any] = {"file_path": lig.remote_path}
    pose_id = lig.properties.get("id")
    if pose_id is not None:
        row["id"] = str(pose_id)
    return row


def _constrained_docking_default_name(protein: Protein, ligands: LigandSet) -> str:
    """Build a short human-readable label for a ConstrainedDocking execution."""
    p = protein.name
    n = len(ligands)
    if n == 0:
        return f"Constrained docking {p} to 0 ligands"
    if n == 1:
        lig = ligands.ligands[0]
        if lig.name is not None and lig.name.strip():
            lig_label = lig.name.strip()
        else:
            lig_label = lig.smiles if lig.smiles else "unnamed ligand"
        return f"Constrained docking {p} to {lig_label}"
    return f"Constrained docking {p} to {n} ligands"


def _ligand_has_3d_structure(ligand: Ligand) -> bool:
    """Return True when the ligand has an RDKit conformer with coordinates."""
    mol = ligand.mol
    return mol is not None and mol.GetNumConformers() > 0


class ConstrainedDocking(
    Execution,
    SyncExecutableMixin,
    AsyncExecutableMixin,
    NotebookWatchMixin,
):
    """Harmonic constrained docking via ``deeporigin.constrained-docking``.

    Dock test ligands using harmonic constraints derived **server-side** from a
    reference ligand pose via MCS alignment. Callers supply
    ``reference_ligand`` (scaffold identity) and ``reference_pose`` (3D
    coordinates); the platform derives per-atom constraints for each test
    ligand.

    :meth:`run` sets ``inputs.sync=true`` for exactly **one** test ligand
    (blocking). :meth:`start` sets ``inputs.sync=false`` for **two or more**
    test ligands (async workflow). Track async jobs with ``.sync()``,
    ``.wait()``, or ``await watch()``.

    Attributes:
        protein: Target protein structure.
        ligands: Test ligands to constrain-dock.
        pocket: Binding pocket defining the docking box.
        reference_ligand: Template ligand identity for MCS constraint derivation.
        reference_pose: Required 3D reference pose SDF used for constraints.
        constraint_energy: Harmonic constraint weight sent to the tool.
        effort: Docking effort level (1 = fastest, 5 = most thorough).
        name: Execution label, set automatically unless overridden.
        batch_size: Workflow batch size for async :meth:`start` (default 8).
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["constrained_docking"]["tool_key"]
    effort: int = 1

    def __init__(
        self,
        *,
        protein: Protein,
        pocket: Pocket,
        reference_ligand: Ligand,
        reference_pose: Ligand,
        ligand: Ligand | None = None,
        ligands: LigandSet | None = None,
        constraint_energy: float = 5.0,
        mcs_smarts: str | None = None,
        mcs_smiles: str | None = None,
        effort: int = 1,
        batch_size: int = 8,
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
            reference_ligand: Reference/template ligand entity for MCS alignment.
            reference_pose: Required 3D pose SDF for constraint derivation.
            ligand: Single test ligand. Mutually exclusive with ``ligands``.
            ligands: Set of test ligands. Mutually exclusive with ``ligand``.
            constraint_energy: Harmonic constraint weight (default 5.0).
            mcs_smarts: Optional SMARTS override for the common scaffold.
            mcs_smiles: Optional SMILES override for the common scaffold.
            effort: Docking effort level (1–5).
            batch_size: Workflow batch size for async :meth:`start` (default 8).
            tool_version: Platform tool version for execution create calls.
            client: Optional API client.
            name: Optional execution label.
        """
        provided = sum(x is not None for x in (ligand, ligands))
        if provided != 1:
            raise ValueError("Exactly one of ligand or ligands must be provided.")

        if mcs_smarts is not None and mcs_smiles is not None:
            raise ValueError("mcs_smarts and mcs_smiles are mutually exclusive.")

        if protein.id is None:
            raise ValueError("Protein must have an ID.")

        if not _ligand_has_3d_structure(reference_pose):
            raise ValueError(
                "reference_pose must have a 3D structure (e.g. a docked pose SDF). "
                "Load from SDF/MOL2 or download from a prior Docking.run()."
            )

        if not 1 <= effort <= 5:
            raise DeepOriginException(
                f"effort must be between 1 and 5 inclusive, got {effort}"
            ) from None

        if batch_size <= 0:
            raise ValueError("batch_size must be a positive integer.")

        if ligand is not None:
            ligands = LigandSet(ligands=[ligand])
        assert ligands is not None

        super().__init__(client=client)
        self.tool_version = tool_version
        self.effort = effort
        self._batch_size = batch_size
        self._protein = protein
        self._pocket = pocket
        self._reference_ligand = reference_ligand
        self._reference_pose = reference_pose
        self._ligands = ligands
        self._constraint_energy = constraint_energy
        self._mcs_smarts = mcs_smarts
        self._mcs_smiles = mcs_smiles
        self.name = (
            name
            if name is not None
            else _constrained_docking_default_name(protein, ligands)
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
    def reference_ligand(self) -> Ligand:
        """Reference/template ligand used for MCS constraint derivation."""
        return self._reference_ligand

    @property
    def reference_pose(self) -> Ligand:
        """Required 3D reference pose submitted to the tool."""
        return self._reference_pose

    @property
    def ligands(self) -> LigandSet:
        """Test ligands to constrain-dock."""
        return self._ligands

    @property
    def ligand(self) -> Ligand:
        """Single test ligand when exactly one was provided."""
        if len(self._ligands) != 1:
            raise ValueError(
                "ligand property is only available when exactly one test ligand "
                "was provided; use ligands instead."
            )
        return self._ligands.ligands[0]

    @property
    def constraint_energy(self) -> float:
        """Harmonic constraint energy weight sent to the tool."""
        return self._constraint_energy

    @property
    def mcs_smarts(self) -> str | None:
        """Optional SMARTS override for the common scaffold."""
        return self._mcs_smarts

    @property
    def mcs_smiles(self) -> str | None:
        """Optional SMILES override for the common scaffold."""
        return self._mcs_smiles

    @property
    def batch_size(self) -> int:
        """Workflow batch size for async :meth:`start` (default 8)."""
        return self._batch_size

    def start(
        self,
        *,
        quote: bool = False,
        approve_amount: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Submit a persisted async execution. Requires at least two test ligands.

        For a single test ligand, use :meth:`run` instead.

        Args:
            quote: Shorthand for ``approve_amount=0``.
            approve_amount: Spend cap forwarded to the platform.
            **kwargs: Forwarded to ``_start_impl``.
        """
        if len(self.ligands) == 1 and not quote:
            raise ValueError(
                "Cannot start: ConstrainedDocking with a single test ligand must "
                "use run(), not start()."
            )
        super().start(quote=quote, approve_amount=approve_amount, **kwargs)

    def _validate_sync_run_params(self) -> None:
        """Raise if :meth:`run` preconditions are not met."""
        if len(self.ligands) != 1:
            raise ValueError(
                "run() requires exactly one test ligand; use start() for multiple."
            ) from None
        if not 1 <= self.effort <= 5:
            raise DeepOriginException(
                f"effort must be between 1 and 5 inclusive, got {self.effort}"
            ) from None

    def _ensure_platform_inputs(self) -> None:
        """Sync protein, reference entities, and test ligands to the platform."""
        self.protein.sync(lazy=True, client=self.client)
        self.reference_ligand.sync(lazy=True, client=self.client)
        if self.reference_pose.properties.get("id") is None:
            self.reference_pose.sync(lazy=True, client=self.client)
        self.ligands.sync(lazy=True, client=self.client)

        if self.reference_ligand.remote_path is None:
            raise ValueError(
                "reference_ligand must have a structure file on the platform."
            )
        if self.reference_pose.remote_path is None:
            raise ValueError(
                "reference_pose must have a structure file on the platform."
            )
        for lig in self.ligands:
            if lig.remote_path is None:
                raise ValueError(
                    "Each test ligand must have a structure file on the platform "
                    "for constrained docking."
                )

    def _build_tool_inputs(
        self,
        *,
        ligand_set: LigandSet | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Build params and metadata for ``client.executions.create``."""
        to_dock = self.ligands if ligand_set is None else ligand_set
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
            "reference": {
                "ligand": _reference_ligand_tool_input_row(self.reference_ligand),
                "pose": _reference_pose_tool_input_row(self.reference_pose),
            },
            "ligands": [_constrained_ligand_tool_input_row(lig) for lig in to_dock],
            "constraint_energy": self.constraint_energy,
        }
        if self.mcs_smarts is not None:
            params["mcs_smarts"] = self.mcs_smarts
        if self.mcs_smiles is not None:
            params["mcs_smiles"] = self.mcs_smiles
        return params, metadata

    def _build_create_payload(
        self,
        *,
        approve_amount: int | None = None,
        sync: bool = False,
    ) -> dict[str, Any]:
        """Build the body dict for ``client.executions.create``."""
        params, metadata = self._build_tool_inputs()
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
            data=self._build_create_payload(
                approve_amount=resolved_amount,
                sync=True,
            ),
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

    def _start_impl(self, *, approve_amount: int | None = None, **kwargs: Any) -> None:
        """Submit constrained docking as a persisted async execution."""
        self._ensure_platform_inputs()
        payload = self._build_create_payload(
            approve_amount=approve_amount,
            sync=False,
        )
        execution_dto = self._create_execution(data=payload)
        self._id = execution_dto.get("executionId")
        self.status = execution_dto.get("status")

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

        reference_input = inputs.get("reference", {})
        ref_ligand_input = reference_input.get("ligand", {})
        ref_pose_input = dict(reference_input.get("pose", {}))
        if not ref_ligand_input:
            raise ValueError(
                "Missing 'reference.ligand' in execution userInputs; "
                "this execution may have been created with an older input schema."
            )
        if not ref_pose_input:
            raise ValueError(
                "Missing 'reference.pose' in execution userInputs; "
                "this execution may have been created with an older input schema."
            )
        if "smiles" not in ref_pose_input and ref_ligand_input.get("smiles"):
            ref_pose_input["smiles"] = ref_ligand_input["smiles"]

        ligands_input = inputs.get("ligands", [])
        if not ligands_input:
            raise ValueError("Missing 'ligands' in execution userInputs.")

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            fut_protein = executor.submit(
                Protein.from_id,
                protein_id,
                client=instance.client,
                download=False,
                remote_path_override=protein_input.get("file_path"),
            )
            fut_ref_ligand = executor.submit(
                LigandSet.from_ids,
                [ref_ligand_input["id"]],
                client=instance.client,
                download=False,
                ligand_inputs=[ref_ligand_input],
            )
            fut_ref_pose = executor.submit(
                LigandSet.from_json,
                [ref_pose_input],
                client=instance.client,
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
        instance._reference_ligand = fut_ref_ligand.result().ligands[0]
        instance._reference_pose = fut_ref_pose.result().ligands[0]
        instance._ligands = fut_ligands.result()
        raw_effort = inputs.get("effort")
        instance.effort = int(raw_effort) if raw_effort is not None else cls.effort
        instance._constraint_energy = float(
            inputs.get("constraint_energy", 5.0),
        )
        instance._mcs_smarts = inputs.get("mcs_smarts")
        instance._mcs_smiles = inputs.get("mcs_smiles")
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
            bs = int(raw_batch) if raw_batch is not None else 8
        except (TypeError, ValueError):
            bs = 8
        instance._batch_size = bs if bs > 0 else 8

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

    @beartype
    def get_reference_pose(
        self,
        dto: dict[str, Any] | None = None,
    ) -> Ligand:
        """Load the reference pose reported by this execution.

        Args:
            dto: Optional execution payload to avoid an extra GET.

        Returns:
            The reference pose as a :class:`Ligand`.
        """
        return load_reference_pose_from_execution(
            self._ensure_id(),
            client=self.client,
            dto=dto,
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
