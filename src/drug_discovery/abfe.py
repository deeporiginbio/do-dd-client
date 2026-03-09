"""ABFE -- async-only absolute binding free energy execution.

Usage::

    abfe = ABFE(protein=protein, ligand=ligand)
    abfe.prepare()
    abfe.quote()
    abfe.start()
    abfe.sync()
    results = abfe.get_results()
"""

from typing import NoReturn

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import AsyncExecutableMixin, QuoteMixin
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import ABFE_TOOL_KEY, ABFE_TOOL_VERSION


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
    ) -> NoReturn:
        """Run system preparation for the protein-ligand pair.

        .. note::

            Not yet implemented. Will produce the solvation and binding
            XML files required by ``start()``.

        Args:
            padding: Padding around the system box in nm. Defaults to 1.0.
            retain_waters: Keep water molecules from the crystal structure.
            add_H_atoms: Add hydrogen atoms to the ligand.
            protonate_protein: Protonate the protein.

        Raises:
            NotImplementedError: Always -- preparation is not yet supported.
        """
        raise NotImplementedError("ABFE preparation is not supported yet.")

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
