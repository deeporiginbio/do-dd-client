"""PreparedSystem -- result of system preparation (ABFE/RBFE) from the platform."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Self

from beartype import beartype

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


@dataclass
@beartype
class PreparedSystem:
    """A prepared protein-ligand system (binding/solvation XML and system PDB paths).

    Returned by :meth:`SystemPrep.run() <deeporigin.drug_discovery.system_prep.SystemPrep.run>`
    or :meth:`PreparedSystem.from_result`. Used as input to ABFE or RBFE workflows.

    Attributes:
        id: Result-explorer record ID, if loaded from the platform.
        binding_xml_path: Remote path to the binding XML file.
        solvation_xml_path: Remote path to the solvation XML file.
        system_pdb_path: Remote path to the system PDB file.
        protein_id: Protein ID used for preparation.
        ligand1_id: First ligand ID (ABFE or RBFE).
        ligand2_id: Second ligand ID (RBFE only); None for ABFE.
        padding: Padding distance in nm, if known.
        add_H_atoms: Whether hydrogens were added, if known.
        retain_waters: Whether waters were retained, if known.
        protonate_protein: Whether protein was protonated, if known.
        compute_job_id: Compute job ID that produced this result, if known.
    """

    binding_xml_path: str
    solvation_xml_path: str
    system_pdb_path: str
    id: Optional[str] = None
    protein_id: Optional[str] = None
    ligand1_id: Optional[str] = None
    ligand2_id: Optional[str] = None
    padding: Optional[float] = None
    add_H_atoms: Optional[bool] = None  # NOSONAR
    retain_waters: Optional[bool] = None
    protonate_protein: Optional[bool] = None
    compute_job_id: Optional[str] = None

    def __repr__(self) -> str:
        workflow = "for RBFE" if self.ligand2_id is not None else "for ABFE"
        parts = [f"protein_id={self.protein_id!r}", f"ligand1_id={self.ligand1_id!r}"]
        if self.ligand2_id is not None:
            parts.append(f"ligand2_id={self.ligand2_id!r}")
        parts.append(workflow)
        return "PreparedSystem(" + ", ".join(parts) + ")"

    @classmethod
    def from_result(
        cls,
        *,
        protein_id: str | None = None,
        ligand1_id: str | None = None,
        ligand2_id: str | None = None,
        padding: int | float | None = None,
        add_H_atoms: bool | None = None,  # NOSONAR
        retain_waters: bool | None = None,
        protonate_protein: bool | None = None,
        client: Optional["DeepOriginClient"] = None,
    ) -> list[Self]:
        """Create PreparedSystem objects from system-prep results in the data platform.

        Fetches prepared-system results via the result-explorer API and builds
        a list of PreparedSystem instances.

        Args:
            protein_id: Optional protein ID to filter by.
            ligand1_id: Optional first ligand ID to filter by.
            ligand2_id: Optional second ligand ID to filter by (RBFE).
            padding: Optional padding value to filter by.
            add_H_atoms: Optional add_H_atoms flag to filter by.
            retain_waters: Optional retain_waters flag to filter by.
            protonate_protein: Optional protonate_protein flag to filter by.
            client: Optional DeepOriginClient. If not provided, uses the default.

        Returns:
            List of PreparedSystem objects with paths and metadata from the results.

        Raises:
            ValueError: If no prepared-system results are found for the given filters.
        """
        from deeporigin.platform.client import DeepOriginClient

        if client is None:
            client = DeepOriginClient.get()

        padding_int: int | None = None
        if padding is not None:
            padding_int = int(padding) if isinstance(padding, float) else padding

        response = client.results.get_prepared_systems(
            protein_id=protein_id,
            ligand1_id=ligand1_id,
            ligand2_id=ligand2_id,
            padding=padding_int,
            add_H_atoms=add_H_atoms,
            retain_waters=retain_waters,
            protonate_protein=protonate_protein,
        )
        records = response.get("data", [])

        if not records:
            raise ValueError(
                "No prepared-system results found for the given filters. "
                "Run SystemPrep first to prepare a system."
            )

        out: list[PreparedSystem] = []
        for record in records:
            data = record.get("data") or {}
            binding = data.get("binding_xml_file_path")
            solvation = data.get("solvation_xml_ligand1_file_path") or data.get(
                "solvation_xml_ligand2_file_path"
            )
            system_pdb = data.get("system_pdb_file_path")
            if not (binding and solvation and system_pdb):
                continue
            out.append(
                cls(
                    id=record.get("id"),
                    binding_xml_path=binding,
                    solvation_xml_path=solvation,
                    system_pdb_path=system_pdb,
                    protein_id=data.get("protein_id"),
                    ligand1_id=data.get("ligand1_id"),
                    ligand2_id=data.get("ligand2_id"),
                    padding=data.get("padding"),
                    add_H_atoms=data.get("add_H_atoms"),
                    retain_waters=data.get("retain_waters"),
                    protonate_protein=data.get("protonate_protein"),
                    compute_job_id=record.get("compute_job_id"),
                )
            )
        return out
