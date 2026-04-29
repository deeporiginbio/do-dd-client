"""SystemPrep -- sync-only execution for preparing a protein-ligand system for ABFE or RBFE.

Usage (ABFE)::

    sysprep = SystemPrep(protein=protein, ligand=ligand)
    sysprep.quote()
    prepared = sysprep.run()   # returns PreparedSystem
    # Use prepared.binding_xml_path, prepared.solvation_xml_path, etc.
    # Or use sysprep.get_results() after run() to reload from the platform by execution id.

Usage (RBFE)::

    sysprep = SystemPrep(protein=protein, ligand1=lig1, ligand2=lig2)
    sysprep.quote()
    prepared = sysprep.run()
"""

from __future__ import annotations

from typing import Any

from beartype import beartype

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_helpers import price_total_from_execution_dto
from deeporigin.drug_discovery.execution_mixins import QuoteMixin, SyncExecutableMixin
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import SYSPREP_NO_OUTPUT_PATHS_MSG


def _build_sysprep_payload(
    *,
    protein: Protein,
    ligand1: Ligand,
    ligand2: Ligand | None,
    padding: float,
    retain_waters: bool,
    add_H_atoms: bool,  # NOSONAR
    protonate_protein: bool,
    box_size: list[float] | None,
    client: DeepOriginClient,
) -> dict:
    """Build and upload inputs, returning the payload dict for a sysprep call."""
    protein.sync(lazy=True, client=client)
    ligand1.sync(lazy=True, client=client)
    if ligand2 is not None:
        ligand2.sync(lazy=True, client=client)

    protein.ensure_remote_path(client=client, label="Protein")
    ligand1.ensure_remote_path(client=client, label="Ligand")
    if ligand2 is not None:
        ligand2.ensure_remote_path(client=client, label="Second ligand")

    payload: dict = {
        "protein": {"id": protein.id, "file_path": protein.remote_path},
        "ligand1": {"id": ligand1.id, "file_path": ligand1.remote_path},
        "add_H_atoms": add_H_atoms,
        "protonate_protein": protonate_protein,
        "retain_waters": retain_waters,
        "padding": padding,
    }

    if box_size is not None:
        payload["box_size"] = box_size

    if ligand2 is not None:
        payload["ligand2"] = {"id": ligand2.id, "file_path": ligand2.remote_path}

    return payload


