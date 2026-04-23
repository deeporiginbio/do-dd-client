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
from deeporigin.drug_discovery.execution_mixins import QuoteMixin, SyncExecutableMixin
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.drug_discovery.sync_function_responses import SyncFunctionResponses
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
    Calls the platform system-prep function to produce binding XML,
    solvation XML, and system PDB. After ``run()``, pass the instance to
    ``ABFE(system=...)`` (ABFE mode) or use the paths for RBFE.

    This is a blocking operation. It does **not** create a persisted
    execution record on the platform.

    Attributes:
        protein: Protein structure used for preparation.
        ligand: Ligand used for preparation (ABFE mode only).
        ligand1: First ligand (RBFE mode only).
        ligand2: Second ligand (RBFE mode only).
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["sysprep"]["function_key"]

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
        tool_version: str = TOOL_KEYS_AND_VERSIONS["sysprep"]["function_version"],
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
            tool_version: Platform function version. Settable so callers can pin or
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

    def _get_quote(self) -> dict[str, Any]:
        """Call the functions API with ``quote=True`` and return the raw response."""
        if self._is_rbfe:
            payload = _build_sysprep_payload(
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
        else:
            payload = _build_sysprep_payload(
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
        return self.client.functions.run(
            key=TOOL_KEYS_AND_VERSIONS["sysprep"]["function_key"],
            version=self.tool_version,
            params=payload,
            quote=True,
        )

    def _quote_impl(self) -> None:
        """Request a cost estimate using the functions API quotation payload."""
        dto = self._get_quote()
        wrapped = SyncFunctionResponses([dto])
        if wrapped.estimate is None:
            raise RuntimeError(
                "Quote failed: no estimate could be parsed from the system-prep response."
            )
        self._estimate = wrapped.estimate

    def run(self) -> PreparedSystem:
        """Execute system preparation (blocking).

        Calls the platform system-prep function (ABFE or RBFE path), parses the
        response, and returns a ``PreparedSystem`` with output paths and metadata.
        To fetch previously computed systems without re-running, use
        :meth:`get_results`.

        Returns:
            A PreparedSystem with the output paths and metadata.

        Raises:
            ValueError: If the function run did not return output paths.
        """
        if self._is_rbfe:
            payload = _build_sysprep_payload(
                protein=self.protein,
                ligand1=self.ligand1,
                ligand2=self.ligand2,
                padding=self._padding,
                retain_waters=self._retain_waters,
                add_H_atoms=self._add_H_atoms,
                protonate_protein=self._protonate_protein,
                box_size=self._box_size,
                client=self.client,
            )
        else:
            payload = _build_sysprep_payload(
                protein=self.protein,
                ligand1=self.ligand,
                ligand2=None,
                padding=self._padding,
                retain_waters=self._retain_waters,
                add_H_atoms=self._add_H_atoms,
                protonate_protein=self._protonate_protein,
                box_size=self._box_size,
                client=self.client,
            )

        raw = self.client.functions.run(
            key=TOOL_KEYS_AND_VERSIONS["sysprep"]["function_key"],
            version=self.tool_version,
            params=payload,
            quote=False,
        )
        result = SyncFunctionResponses([raw])

        if result.cost is not None:
            self._cost = result.cost

        execution_id = result.responses[0]["id"]
        self._id = execution_id
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
                    "using function response instead. Results may be delayed.",
                    stacklevel=2,
                )

        if not result.function_outputs:
            raise ValueError(SYSPREP_NO_OUTPUT_PATHS_MSG)

        outputs = result.function_outputs[0]
        system = outputs.get("system")
        if system is None:
            raise ValueError(SYSPREP_NO_OUTPUT_PATHS_MSG)
        binding_xml_path: str | None = None
        solvation_xml_path: str | None = None
        system_pdb_path: str | None = None
        solute_pdb_path: str | None = None
        if isinstance(system, dict):
            binding_xml_path = system.get("binding_xml_file_path")
            solvation_xml_path = system.get("solvation_xml_ligand_file_path")
            system_pdb_path = system.get("system_pdb_file_path")
            solute_pdb_path = system.get("solute_pdb_file_path")

        if not (binding_xml_path and solvation_xml_path and system_pdb_path):
            raise ValueError(SYSPREP_NO_OUTPUT_PATHS_MSG)

        return PreparedSystem(
            binding_xml_path=binding_xml_path,
            solvation_xml_path=solvation_xml_path,
            system_pdb_path=system_pdb_path,
            solute_pdb_path=solute_pdb_path,
            protein_id=self.protein.id,
            ligand1_id=self._ligand_ids()[0],
            ligand2_id=self._ligand_ids()[1],
            padding=self._padding,
            add_H_atoms=self._add_H_atoms,
            retain_waters=self._retain_waters,
            protonate_protein=self._protonate_protein,
        )

    def get_results(self) -> list[PreparedSystem]:
        """Load prepared-system result records for this execution from the platform.

        Calls :meth:`~deeporigin.drug_discovery.execution.Execution.get_results` (same
        result-explorer response as other executions), then builds
        :class:`PreparedSystem` from each row that contains the required output paths.

        Uses the platform execution :attr:`~deeporigin.drug_discovery.execution_mixins.QuoteMixin.id`
        (function execution / compute job id) set by :meth:`run`.

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
) -> SyncFunctionResponses:
    """Run ABFE system preparation via ``functions.run`` (low-level helper).

    Unlike :class:`SystemPrep`, this does not require platform entity IDs on
    ``protein`` / ``ligand`` before the call; inputs are synced in
    :func:`_build_sysprep_payload`.
    """
    payload = _build_sysprep_payload(
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
    raw = client.functions.run(
        key=TOOL_KEYS_AND_VERSIONS["sysprep"]["function_key"],
        version=TOOL_KEYS_AND_VERSIONS["sysprep"]["function_version"],
        params=payload,
        quote=quote,
    )
    return SyncFunctionResponses([raw])


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
) -> SyncFunctionResponses:
    """Run RBFE system preparation via ``functions.run`` (low-level helper)."""
    payload = _build_sysprep_payload(
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
    raw = client.functions.run(
        key=TOOL_KEYS_AND_VERSIONS["sysprep"]["function_key"],
        version=TOOL_KEYS_AND_VERSIONS["sysprep"]["function_version"],
        params=payload,
        quote=quote,
    )
    return SyncFunctionResponses([raw])
