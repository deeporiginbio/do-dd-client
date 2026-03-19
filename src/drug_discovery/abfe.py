"""ABFE -- async-only absolute binding free energy execution.

Usage::

    abfe = ABFE(prepared_system=prepared_system)
    abfe.quote()
    abfe.start()
    abfe.sync()
    results = abfe.get_results()
"""

from dataclasses import dataclass
from typing import Self

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import AsyncExecutableMixin, QuoteMixin
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import ABFE_TOOL_KEY, ABFE_TOOL_VERSION


@dataclass(frozen=True)
class ABFEParams:
    """ABFE calculation parameters.

    Attributes:
        annihilate: Whether to annihilate the ligand.
        dt: Time step in ps. Used for both emeq_md_options and prod_md_options.
        temperature: Temperature in K. Used for both emeq_md_options and prod_md_options.
        cutoff: Cutoff distance in nm. Used for both emeq_md_options and prod_md_options.
        repeats: Number of repeats.
        replex_period_ps: Replica exchange period in ps.
        test_run: Test run flag.
        binding_n_windows: Number of windows for binding calculation.
        binding_npt_reduce_restraints_ns: NPT reduce restraints time in ns for binding.
        binding_nvt_heating_ns: NVT heating time in ns for binding.
        binding_steps: Number of steps for binding calculation.
        solvation_n_windows: Number of windows for solvation calculation.
        solvation_npt_reduce_restraints_ns: NPT reduce restraints time in ns for solvation.
        solvation_nvt_heating_ns: NVT heating time in ns for solvation.
        solvation_steps: Number of steps for solvation calculation.
    """

    # Common parameters (same for binding and solvation)
    annihilate: bool = True
    dt: float = 0.004
    temperature: float = 298.15
    cutoff: float = 0.9
    repeats: int = 1
    replex_period_ps: float = 2.5
    test_run: int = 0
    # Binding-specific parameters
    binding_n_windows: int = 48
    binding_npt_reduce_restraints_ns: float = 2.0
    binding_nvt_heating_ns: float = 1.0
    binding_steps: int = 1250000
    # Solvation-specific parameters
    solvation_n_windows: int = 32
    solvation_npt_reduce_restraints_ns: float = 0.2
    solvation_nvt_heating_ns: float = 0.1
    solvation_steps: int = 500000

    def __repr__(self) -> str:
        """Return a string representation with each attribute on its own line.

        Fields modified from their default values are marked with an asterisk (*).
        """
        lines = []
        for f in self.__dataclass_fields__.values():
            value = getattr(self, f.name)
            changed = f.default is not f.default_factory and value != f.default
            marker = " *" if changed else ""
            lines.append(f"  {f.name}: {value}{marker}")
        return "ABFEParams(\n" + "\n".join(lines) + "\n)"

    def to_dict(
        self,
        *,
        binding_xml_path: str,
        solvation_xml_path: str,
    ) -> dict:
        """Build the tool input parameters dict.

        Args:
            binding_xml_path: Remote path to the binding XML file.
            solvation_xml_path: Remote path to the solvation XML file.

        Returns:
            Parameters dict ready to be passed to the ABFE tool.
        """
        md_options = {
            "T": self.temperature,
            "cutoff": self.cutoff,
            "dt": self.dt,
        }
        return {
            "prepared_system": {
                "binding_xml_file_path": binding_xml_path,
                "solvation_xml_ligand1_file_path": solvation_xml_path,
            },
            "binding": {
                "annihilate": self.annihilate,
                "emeq_md_options": md_options,
                "n_windows": self.binding_n_windows,
                "npt_reduce_restraints_ns": self.binding_npt_reduce_restraints_ns,
                "nvt_heating_ns": self.binding_nvt_heating_ns,
                "prod_md_options": md_options,
                "repeats": self.repeats,
                "replex_period_ps": self.replex_period_ps,
                "steps": self.binding_steps,
                "test_run": self.test_run,
            },
            "solvation": {
                "annihilate": self.annihilate,
                "emeq_md_options": md_options,
                "n_windows": self.solvation_n_windows,
                "npt_reduce_restraints_ns": self.solvation_npt_reduce_restraints_ns,
                "nvt_heating_ns": self.solvation_nvt_heating_ns,
                "prod_md_options": md_options,
                "repeats": self.repeats,
                "replex_period_ps": self.replex_period_ps,
                "steps": self.solvation_steps,
                "test_run": self.test_run,
            },
        }


