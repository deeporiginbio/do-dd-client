"""ABFE -- async-only absolute binding free energy execution.

Usage::

    abfe = ABFE(protein=protein, ligand=ligand)
    abfe.prepare()
    abfe.quote()
    abfe.start()
    abfe.refresh()
    results = abfe.get_results()
"""

from typing import Optional

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.jobs.base import Execution
from deeporigin.jobs.mixins import AsyncExecutableMixin, QuoteMixin
from deeporigin.platform.client import DeepOriginClient

ABFE_TOOL_KEY = "deeporigin.abfe-end-to-end"
ABFE_TOOL_VERSION = "0.2.19"


class ABFE(Execution, QuoteMixin, AsyncExecutableMixin):
    """Absolute Binding Free Energy calculation (async-only).

    Requires a ``prepare()`` step before ``start()`` to generate the
    solvation and binding XML files needed by the ABFE tool.

    Attributes:
        protein: Target protein structure.
        ligand: Ligand to evaluate.
        solvation_xml_path: Remote path to the solvation XML (set by ``prepare()``).
        binding_xml_path: Remote path to the binding XML (set by ``prepare()``).
    """

    tool_key: str = ABFE_TOOL_KEY
    tool_version: str = ABFE_TOOL_VERSION

    _immutable_fields: frozenset[str] = frozenset({"protein", "ligand"})

    @beartype
    def __init__(
        self,
        *,
        protein: Protein,
        ligand: Ligand,
        client: DeepOriginClient | None = None,
    ) -> None:
        """Create an ABFE execution for a protein-ligand pair.

        Args:
            protein: Protein structure.
            ligand: Ligand molecule.
            client: Optional API client.
        """
        super().__init__()
        self._init_async()

        with self._system_update():
            self.protein = protein
            self.ligand = ligand
            self.solvation_xml_path: str | None = None
            self.binding_xml_path: str | None = None

        self._client = client
        self._prepared_outputs: dict | None = None

    @beartype
    def prepare(
        self,
        *,
        padding: float = 1.0,
        retain_waters: bool = False,
        add_H_atoms: bool = False,
        protonate_protein: bool = False,
        client: DeepOriginClient | None = None,
    ) -> Protein:
        """Run system preparation for the protein-ligand pair.

        This step produces the solvation and binding XML files required
        by ``start()``. The resulting prepared system PDB is returned as
        a ``Protein`` object and can be visualised.

        Args:
            padding: Padding around the system box in nm. Defaults to 1.0.
            retain_waters: Keep water molecules from the crystal structure.
            add_H_atoms: Add hydrogen atoms to the ligand.
            protonate_protein: Protonate the protein.
            client: Optional API client.

        Returns:
            A ``Protein`` built from the prepared system PDB.

        Raises:
            ValueError: If the ligand is charged (ABFE does not support charged ligands).
        """
        from deeporigin.exceptions import DeepOriginException
        from deeporigin.functions.sysprep import abfe as _sysprep_abfe

        if self.ligand.is_charged():
            raise DeepOriginException(
                title="Cannot prepare ABFE: charged ligand",
                message=f"Ligand {self.ligand.name} is charged. ABFE does not support charged ligands.",
            )

        client = client or self._resolve_client()

        missing = self.protein.find_missing_residues()
        if len(missing) > 0:
            raise DeepOriginException(
                title="Protein has missing residues",
                message="Please use the loop modelling tool to fill in missing residues before preparing.",
            )

        result = _sysprep_abfe(
            protein=self.protein,
            ligand=self.ligand,
            padding=padding,
            retain_waters=retain_waters,
            add_H_atoms=add_H_atoms,
            protonate_protein=protonate_protein,
            client=client,
        )

        outputs = result.function_outputs[0]
        self._prepared_outputs = outputs

        output_files = outputs.get("output_files", [])
        if not output_files and "system" in outputs:
            output_files = outputs

        binding_xml = None
        solvation_xml = None

        if isinstance(output_files, list):
            for f in output_files:
                if isinstance(f, str) and f.endswith("bsm_system.xml"):
                    binding_xml = f
                elif isinstance(f, str) and f.endswith("solvation.xml"):
                    solvation_xml = f
        elif isinstance(output_files, dict):
            for key, val in output_files.items():
                if isinstance(val, dict) and "system_pdb_file_path" in val:
                    pass

        with self._system_update():
            self.binding_xml_path = binding_xml
            self.solvation_xml_path = solvation_xml

        system_pdb = outputs.get("system", {}).get("system_pdb_file_path")
        if system_pdb:
            local_path = client.files.download_file(
                remote_path=system_pdb,
                lazy=True,
            )
            return Protein.from_file(local_path)

        return self.protein

    def quote(self) -> None:
        """Request a cost estimate for the ABFE calculation.

        Populates ``self.estimate``. Uses the tools API with
        ``approve_amount=0`` to get a quotation.
        """
        from deeporigin.drug_discovery import utils

        if self.binding_xml_path is None or self.solvation_xml_path is None:
            raise ValueError(
                "System has not been prepared. Call prepare() before quote()."
            )

        client = self._resolve_client()
        params = self._build_params()

        metadata = self._build_metadata()
        output_dir_path = self._build_output_dir()

        execution_dto = utils._start_tool_run(
            params=params,
            metadata=metadata,
            tool="ABFE",
            tool_version=self.tool_version,
            client=client,
            output_dir_path=output_dir_path,
            approve_amount=0,
        )

        quotation = execution_dto.get("quotationResult", {})
        successful = quotation.get("successfulQuotations", [])
        if successful:
            price = successful[0].get("priceTotal")
            if price is not None:
                with self._system_update():
                    self.estimate = float(price)
                    self.id = execution_dto.get("executionId")
                    self.status = execution_dto.get("status")

    @beartype
    def start(
        self,
        *,
        client: DeepOriginClient | None = None,
        approve_amount: Optional[int] = None,
    ) -> None:
        """Submit the ABFE execution to the platform.

        Args:
            client: Optional API client.
            approve_amount: Pre-approved spend amount. If None, uses default.

        Raises:
            ValueError: If the system has not been prepared.
        """
        from deeporigin.drug_discovery import utils
        from deeporigin.platform.job import Job

        if self.binding_xml_path is None or self.solvation_xml_path is None:
            raise ValueError(
                "System has not been prepared. Call prepare() before start()."
            )

        client = client or self._resolve_client()

        self.protein.sync(client=client)

        params = self._build_params()
        metadata = self._build_metadata()
        output_dir_path = self._build_output_dir()

        execution_dto = utils._start_tool_run(
            params=params,
            metadata=metadata,
            tool="ABFE",
            tool_version=self.tool_version,
            client=client,
            output_dir_path=output_dir_path,
            approve_amount=approve_amount,
        )

        job = Job.from_dto(execution_dto, client=client)

        with self._system_update():
            self._execution_dto = execution_dto
            self.id = job.id
            self.status = job.status

    def get_results(self) -> pd.DataFrame | None:
        """Retrieve ABFE results as a DataFrame.

        Downloads the results CSV from the platform and returns a
        DataFrame with the binding free energy and related data.

        Returns:
            A DataFrame with ABFE results, or ``None`` if not yet available.

        Raises:
            ValueError: If no execution has been started.
        """
        if self.id is None:
            raise ValueError("No execution has been started. Call start() first.")

        client = self._resolve_client()

        self.refresh(client=client)
        if self.status != "Succeeded":
            return None

        if self._execution_dto is None:
            result = client.executions.get_execution(execution_id=self.id)
            self._execution_dto = result

        user_outputs = self._execution_dto.get("userOutputs", {})
        summary_info = user_outputs.get("abfe_results_summary", {})
        remote_path = summary_info.get("key")

        if not remote_path:
            return None

        local_path = client.files.download_file(
            remote_path=remote_path,
            lazy=True,
        )

        return pd.read_csv(local_path, nrows=1)

    def _build_params(self) -> dict:
        """Construct the tool input parameters dict."""
        from deeporigin.drug_discovery import utils

        params = utils._load_params("abfe_end_to_end")
        params["binding_xml"] = {
            "$provider": "ufa",
            "key": self.binding_xml_path,
        }
        params["solvation_xml"] = {
            "$provider": "ufa",
            "key": self.solvation_xml_path,
        }
        return params

    def _build_metadata(self) -> dict:
        """Construct execution metadata."""
        return {
            "protein_hash": self.protein.to_hash(),
            "ligand_hash": self.ligand.to_hash(),
            "ligand_smiles": self.ligand.smiles,
            "protein_name": self.protein.name,
            "ligand_name": self.ligand.name,
        }

    def _build_output_dir(self) -> str:
        """Construct the remote output directory path."""
        return (
            f"tool-runs/ABFE/{self.protein.to_hash()}.pdb/{self.ligand.to_hash()}.sdf/"
        )

    def _resolve_client(self) -> DeepOriginClient:
        """Return the client, falling back to the default singleton."""
        if self._client is not None:
            return self._client
        return DeepOriginClient.get()