class SystemPrep(Execution, QuoteMixin, SyncExecutableMixin):
    """Prepare a protein-ligand system for ABFE or RBFE (sync-only).

    Use either a single ``ligand`` (ABFE) or ``ligand1`` and ``ligand2`` (RBFE).
    Calls ``client.executions.create`` with ``sync=True`` for :meth:`run` to
    produce binding XML, solvation XML, and system PDB. After ``run()``, pass the
    instance to ``ABFE(system=...)`` (ABFE mode) or use the paths for RBFE.

    Attributes:
        protein: Protein structure used for preparation.
        ligand: Ligand used for preparation (ABFE mode only).
        ligand1: First ligand (RBFE mode only).
        ligand2: Second ligand (RBFE mode only).
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
            protein: Protein structure for system preparation. Must have ``id`` set.
            ligand: Single ligand for ABFE. Mutually exclusive with ligand1/ligand2.
                Must have ``id`` set.
            ligand1: First ligand for RBFE. Must be used together with ligand2.
                Must have ``id`` set.
            ligand2: Second ligand for RBFE. Must be used together with ligand1.
                Must have ``id`` set.
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
            ValueError: If protein or the relevant ligand(s) do not have an ``id`` set.
        """
        super().__init__(client=client)
        _abfe_mode = ligand is not None and ligand1 is None and ligand2 is None
        _rbfe_mode = ligand is None and ligand1 is not None and ligand2 is not None
        if not (_abfe_mode or _rbfe_mode):
            raise ValueError(
                "Provide either ligand (ABFE) or both ligand1 and ligand2 (RBFE), "
                "but not both and not only one of ligand1/ligand2."
            )

        if protein.id is None:
            raise ValueError(
                "protein must have an id set (sync or create with id first)."
            )
        if _abfe_mode and ligand is not None and ligand.id is None:
            raise ValueError(
                "ligand must have an id set (sync or create with id first)."
            )
        if _rbfe_mode:
            if ligand1 is None or ligand2 is None:
                raise ValueError("ligand1 and ligand2 are required in RBFE mode.")
            if ligand1.id is None or ligand2.id is None:
                raise ValueError(
                    "ligand1 and ligand2 must have an id set (sync or create with id first)."
                )

        self.tool_version = tool_version
        self._protein = protein
        self._ligand = ligand
        self._ligand1 = ligand1
        self._ligand2 = ligand2
        self._is_rbfe = _rbfe_mode
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
    def ligand(self) -> Ligand | None:
        """Ligand used for preparation (ABFE mode). None in RBFE mode."""
        return self._ligand

    @property
    def ligand1(self) -> Ligand | None:
        """First ligand (RBFE mode). None in ABFE mode."""
        return self._ligand1

    @property
    def ligand2(self) -> Ligand | None:
        """Second ligand (RBFE mode). None in ABFE mode."""
        return self._ligand2

    @property
    def padding(self) -> float:
        """Padding distance in nm around the system."""
        return self._padding

    def __repr__(self) -> str:
        """Return a concise summary of this SystemPrep."""
        parts = ["SystemPrep("]
        parts.append(f"  protein_id={self.protein.id!r},")
        if self._is_rbfe:
            parts.append(f"  ligand1_id={self.ligand1.id!r},")
            parts.append(f"  ligand2_id={self.ligand2.id!r},")
        else:
            parts.append(f"  ligand_id={self.ligand.id!r},")
        parts.append(f"  is_rbfe={self._is_rbfe},")
        parts.append(")")
        return "\n".join(parts)

    def _ligand_ids(self) -> tuple[str, str | None]:
        """Return (ligand1_id, ligand2_id). IDs are always set by constructor."""
        if self._is_rbfe:
            return (self.ligand1.id, self.ligand2.id)
        return (self.ligand.id, None)

    def _sysprep_inputs(self) -> dict[str, Any]:
        """Build tool ``inputs`` for system preparation."""
        if self._is_rbfe:
            return _build_sysprep_payload(
                protein=self._protein,
                ligand1=self._ligand1,
                ligand2=self._ligand2,
                padding=self._padding,
                retain_waters=self._retain_waters,
                add_H_atoms=self._add_H_atoms,
                protonate_protein=self._protonate_protein,
                box_size=self._box_size,
                client=self.client,
            )
        return _build_sysprep_payload(
            protein=self._protein,
            ligand1=self._ligand,
            ligand2=None,
            padding=self._padding,
            retain_waters=self._retain_waters,
            add_H_atoms=self._add_H_atoms,
            protonate_protein=self._protonate_protein,
            box_size=self._box_size,
            client=self.client,
        )

    def _make_payload(
        self, *, sync: bool, approve_amount: int | None
    ) -> dict[str, Any]:
        """Build the POST body for ``executions.create``."""
        body: dict[str, Any] = {
            "inputs": self._sysprep_inputs(),
            "outputs": {},
            "metadata": {},
            "sync": sync,
        }
        if approve_amount is not None:
            body["approveAmount"] = approve_amount
        return body

    def _get_quote(self) -> dict[str, Any]:
        """Return the tools API execution DTO for a quotation (``approveAmount=0``)."""
        return self.client.executions.create(  # ty:ignore[union-attr]
            data=self._make_payload(sync=False, approve_amount=0),
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )

    def run(self) -> PreparedSystem:
        """Execute system preparation (blocking).

        Calls ``client.executions.create`` with ``sync=True`` (ABFE or RBFE path),
        parses the response, and returns a ``PreparedSystem`` with output paths and
        metadata. To fetch previously computed systems without re-running, use
        :meth:`get_results`.

        Returns:
            A PreparedSystem with the output paths and metadata.

        Raises:
            ValueError: If the execution did not return usable output paths.
        """
        dto = self.client.executions.create(  # ty:ignore[unresolved-attribute]
            data=self._make_payload(sync=True, approve_amount=None),
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )
        execution_id = dto.get("executionId")
        if not execution_id:
            raise ValueError(
                "System prep run failed: tools execution create did not return "
                "an executionId."
            )
        self._id = execution_id
        if dto.get("status") == "Succeeded":
            price = price_total_from_execution_dto(dto)
            if price is not None:
                self._cost = price

        client = self.client
        ligand1_id, ligand2_id = self._ligand_ids()
        ids_ok = (
            self.protein.id is not None
            and ligand1_id is not None
            and (not self._is_rbfe or ligand2_id is not None)
        )

        if ids_ok:
            try:
                response = client.results.get_prepared_systems(
                    compute_job_id=execution_id,
                )
                records = response.get("data", [])
                if not records:
                    raise ValueError(
                        "No prepared-system result found for this execution."
                    )
                return PreparedSystem._from_record(records[0])
            except Exception:
                import warnings

                warnings.warn(
                    "Could not load prepared system from the data platform; "
                    "using execution outputs if present. Results may be delayed.",
                    stacklevel=2,
                )

        prepared = self._prepared_system_from_execution_dto(dto)
        if prepared is not None:
            return prepared

        raise ValueError(SYSPREP_NO_OUTPUT_PATHS_MSG)

    def _prepared_system_from_execution_dto(
        self, dto: dict[str, Any]
    ) -> PreparedSystem | None:
        """Build ``PreparedSystem`` from execution output blobs, if present."""
        for key in ("jobOutputs", "userOutputs", "functionOutputs"):
            block = dto.get(key)
            if not isinstance(block, dict):
                continue
            system = block.get("system")
            prepared = SystemPrep._prepared_system_from_system_dict(
                system,
                protein_id=self.protein.id,
                ligand1_id=self._ligand_ids()[0],
                ligand2_id=self._ligand_ids()[1],
                padding=self._padding,
                add_H_atoms=self._add_H_atoms,
                retain_waters=self._retain_waters,
                protonate_protein=self._protonate_protein,
            )
            if prepared is not None:
                return prepared
        return None

    @staticmethod
    def _prepared_system_from_system_dict(
        system: object,
        *,
        protein_id: str | None,
        ligand1_id: str | None,
        ligand2_id: str | None,
        padding: float,
        add_H_atoms: bool,
        retain_waters: bool,
        protonate_protein: bool,
    ) -> PreparedSystem | None:
        """Return a ``PreparedSystem`` if *system* dict contains required paths."""
        if not isinstance(system, dict):
            return None
        binding_xml_path = system.get("binding_xml_file_path")
        solvation_xml_path = system.get("solvation_xml_ligand_file_path")
        system_pdb_path = system.get("system_pdb_file_path")
        solute_pdb_path = system.get("solute_pdb_file_path")
        if not (binding_xml_path and solvation_xml_path and system_pdb_path):
            return None
        return PreparedSystem(
            binding_xml_path=binding_xml_path,
            solvation_xml_path=solvation_xml_path,
            system_pdb_path=system_pdb_path,
            solute_pdb_path=solute_pdb_path,
            protein_id=protein_id,
            ligand1_id=ligand1_id,
            ligand2_id=ligand2_id,
            padding=padding,
            add_H_atoms=add_H_atoms,
            retain_waters=retain_waters,
            protonate_protein=protonate_protein,
        )

    def get_results(self) -> list[PreparedSystem]:
        """Load prepared-system result records for this execution from the platform.

        Calls :meth:`~deeporigin.drug_discovery.execution.Execution.get_results` (same
        result-explorer response as other executions), then builds
        :class:`PreparedSystem` from each row that contains the required output paths.

        Uses the platform execution :attr:`~deeporigin.drug_discovery.execution_mixins.QuoteMixin.id`
        (compute job id) set by :meth:`run`.

        Returns:
            One or more :class:`PreparedSystem` instances from the results API for
            this execution.

        Raises:
            ValueError: If :attr:`id` is unset (see :meth:`~deeporigin.drug_discovery.execution.Execution.get_results`),
                if the API returns no rows for this execution id, or if no rows parse as
                a prepared system.
        """
        response = super().get_results()
        records = response.get("data", [])
        if not records:
            raise ValueError("No prepared-system results found for this execution id.")
        out: list[PreparedSystem] = []
        for record in records:
            try:
                out.append(PreparedSystem._from_record(record))
            except ValueError:
                continue
        if not out:
            raise ValueError("No valid prepared-system records for this execution id.")
        return out


