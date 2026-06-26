"""PreparedSystem -- result of system preparation (ABFE/RBFE) from the platform."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Self

from beartype import beartype

from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient


@dataclass
@beartype
class PreparedSystem:
    """A prepared protein-ligand system (binding/solvation XML and system PDB paths).

    Returned by :meth:`SystemPrep.run() <deeporigin.drug_discovery.system_prep.SystemPrep.run>`
    or :meth:`PreparedSystem.from_result` / :meth:`PreparedSystem.from_json`.
    Used as input to ABFE or RBFE workflows.

    Attributes:
        id: Result-explorer record ID, if loaded from the platform.
        binding_xml_path: Remote path to the binding XML file.
        solvation_xml_path: Remote path to the solvation XML file.
        system_pdb_path: Remote path to the system PDB file.
        solute_pdb_path: Remote path to the solute-only PDB file, if present.
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
    solute_pdb_path: Optional[str] = None
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

    @beartype
    def show(self, *, solute: bool = False) -> Any:
        """Visualize the prepared system structure in a Jupyter notebook using MolStar.

        By default, downloads the full system PDB from the platform. Pass
        ``solute=True`` to visualize the solute-only structure instead (requires
        :attr:`solute_pdb_path` to be set).

        Renders with the same protein-only viewer as :meth:`Protein.show` when
        called without optional pocket or ligand arguments.

        Args:
            solute: If true, use :attr:`solute_pdb_path`; otherwise
                :attr:`system_pdb_path`.

        Returns:
            Output from :func:`deeporigin.utils.notebook.render_html` (Jupyter
            ``display`` or marimo HTML wrapper, depending on environment).

        Raises:
            DeepOriginException: If the chosen PDB path is missing or empty, or
                ``solute=True`` but :attr:`solute_pdb_path` is not available.
        """
        if solute:
            if not self.solute_pdb_path:
                raise DeepOriginException(
                    "Cannot show PreparedSystem: solute_pdb_path is not set or empty "
                    "(use solute=False for the full system, or re-fetch results that "
                    "include solute_pdb_file_path).",
                ) from None
            remote = self.solute_pdb_path
        else:
            if not self.system_pdb_path:
                raise DeepOriginException(
                    "Cannot show PreparedSystem: system_pdb_path is empty.",
                ) from None
            remote = self.system_pdb_path

        client = DeepOriginClient()
        local_pdb = client.files.download(
            remote_path=remote,
            lazy=True,
        )

        from deeporigin.viz.molstar_html import render_protein_html

        from deeporigin.utils.notebook import render_html

        html_content = render_protein_html(pdb_path=local_pdb)
        return render_html(html_content)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        """Build a ``PreparedSystem`` from API-shaped JSON.

        Use the same keys as result-explorer ``data``, sync ``jobOutputs.system``, or a
        merged payload from :meth:`_from_record` (paths plus optional metadata).

        Required keys: ``binding_xml_file_path``, ``solvation_xml_ligand_file_path``,
        ``system_pdb_file_path``. Optional keys include ``solute_pdb_file_path``,
        ``protein_id``, ``ligand1_id``, ``ligand2_id``, ``padding``, ``add_H_atoms``,
        ``retain_waters``, ``protonate_protein``, ``id`` (result row id), and
        ``compute_job_id``.

        Args:
            data: Dict of paths and metadata.

        Returns:
            A populated ``PreparedSystem``.

        Raises:
            ValueError: If required path keys are missing or empty.
        """
        binding_xml_path = data.get("binding_xml_file_path")
        solvation_xml_path = data.get("solvation_xml_ligand_file_path")
        system_pdb_path = data.get("system_pdb_file_path")
        if not (binding_xml_path and solvation_xml_path and system_pdb_path):
            raise ValueError(
                "PreparedSystem JSON missing required paths (binding_xml_file_path, "
                "solvation_xml_ligand_file_path, system_pdb_file_path)."
            )
        solute_pdb_path = data.get("solute_pdb_file_path")

        raw_padding = data.get("padding")
        padding_f = float(raw_padding) if raw_padding is not None else None

        return cls(
            binding_xml_path=binding_xml_path,
            solvation_xml_path=solvation_xml_path,
            system_pdb_path=system_pdb_path,
            solute_pdb_path=solute_pdb_path,
            id=data.get("id"),
            protein_id=data.get("protein_id"),
            ligand1_id=data.get("ligand1_id"),
            ligand2_id=data.get("ligand2_id"),
            padding=padding_f,
            add_H_atoms=data.get("add_H_atoms"),
            retain_waters=data.get("retain_waters"),
            protonate_protein=data.get("protonate_protein"),
            compute_job_id=data.get("compute_job_id"),
        )

    @classmethod
    def _from_record(cls, record: dict) -> Self:
        """Build a single PreparedSystem from a result-explorer record.

        Args:
            record: A single record dict from results.get or get_prepared_systems,
                with keys ``id``, ``data``, ``compute_job_id``.

        Returns:
            A PreparedSystem with paths and metadata from the record.

        Raises:
            ValueError: If the record does not contain required path fields.
        """
        payload: dict[str, Any] = dict(record.get("data") or {})
        rid = record.get("id")
        if rid is not None:
            payload["id"] = rid
        cjid = record.get("compute_job_id")
        if cjid is not None:
            payload["compute_job_id"] = cjid
        return cls.from_json(payload)

    @classmethod
    def from_result(
        cls,
        *,
        protein_id: str | None = None,
        ligand1_id: str | None = None,
        ligand2_id: str | None = None,
        compute_job_id: str | None = None,
        padding: int | float | None = None,
        add_H_atoms: bool | None = None,  # NOSONAR
        retain_waters: bool | None = None,
        protonate_protein: bool | None = None,
        client: Optional[DeepOriginClient] = None,
    ) -> list[Self]:
        """Create PreparedSystem objects from system-prep results in the data platform.

        Fetches prepared-system results via the result-explorer API and builds
        a list of PreparedSystem instances.

        Args:
            protein_id: Optional protein ID to filter by.
            ligand1_id: Optional first ligand ID to filter by.
            ligand2_id: Optional second ligand ID to filter by (RBFE).
            compute_job_id: Optional compute job ID to filter by.
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

        if client is None:
            client = DeepOriginClient()

        padding_int: int | None = None
        if padding is not None:
            padding_int = int(padding) if isinstance(padding, float) else padding

        response = client.results.get_prepared_systems(
            protein_id=protein_id,
            ligand1_id=ligand1_id,
            ligand2_id=ligand2_id,
            compute_job_id=compute_job_id,
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

        out: list[Self] = []
        for record in records:
            try:
                out.append(cls._from_record(record))
            except ValueError:
                continue
        return out
