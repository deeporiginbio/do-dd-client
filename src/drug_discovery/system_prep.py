"""SystemPrep -- sync-only execution for preparing a protein-ligand system for ABFE or RBFE.

Usage (ABFE)::

    sysprep = SystemPrep(protein=protein, ligand=ligand)
    sysprep.quote()
    sysprep.run()
    abfe = ABFE(system=sysprep)

Usage (RBFE)::

    sysprep = SystemPrep(protein=protein, ligand1=lig1, ligand2=lig2)
    sysprep.quote()
    sysprep.run()
"""

from beartype import beartype

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import QuoteMixin, SyncExecutableMixin
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import (
    SYSPREP_FUNCTION_KEY,
    SYSPREP_FUNCTION_VERSION,
)


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
        binding_xml_path: Remote path to binding XML (set after successful ``run()``).
        solvation_xml_path: Remote path to solvation XML (set after successful ``run()``).
        system_pdb_path: Remote path to system PDB (set after successful ``run()``).
    """

    tool_key: str = SYSPREP_FUNCTION_KEY

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
        tool_version: str = SYSPREP_FUNCTION_VERSION,
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
            tool_version: Platform function version. Settable so callers can pin or
                upgrade independently of the SDK release.
            client: Optional API client. Uses the default if not provided.

        Raises:
            ValueError: If neither (ligand) nor (ligand1 and ligand2) is set, or both are set.
        """
        super().__init__(client=client)
        _abfe_mode = ligand is not None and ligand1 is None and ligand2 is None
        _rbfe_mode = ligand is None and ligand1 is not None and ligand2 is not None
        if not (_abfe_mode or _rbfe_mode):
            raise ValueError(
                "Provide either ligand (ABFE) or both ligand1 and ligand2 (RBFE), "
                "but not both and not only one of ligand1/ligand2."
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

        self.binding_xml_path: str | None = None
        self.solvation_xml_path: str | None = None
        self.system_pdb_path: str | None = None

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
    def is_rbfe(self) -> bool:
        """True if this SystemPrep was created with ligand1 and ligand2 (RBFE path)."""
        return self._is_rbfe

    @property
    def is_prepared(self) -> bool:
        """True if run() has completed successfully and output paths are set."""
        return (
            self.binding_xml_path is not None
            and self.solvation_xml_path is not None
            and self.system_pdb_path is not None
        )

    def __repr__(self) -> str:
        """Return a concise summary of this SystemPrep."""
        parts = ["SystemPrep("]
        if self.protein.id is not None:
            parts.append(f"  protein_id={self.protein.id!r},")
        if self._is_rbfe and self.ligand1 is not None and self.ligand2 is not None:
            if self.ligand1.id is not None:
                parts.append(f"  ligand1_id={self.ligand1.id!r},")
            if self.ligand2.id is not None:
                parts.append(f"  ligand2_id={self.ligand2.id!r},")
        elif self.ligand is not None and self.ligand.id is not None:
            parts.append(f"  ligand_id={self.ligand.id!r},")
        parts.append(f"  is_rbfe={self._is_rbfe},")
        parts.append(f"  is_prepared={self.is_prepared},")
        parts.append(")")
        return "\n".join(parts)

    def quote(self) -> None:
        """Request a cost estimate for system preparation.

        Populates ``self.estimate`` with the estimated cost in dollars.
        Does not mutate output paths or run the function.
        """
        if self._is_rbfe:
            from deeporigin.functions.sysprep import rbfe as _rbfe

            result = _rbfe(
                protein=self.protein,
                ligand1=self.ligand1,
                ligand2=self.ligand2,
                padding=self._padding,
                retain_waters=self._retain_waters,
                add_H_atoms=self._add_H_atoms,
                protonate_protein=self._protonate_protein,
                box_size=self._box_size,
                client=self.client,
                quote=True,
            )
        else:
            from deeporigin.functions.sysprep import abfe as _abfe

            result = _abfe(
                protein=self.protein,
                ligand=self.ligand,
                padding=self._padding,
                retain_waters=self._retain_waters,
                add_H_atoms=self._add_H_atoms,
                protonate_protein=self._protonate_protein,
                box_size=self._box_size,
                client=self.client,
                quote=True,
            )
        if result.estimate is not None:
            self._estimate = result.estimate

    def run(self) -> "SystemPrep":
        """Execute system preparation (blocking).

        Calls the platform system-prep function (ABFE or RBFE path), then parses
        the response and sets ``binding_xml_path``, ``solvation_xml_path``, and
        ``system_pdb_path``. Also sets ``self.cost``.

        Returns:
            self, so the caller can pass this object to ABFE(system=...) in ABFE mode.
        """
        if self._is_rbfe:
            from deeporigin.functions.sysprep import rbfe as _rbfe

            result = _rbfe(
                protein=self.protein,
                ligand1=self.ligand1,
                ligand2=self.ligand2,
                padding=self._padding,
                retain_waters=self._retain_waters,
                add_H_atoms=self._add_H_atoms,
                protonate_protein=self._protonate_protein,
                box_size=self._box_size,
                client=self.client,
                quote=False,
            )
        else:
            from deeporigin.functions.sysprep import abfe as _abfe

            result = _abfe(
                protein=self.protein,
                ligand=self.ligand,
                padding=self._padding,
                retain_waters=self._retain_waters,
                add_H_atoms=self._add_H_atoms,
                protonate_protein=self._protonate_protein,
                box_size=self._box_size,
                client=self.client,
                quote=False,
            )

        if result.cost is not None:
            self._cost = result.cost

        if not result.function_outputs:
            return self

        outputs = result.function_outputs[0]
        output_files = outputs.get("output_files", [])
        binding = [f for f in output_files if f.endswith("bsm_system.xml")]
        solvation = [f for f in output_files if f.endswith("solvation.xml")]
        if binding:
            self.binding_xml_path = binding[0]
        if solvation:
            self.solvation_xml_path = solvation[0]
        system = outputs.get("system", {})
        if isinstance(system, dict):
            pdb_path = system.get("system_pdb_file_path")
            if pdb_path is not None:
                self.system_pdb_path = pdb_path

        return self