@beartype
def for_abfe(
    *,
    protein: Protein,
    ligand: Ligand,
    padding: float = 1.0,
    retain_waters: bool = False,
    add_H_atoms: bool = True,  # NOSONAR
    protonate_protein: bool = True,
    box_size: list[float] | None = None,
    client: DeepOriginClient,
    quote: bool = False,
    tool_version: str = TOOL_KEYS_AND_VERSIONS["sysprep"]["tool_version"],
) -> dict[str, Any]:
    """Run ABFE system preparation via ``client.executions.create`` (low-level helper).

    Unlike :class:`SystemPrep`, this does not require platform entity IDs on
    ``protein`` / ``ligand`` before the call; inputs are synced in
    :func:`_build_sysprep_payload`.

    Args:
        tool_version: Tool manifest version for the executions URL segment.

    Returns:
        Raw execution DTO from the tools API.
    """
    inputs = _build_sysprep_payload(
        protein=protein,
        ligand1=ligand,
        ligand2=None,
        padding=padding,
        retain_waters=retain_waters,
        add_H_atoms=add_H_atoms,
        protonate_protein=protonate_protein,
        box_size=box_size,
        client=client,
    )
    body: dict[str, Any] = {
        "inputs": inputs,
        "outputs": {},
        "metadata": {},
        "sync": False if quote else True,
    }
    if quote:
        body["approveAmount"] = 0
    return client.executions.create(  # ty:ignore[union-attr]
        data=body,
        tool_key=TOOL_KEYS_AND_VERSIONS["sysprep"]["tool_key"],
        tool_version=tool_version,
    )


