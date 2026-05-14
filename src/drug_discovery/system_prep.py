"""SystemPrep -- sync-only execution for preparing a protein-ligand system for ABFE or RBFE.

Usage (ABFE)::

    sysprep = SystemPrep(protein=protein, ligand=ligand)
    sysprep.run(quote=True)   # populates sysprep.estimate; status == "Quoted"
    prepared = sysprep.run()  # returns PreparedSystem via get_results()
    # Use prepared.binding_xml_path, prepared.solvation_xml_path, etc.
    # Or use sysprep.get_results() after run() to reload one PreparedSystem by execution id.

Usage (RBFE)::

    sysprep = SystemPrep(protein=protein, ligand1=lig1, ligand2=lig2)
    prepared = sysprep.run()
"""

from __future__ import annotations

from typing import Any

from beartype import beartype

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import SyncExecutableMixin
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import SYSPREP_NO_OUTPUT_PATHS_MSG


class SystemPrep(Execution, SyncExecutableMixin):
    """Prepare a protein-ligand system for ABFE or RBFE (sync-only).

    Use either a single ``ligand`` (ABFE) or ``ligand1`` and ``ligand2`` (RBFE).
    Calls ``client.executions.create`` with ``sync=True`` for :meth:`run` to
    produce binding XML, solvation XML, and system PDB. After ``run()``, pass the
    instance to ``ABFE(system=...)`` (ABFE mode) or use the paths for RBFE.

    Attributes:
        protein: Protein structure used for preparation.
        ligand: Convenience alias for :attr:`ligand1` (ABFE callers pass ``ligand=``;
            it is stored as ``ligand1`` internally).
        ligand1: Primary ligand (ABFE) or first ligand of the pair (RBFE).
        ligand2: Second ligand (RBFE only); ``None`` in ABFE mode.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["sysprep"]["tool_key"]

    @beartype
    def __init__(
        self,
        *,
        protein: Protein,
        ligand: Ligand | None = None,
        ligand1: Ligand | None = None,
        ligand2: Ligand | None = None,
        padding: float = 1.0,
        retain_waters: bool = False,
        add_H_atoms: bool = True,  # NOSONAR
        protonate_protein: bool = True,
        box_size: list[float] | None = None,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["sysprep"]["tool_version"],
        client: DeepOriginClient | None = None,
    ) -> None:
        """Create a SystemPrep for ABFE (single ligand) or RBFE (ligand pair).

        Exactly one of (ligand) or (ligand1 and ligand2) must be provided.

        Args:
            protein: Protein structure for system preparation.
            ligand: Single ligand for ABFE. Mutually exclusive with ligand1/ligand2.
            ligand1: First ligand for RBFE. Must be used together with ligand2.
            ligand2: Second ligand for RBFE. Must be used together with ligand1.
            padding: Padding distance in nm around the system. Defaults to 1.0.
            retain_waters: Whether to keep water molecules. Defaults to False.
            add_H_atoms: Whether to add hydrogen atoms to the ligand(s). Defaults to True.
            protonate_protein: Whether to protonate the protein. Defaults to True.
            box_size: Simulation box dimensions (X, Y, Z) in nm. Optional.
            tool_version: Platform tool version. Settable so callers can pin or
                upgrade independently of the SDK release.
            client: Optional API client. Uses the default if not provided.

        Raises:
            ValueError: If neither (ligand) nor (ligand1 and ligand2) is set, or both are set.
            ValueError: If RBFE mode but ligand1 or ligand2 is missing.

        Note:
            Protein and ligand ``id`` values may be unset until :meth:`sync_inputs`
            runs (upload/sync assigns platform ids).
        """
        super().__init__(client=client)
        _abfe_mode = ligand is not None and ligand1 is None and ligand2 is None
        _rbfe_mode = ligand is None and ligand1 is not None and ligand2 is not None
        if not (_abfe_mode or _rbfe_mode):
            raise ValueError(
                "Provide either ligand (ABFE) or both ligand1 and ligand2 (RBFE), "
                "but not both and not only one of ligand1/ligand2."
            )

        if _rbfe_mode and (ligand1 is None or ligand2 is None):
            raise ValueError("ligand1 and ligand2 are required in RBFE mode.")

        self.tool_version = tool_version
        self._protein = protein
        if _abfe_mode:
            assert ligand is not None
            self._ligand1 = ligand
            self._ligand2 = None
        else:
            assert ligand1 is not None and ligand2 is not None
            self._ligand1 = ligand1
            self._ligand2 = ligand2
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
    def ligand(self) -> Ligand:
        """Alias for :attr:`ligand1` (single-ligand ABFE input is stored there)."""
        return self._ligand1

    @property
    def ligand1(self) -> Ligand:
        """Primary ligand (ABFE) or first ligand of the RBFE pair."""
        return self._ligand1

    @property
    def ligand2(self) -> Ligand | None:
        """Second ligand in RBFE mode; ``None`` in ABFE mode."""
        return self._ligand2

    @property
    def padding(self) -> float:
        """Padding distance in nm around the system."""
        return self._padding

    def __repr__(self) -> str:
        """Return a concise summary of this SystemPrep."""
        parts = ["SystemPrep("]
        parts.append(f"  protein_id={self.protein.id!r},")
        parts.append(f"  ligand1_id={self.ligand1.id!r},")
        if self._ligand2 is not None:
            parts.append(f"  ligand2_id={self._ligand2.id!r},")
        parts.append(f"  is_rbfe={self._ligand2 is not None},")
        parts.append(")")
        return "\n".join(parts)

    def sync_inputs(self) -> dict[str, Any]:
        """Sync protein and ligand(s) to the platform and return tool ``inputs``."""
        ligand1 = self._ligand1
        ligand2 = self._ligand2
        protein = self._protein
        client = self.client

        protein.sync(lazy=True, client=client)
        ligand1.sync(lazy=True, client=client)
        if ligand2 is not None:
            ligand2.sync(lazy=True, client=client)

        protein.ensure_remote_path(client=client, label="Protein")
        ligand1.ensure_remote_path(client=client, label="Ligand")
        if ligand2 is not None:
            ligand2.ensure_remote_path(client=client, label="Second ligand")

        if protein.id is None or ligand1.id is None:
            raise ValueError(
                "protein and ligand1 must have an id after sync "
                "(sync or create with id first)."
            )
        if ligand2 is not None and ligand2.id is None:
            raise ValueError(
                "ligand2 must have an id after sync (sync or create with id first)."
            )

        inputs: dict[str, Any] = {
            "protein": {"id": protein.id, "file_path": protein.remote_path},
            "ligand1": {"id": ligand1.id, "file_path": ligand1.remote_path},
            "add_H_atoms": self._add_H_atoms,
            "protonate_protein": self._protonate_protein,
            "retain_waters": self._retain_waters,
            "padding": self._padding,
        }

        if self._box_size is not None:
            inputs["box_size"] = self._box_size

        if ligand2 is not None:
            inputs["ligand2"] = {"id": ligand2.id, "file_path": ligand2.remote_path}

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

    @beartype
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
        dto = self.client.executions.create(  # ty:ignore[unresolved-attribute]
            data=self._build_system_prep_body(
                sync=True, approve_amount=resolved_amount
            ),
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )
        self.update_from_dto(dto)

        if self.status == "Quoted":
            return None

        return self.get_results(dto)
