"""SystemPrep -- sync-only execution for preparing a protein-pose system for ABFE or RBFE.

Usage (ABFE)::

    sysprep = SystemPrep(protein=protein, pose=pose)
    sysprep.run(quote=True)   # populates sysprep.estimate; status == "Quoted"
    prepared = sysprep.run()  # returns PreparedSystem via get_results()
    # Use prepared.binding_xml_path, prepared.solvation_xml_path, etc.
    # Or use sysprep.get_results() after run() to reload one PreparedSystem by execution id.

Usage (RBFE)::

    sysprep = SystemPrep(protein=protein, pose1=pose_a, pose2=pose_b)
    prepared = sysprep.run()
"""

from __future__ import annotations

from typing import Any

from beartype import beartype

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import SyncExecutableMixin
from deeporigin.drug_discovery.fep_common import _pose_tool_ref
from deeporigin.drug_discovery.structures.pose import Pose
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import SYSPREP_NO_OUTPUT_PATHS_MSG


class SystemPrep(Execution, SyncExecutableMixin):
    """Prepare a protein-pose system for ABFE or RBFE (sync-only).

    Use either a single ``pose`` (ABFE) or ``pose1`` and ``pose2`` (RBFE).
    Calls ``client.executions.create`` with ``sync=True`` for :meth:`run` to
    produce binding XML, solvation XML, and system PDB. After ``run()``, pass the
    instance to ``ABFE(system=...)`` (ABFE mode) or use the paths for RBFE.

    Attributes:
        protein: Protein structure used for preparation.
        pose: Convenience alias for :attr:`pose1` (ABFE callers pass ``pose=``;
            it is stored as ``pose1`` internally).
        pose1: Primary pose (ABFE) or first pose of the pair (RBFE).
        pose2: Second pose (RBFE only); ``None`` in ABFE mode.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["sysprep"]["tool_key"]

    def __init__(
        self,
        *,
        protein: Protein,
        pose: Pose | None = None,
        pose1: Pose | None = None,
        pose2: Pose | None = None,
        padding: float = 1.0,
        retain_waters: bool = False,
        add_H_atoms: bool = True,  # NOSONAR
        protonate_protein: bool = True,
        box_size: list[float] | None = None,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["sysprep"]["tool_version"],
        client: DeepOriginClient | None = None,
    ) -> None:
        """Create a SystemPrep for ABFE (single pose) or RBFE (pose pair).

        Exactly one of (pose) or (pose1 and pose2) must be provided.

        Args:
            protein: Protein structure for system preparation.
            pose: Single pose for ABFE. Mutually exclusive with pose1/pose2.
            pose1: First pose for RBFE. Must be used together with pose2.
            pose2: Second pose for RBFE. Must be used together with pose1.
            padding: Padding distance in nm around the system. Defaults to 1.0.
            retain_waters: Whether to keep water molecules. Defaults to False.
            add_H_atoms: Whether to add hydrogen atoms to the pose(s). Defaults to True.
            protonate_protein: Whether to protonate the protein. Defaults to True.
            box_size: Simulation box dimensions (X, Y, Z) in nm. Optional.
            tool_version: Platform tool version. Settable so callers can pin or
                upgrade independently of the SDK release.
            client: Optional API client. Uses the default if not provided.

        Raises:
            ValueError: If neither (pose) nor (pose1 and pose2) is set, or both are set.
            ValueError: If RBFE mode but pose1 or pose2 is missing.

        Note:
            Protein and pose ``id`` values may be unset until :meth:`sync_inputs`
            runs (upload/sync assigns platform ids).
        """
        super().__init__(client=client)
        _abfe_mode = pose is not None and pose1 is None and pose2 is None
        _rbfe_mode = pose is None and pose1 is not None and pose2 is not None
        if not (_abfe_mode or _rbfe_mode):
            raise ValueError(
                "Provide either pose (ABFE) or both pose1 and pose2 (RBFE), "
                "but not both and not only one of pose1/pose2."
            )

        self.tool_version = tool_version
        self._protein = protein
        if _abfe_mode:
            assert pose is not None
            self._pose1 = pose
            self._pose2 = None
        else:
            self._pose1 = pose1
            self._pose2 = pose2
        self._padding = padding
        self._retain_waters = retain_waters
        self._add_H_atoms = add_H_atoms
        self._protonate_protein = protonate_protein
        self._box_size = box_size

    @property
    def protein(self) -> Protein:
        """Protein structure used for preparation."""
        return self._protein

    @property
    def pose(self) -> Pose:
        """Alias for :attr:`pose1` (single-pose ABFE input is stored there)."""
        return self._pose1

    @property
    def pose1(self) -> Pose:
        """Primary pose (ABFE) or first pose of the RBFE pair."""
        return self._pose1

    @property
    def pose2(self) -> Pose | None:
        """Second pose in RBFE mode; ``None`` in ABFE mode."""
        return self._pose2

    @property
    def padding(self) -> float:
        """Padding distance in nm around the system."""
        return self._padding

    def __repr__(self) -> str:
        """Return a concise summary of this SystemPrep."""
        parts = ["SystemPrep("]
        parts.append(f"  protein_id={self.protein.id!r},")
        parts.append(f"  pose1_id={self.pose1.id!r},")
        if self._pose2 is not None:
            parts.append(f"  pose2_id={self._pose2.id!r},")
        parts.append(f"  is_rbfe={self._pose2 is not None},")
        parts.append(")")
        return "\n".join(parts)

    def sync_inputs(self) -> dict[str, Any]:
        """Sync protein and pose(s) to the platform and return tool ``inputs``."""
        pose1 = self._pose1
        pose2 = self._pose2
        protein = self._protein
        client = self.client

        protein.sync(lazy=True, client=client)
        pose1.sync(lazy=True, client=client)
        if pose2 is not None:
            pose2.sync(lazy=True, client=client)

        protein.ensure_remote_path(client=client, label="Protein")
        pose1.ensure_remote_path(client=client, label="Pose")
        if pose2 is not None:
            pose2.ensure_remote_path(client=client, label="Second pose")

        if protein.id is None:
            raise ValueError(
                "protein must have an id after sync (sync or create with id first)."
            )

        inputs: dict[str, Any] = {
            "protein": {"id": protein.id, "file_path": protein.remote_path},
            "pose1": _pose_tool_ref(pose1),
            "add_H_atoms": self._add_H_atoms,
            "protonate_protein": self._protonate_protein,
            "retain_waters": self._retain_waters,
            "padding": self._padding,
        }

        if self._box_size is not None:
            inputs["box_size"] = self._box_size

        if pose2 is not None:
            inputs["pose2"] = _pose_tool_ref(pose2)

        return inputs

    def _build_system_prep_body(
        self,
        *,
        sync: bool = True,
        approve_amount: int | None = None,
    ) -> dict[str, Any]:
        """Build the POST body for ``executions.create``."""
        inputs = self.sync_inputs()
        body: dict[str, Any] = {
            "inputs": inputs,
            "outputs": {},
            "metadata": {},
            "sync": sync,
        }
        if approve_amount is not None:
            body["approveAmount"] = approve_amount
        return body

    def _make_payload(
        self,
        *,
        approve_amount: int | None,
        sync: bool,
    ) -> dict[str, Any]:
        """Build the POST body for system-prep ``executions.create``."""
        return self._build_system_prep_body(
            sync=sync,
            approve_amount=approve_amount,
        )

    @beartype
    def get_results(self, dto: dict[str, Any] | None = None) -> PreparedSystem:
        """Load a ``PreparedSystem`` from the data platform or ``jobOutputs``.

        Tries :meth:`~deeporigin.drug_discovery.structures.prepared_system.PreparedSystem.from_result`
        first (same explorer rows as ``client.results.get_prepared_systems``). On
        failure or empty rows, parses ``jobOutputs.system`` from ``dto``, or from
        ``client.executions.get`` when ``dto`` is omitted (for example after
        :meth:`~deeporigin.drug_discovery.execution.Execution.from_id`).

        Args:
            dto: Optional execution payload (``executions.create`` /
                ``executions.get``). Passing it avoids an extra GET when the data
                platform path fails but the sync response included ``jobOutputs``.

        Returns:
            A single :class:`PreparedSystem` for this execution.

        Raises:
            ValueError: If :attr:`id` is unset, or if no usable output paths could
                be resolved (same message as a failed sync :meth:`run`).
        """
        exec_id = getattr(self, "_id", None)
        if exec_id is None:
            raise ValueError(
                "Cannot get results: no execution has been started (id is None)."
            )

        try:
            systems = PreparedSystem.from_result(
                compute_job_id=self.id,
                client=self.client,
            )
            if systems:
                return systems[0]
        except Exception:
            pass

        exec_dto: dict[str, Any] | None = dto
        if exec_dto is None:
            exec_dto = self.client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
        if exec_dto is None:
            raise ValueError(SYSPREP_NO_OUTPUT_PATHS_MSG)

        try:
            jo = exec_dto.get("jobOutputs")
            if isinstance(jo, dict):
                system = jo.get("system")
                if isinstance(system, dict):
                    return PreparedSystem.from_json(system)
        except ValueError:
            pass

        raise ValueError(SYSPREP_NO_OUTPUT_PATHS_MSG)

    def run(
        self,
        *,
        quote: bool = False,
        approve_amount: int | None = None,
    ) -> PreparedSystem | None:
        """Execute system preparation (blocking).

        Calls ``client.executions.create`` with ``sync=True`` (ABFE or RBFE
        path), refreshes instance state from the DTO, then returns a
        ``PreparedSystem`` via :meth:`get_results`.

        Pass ``quote=True`` (or ``approve_amount=0``) to request a cost
        estimate only. In that case the platform returns a ``Quoted`` DTO, the
        instance is updated with ``estimate`` and ``status="Quoted"``, and
        ``None`` is returned.

        Args:
            quote: Shorthand for ``approve_amount=0``.
            approve_amount: Spend cap forwarded to the platform as ``approveAmount``.

        Returns:
            A ``PreparedSystem`` with the output paths and metadata, or ``None``
            when the platform responds with ``Quoted`` status.

        Raises:
            ValueError: If the execution did not return usable output paths.
        """
        resolved_amount = 0 if quote else approve_amount
        dto = self._create_execution(
            data=self._build_system_prep_body(
                sync=True, approve_amount=resolved_amount
            ),
        )
        self.update_from_dto(dto)

        if self.status == "Quoted":
            return None

        return self.get_results(dto)