@beartype
def for_rbfe(
    *,
    protein: Protein,
    ligand1: Ligand,
    ligand2: Ligand,
    padding: float = 1.0,
    retain_waters: bool = False,
    add_H_atoms: bool = True,  # NOSONAR
    protonate_protein: bool = True,
    box_size: list[float] | None = None,
    client: DeepOriginClient,
    quote: bool = False,
    tool_version: str = TOOL_KEYS_AND_VERSIONS["sysprep"]["tool_version"],
) -> dict[str, Any]:
    """Run RBFE system preparation via ``client.executions.create`` (low-level helper).

    Args:
        tool_version: Tool manifest version for the executions URL segment.

    Returns:
        Raw execution DTO from the tools API.
    """
    inputs = _build_sysprep_payload(
        protein=protein,
        ligand1=ligand1,
        ligand2=ligand2,
        padding=padding,
        retain_waters=retain_waters,
        add_H_atoms=add_H_atoms,
        protonate_protein=protonate_protein,
        box_size=box_size,
        client=client,
    )
    body: dict[str, Any] = {
        "inputs": inputs,
        "outputs": {},
        "metadata": {},
        "sync": False if quote else True,
    }
    if quote:
        body["approveAmount"] = 0
    return client.executions.create(  # ty:ignore[union-attr]
        data=body,
        tool_key=TOOL_KEYS_AND_VERSIONS["sysprep"]["tool_key"],
        tool_version=tool_version,
    )
