"""ABFE -- async-only absolute binding free energy execution.

Usage::

    abfe = ABFE(prepared_system=prepared_system)
    abfe.quote()
    abfe.start()
    # Jupyter — non-blocking cell (like legacy Job.watch):
    #     task = await abfe.watch()
    # Jupyter — block until the job finishes:
    #     await abfe.watch_async()
    # Script (blocking): asyncio.run(abfe.watch_async())
    abfe.sync()
    results = abfe.get_results()
"""

from dataclasses import dataclass
from typing import Any, Self

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import AsyncExecutableMixin, QuoteMixin
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import ABFE_TOOL_KEY, ABFE_TOOL_VERSION


@beartype
def _protein_display_name_from_entity(*, entity: dict, fallback_id: str) -> str:
    """Resolve a display label from a protein entity record.

    Preference order matches :meth:`deeporigin.drug_discovery.structures.protein.Protein.from_id`.

    Args:
        entity: Raw protein dict from ``client.entities.get_protein``.
        fallback_id: Value to use when no suitable name field is present.

    Returns:
        Non-empty display string for the protein.
    """
    for key in ("protein_name", "pdb_id", "gene_symbol"):
        value = entity.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return fallback_id


@beartype
def _ligand_display_label_from_entity(*, entity: dict, fallback_id: str) -> str:
    """Resolve ligand label: name when set, otherwise canonical or input SMILES.

    Args:
        entity: Raw ligand dict from ``client.entities.get_ligand``.
        fallback_id: Value to use when no name or SMILES is present.

    Returns:
        Non-empty display string for the ligand.
    """
    name = entity.get("name")
    if name is not None and str(name).strip():
        return str(name).strip()
    smiles = entity.get("canonical_smiles") or entity.get("smiles")
    if smiles is not None and str(smiles).strip():
        return str(smiles).strip()
    return fallback_id


@beartype
def _abfe_default_name(
    *,
    prepared_system: PreparedSystem,
    client: DeepOriginClient,
) -> str:
    """Build a short human-readable label for an ABFE execution.

    Loads protein and ligand records via ``client.entities`` when IDs are set,
    then formats ``ABFE: <protein> with <ligand>``. The ligand segment uses
    SMILES when the entity has no name. On fetch failure, falls back to the
    corresponding ID string.

    Args:
        prepared_system: Prepared system carrying protein and ligand entity IDs.
        client: API client used to resolve entities.

    Returns:
        A string such as ``ABFE: BRD4 with CCO`` or ``ABFE: BRD4 with lig-456``
        when metadata is missing.
    """
    pid = prepared_system.protein_id
    lid = prepared_system.ligand1_id
    protein_id_str = pid.strip() if pid is not None and pid.strip() else ""
    ligand_id_str = lid.strip() if lid is not None and lid.strip() else ""

    if protein_id_str:
        try:
            protein_label = _protein_display_name_from_entity(
                entity=client.entities.get_protein(id=protein_id_str),
                fallback_id=protein_id_str,
            )
        except Exception:
            protein_label = protein_id_str
    else:
        protein_label = "unknown protein"

    if ligand_id_str:
        try:
            ligand_label = _ligand_display_label_from_entity(
                entity=client.entities.get_ligand(id=ligand_id_str),
                fallback_id=ligand_id_str,
            )
        except Exception:
            ligand_label = ligand_id_str
    else:
        ligand_label = "unknown ligand"

    return f"ABFE: {protein_label} with {ligand_label}"


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


class ABFE(Execution, QuoteMixin, AsyncExecutableMixin, NotebookWatchMixin):
    """Absolute Binding Free Energy calculation (async-only).

    Requires a ``PreparedSystem`` from system preparation before ``start()``.

    Attributes:
        prepared_system: Prepared system containing binding and solvation XML paths.
        name: Execution label, set from platform entities when IDs are present unless overridden.
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
        name: str | None = None,
    ) -> None:
        """Create an ABFE execution from a prepared system.

        Args:
            prepared_system: Prepared system with binding and solvation XML paths.
            params: ABFE calculation parameters. If None, uses default values.
            tool_version: Platform tool version to run. Settable so callers
                can pin or upgrade independently of the SDK release.
            client: Optional API client.
            name: Optional execution label. When omitted, derived by fetching
                protein and ligand entities when ``prepared_system`` IDs are set.
        """
        super().__init__(client=client)
        self.tool_version = tool_version

        self.prepared_system = prepared_system
        self.name = (
            name
            if name is not None
            else _abfe_default_name(prepared_system=prepared_system, client=self.client)
        )

        # Store parameters in a frozen dataclass
        self._params = params if params is not None else ABFEParams()

    @classmethod
    def from_dto(
        cls,
        dto: dict,
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct an ABFE instance from an execution DTO.

        Rehydrates ``prepared_system`` and ``_params`` from the stored
        ``userInputs`` and ``metadata``.

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client. Uses the default if not provided.

        Returns:
            A fully-hydrated ABFE instance with status from the DTO.
        """
        instance = super().from_dto(dto, client=client)
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

    @classmethod
    def from_id(
        cls,
        id: str,
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct an ABFE instance from an existing platform execution ID.

        Fetches the execution record via the API and delegates to
        :meth:`from_dto`.

        Args:
            id: Platform execution ID.
            client: Optional API client. Uses the default if not provided.

        Returns:
            A fully-hydrated ABFE instance with status synced from the platform.
        """
        return super().from_id(id, client=client)

    @property
    def params(self) -> ABFEParams:
        """ABFE calculation parameters (read-only)."""
        return self._params

    @params.setter
    def params(self, value: ABFEParams) -> None:
        """Prevent modification of params after construction."""
        raise AttributeError("params can only be set in the constructor")

    def get_quote_execution_dto(self) -> dict[str, Any]:
        """Build the ABFE quote payload and return the tools API execution DTO.

        Uses ``approveAmount=0`` via ``executions.create``. Parsing and state
        assignment are handled by :meth:`~deeporigin.drug_discovery.execution_mixins.QuoteMixin._apply_quotation_dto`.

        Returns:
            Raw execution dictionary from the platform.
        """
        payload = {
            "inputs": self._build_params(),
            "outputs": self._build_outputs(),
            "metadata": self._build_metadata(),
            "approveAmount": 0,
        }
        if self.name is not None:
            payload["name"] = self.name

        return self.client.executions.create(
            data=payload,
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )

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
        from deeporigin.platform.job import Job

        payload = {
            "inputs": self._build_params(),
            "outputs": self._build_outputs(),
            "metadata": self._build_metadata(),
        }
        if self.name is not None:
            payload["name"] = self.name
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount

        execution_dto = self.client.executions.create(
            data=payload,
            tool_key=self.tool_key,
            tool_version=self.tool_version,
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
            self._execution_dto = client.executions.get(self.id)

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