class ABFE(Execution, QuoteMixin, AsyncExecutableMixin):
    """Absolute Binding Free Energy calculation (async-only).

    Requires a ``PreparedSystem`` from system preparation before ``start()``.

    Attributes:
        prepared_system: Prepared system containing binding and solvation XML paths.
    """

    tool_key: str = ABFE_TOOL_KEY

    @beartype
    def __init__(
        self,
        *,
        prepared_system: PreparedSystem,
        params: ABFEParams | None = None,
        tool_version: str = ABFE_TOOL_VERSION,
        client: DeepOriginClient | None = None,
    ) -> None:
        """Create an ABFE execution from a prepared system.

        Args:
            prepared_system: Prepared system with binding and solvation XML paths.
            params: ABFE calculation parameters. If None, uses default values.
            tool_version: Platform tool version to run. Settable so callers
                can pin or upgrade independently of the SDK release.
            client: Optional API client.
        """
        super().__init__(client=client)
        self.tool_version = tool_version

        self.prepared_system = prepared_system

        # Store parameters in a frozen dataclass
        self._params = params if params is not None else ABFEParams()

    @classmethod
    def from_id(
        cls,
        id: str,
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct an ABFE instance from an existing platform execution ID.

        Fetches the execution record and rehydrates ``prepared_system`` and
        ``_params`` from the stored ``userInputs`` and ``metadata``.

        Args:
            id: Platform execution ID.
            client: Optional API client. Uses the default if not provided.

        Returns:
            A fully-hydrated ABFE instance with status synced from the platform.
        """
        instance = super().from_id(id, client=client)
        inputs = instance._execution_dto.get("userInputs", {})
        metadata = instance._execution_dto.get("metadata", {})

        prepared_system_input = inputs.get("prepared_system", {})
        binding = inputs.get("binding", {})
        solvation = inputs.get("solvation", {})
        md_options = binding.get("emeq_md_options", {})

        instance.prepared_system = PreparedSystem(
            binding_xml_path=prepared_system_input.get("binding_xml_file_path", ""),
            solvation_xml_path=prepared_system_input.get(
                "solvation_xml_ligand1_file_path", ""
            ),
            system_pdb_path="",
            protein_id=metadata.get("protein_id"),
            ligand1_id=metadata.get("ligand_id"),
        )

        _BINDING_KEY_MAP = {
            "annihilate": "annihilate",
            "n_windows": "binding_n_windows",
            "npt_reduce_restraints_ns": "binding_npt_reduce_restraints_ns",
            "nvt_heating_ns": "binding_nvt_heating_ns",
            "steps": "binding_steps",
            "repeats": "repeats",
            "replex_period_ps": "replex_period_ps",
            "test_run": "test_run",
        }
        _SOLVATION_KEY_MAP = {
            "n_windows": "solvation_n_windows",
            "npt_reduce_restraints_ns": "solvation_npt_reduce_restraints_ns",
            "nvt_heating_ns": "solvation_nvt_heating_ns",
            "steps": "solvation_steps",
        }
        _MD_OPTIONS_KEY_MAP = {
            "dt": "dt",
            "T": "temperature",
            "cutoff": "cutoff",
        }

        kwargs: dict = {}
        for dto_key, param_field in _BINDING_KEY_MAP.items():
            if dto_key in binding:
                kwargs[param_field] = binding[dto_key]
        for dto_key, param_field in _SOLVATION_KEY_MAP.items():
            if dto_key in solvation:
                kwargs[param_field] = solvation[dto_key]
        for dto_key, param_field in _MD_OPTIONS_KEY_MAP.items():
            if dto_key in md_options:
                kwargs[param_field] = md_options[dto_key]

        instance._params = ABFEParams(**kwargs)

        return instance

    @property
    def params(self) -> ABFEParams:
        """ABFE calculation parameters (read-only)."""
        return self._params

    @params.setter
    def params(self, value: ABFEParams) -> None:
        """Prevent modification of params after construction."""
        raise AttributeError("params can only be set in the constructor")

    def _quote_impl(self) -> None:
        """Request a cost estimate for the ABFE calculation.

        Populates ``self.estimate``. Uses the tools API with
        ``approve_amount=0`` to get a quotation.
        """
        from deeporigin.drug_discovery import utils

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
    def _start_impl(
        self,
        *,
        approve_amount: int | None = None,
    ) -> None:
        """Submit the ABFE execution to the platform.

        Args:
            approve_amount: Pre-approved spend amount. If None, uses default.
        """
        from deeporigin.drug_discovery import utils
        from deeporigin.platform.job import Job

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

        local_path = client.files.download(
            remote_path=remote_path,
            lazy=True,
        )

        return pd.read_csv(local_path, nrows=1)

    def _build_params(self) -> dict:
        """Construct the tool input parameters dict."""
        return self.params.to_dict(
            binding_xml_path=self.prepared_system.binding_xml_path,
            solvation_xml_path=self.prepared_system.solvation_xml_path,
        )

    def __repr__(self) -> str:
        """Return a string representation showing protein and ligand IDs."""
        ps = getattr(self, "prepared_system", None)
        if ps is None:
            return super().__repr__()
        return f"ABFE(protein_id={ps.protein_id!r}, ligand_id={ps.ligand1_id!r})"

    def _build_metadata(self) -> dict:
        """Construct execution metadata."""
        metadata = {}
        if self.prepared_system.protein_id:
            metadata["protein_id"] = self.prepared_system.protein_id
        if self.prepared_system.ligand1_id:
            metadata["ligand_id"] = self.prepared_system.ligand1_id
        return metadata

    def _build_outputs(self) -> dict:
        """Construct the output file specification for the ABFE tool."""
        return {}
