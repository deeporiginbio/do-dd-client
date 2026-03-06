"""ABFE -- async-only absolute binding free energy execution.

Usage::

    abfe = ABFE(protein=protein, ligand=ligand)
    abfe.prepare()
    abfe.quote()
    abfe.start()
    abfe.sync()
    results = abfe.get_results()
"""

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import AsyncExecutableMixin, QuoteMixin
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.protein import Protein
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

    @beartype
    def __init__(
        self,
        *,
        protein: Protein,
        ligand: Ligand,
        tool_version: str = ABFE_TOOL_VERSION,
        client: DeepOriginClient | None = None,
    ) -> None:
        """Create an ABFE execution for a protein-ligand pair.

        Args:
            protein: Protein structure.
            ligand: Ligand molecule.
            tool_version: Platform tool version to run. Settable so callers
                can pin or upgrade independently of the SDK release.
            client: Optional API client.
        """
        super().__init__(client=client)
        self.tool_version = tool_version

        self._protein = protein
        self._ligand = ligand
        self.solvation_xml_path: str | None = None
        self.binding_xml_path: str | None = None
        self._prepared_outputs: dict | None = None

    @property
    def protein(self) -> Protein:
        """Target protein structure."""
        return self._protein

    @property
    def ligand(self) -> Ligand:
        """Ligand to evaluate."""
        return self._ligand

    @beartype
    def prepare(
        self,
        *,
        padding: float = 1.0,
        retain_waters: bool = False,
        add_H_atoms: bool = False,
        protonate_protein: bool = False,
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
            client=self.client,
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

        self.binding_xml_path = binding_xml
        self.solvation_xml_path = solvation_xml

        system_pdb = outputs.get("system", {}).get("system_pdb_file_path")
        if system_pdb:
            local_path = self.client.files.download_file(
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

        execution_dto = utils._start_tool_run(
            params=self._build_params(),
            metadata=self._build_metadata(),
            outputs=self._build_outputs(),
            tool="ABFE",
            tool_version=self.tool_version,
            client=self.client,
            approve_amount=0,
        )

        quotation = execution_dto.get("quotationResult", {})
        successful = quotation.get("successfulQuotations", [])
        if successful:
            price = successful[0].get("priceTotal")
            if price is not None:
                self._estimate = float(price)
                self._id = execution_dto.get("executionId")
                self.status = execution_dto.get("status")

    @beartype
    def start(
        self,
        *,
        approve_amount: int | None = None,
    ) -> None:
        """Submit the ABFE execution to the platform.

        Args:
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

        self.protein.sync(client=self.client)

        execution_dto = utils._start_tool_run(
            params=self._build_params(),
            metadata=self._build_metadata(),
            outputs=self._build_outputs(),
            tool="ABFE",
            tool_version=self.tool_version,
            client=self.client,
            approve_amount=approve_amount,
        )

        job = Job.from_dto(execution_dto, client=self.client)

        self._execution_dto = execution_dto
        self._id = job.id
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

        client = self.client

        self.sync()
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

    def _build_outputs(self) -> dict:
        """Construct the output file specification for the ABFE tool."""
        output_dir = (
            f"tool-runs/ABFE/{self.protein.to_hash()}.pdb/{self.ligand.to_hash()}.sdf/"
        )
        provider = "ufa"
        return {
            "output_file": {
                "$provider": provider,
                "key": output_dir + "output/",
            },
            "abfe_results_summary": {
                "$provider": provider,
                "key": output_dir + "results.csv",
            },
        }
