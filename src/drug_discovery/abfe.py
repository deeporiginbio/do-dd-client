"""ABFE -- class to run and control absolute binding free energy calculations."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Self

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import AsyncExecutableMixin
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status


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


@beartype
def _abfe_first_remote_trajectory_path(*, data: dict[str, Any]) -> str:
    """Return any remote trajectory path string from ABFE result ``data``."""
    for analysis_key in ("binding_analysis", "solvation_analysis"):
        blocks = data.get(analysis_key)
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            traj = block.get("trajectories")
            if not isinstance(traj, dict) or not traj:
                continue
            for value in traj.values():
                if isinstance(value, str) and value.strip():
                    return value.strip()
    raise DeepOriginException(
        title="No trajectory metadata in results",
        message="Results do not include binding or solvation trajectory paths yet.",
        fix="Wait for the job to finish and ensure the tool version records trajectories.",
    ) from None


@beartype
def _abfe_tool_run_root(*, remote_trajectory_path: str) -> str:
    """Return ``tool-runs/<uuid>`` prefix parsed from a trajectory remote path."""
    parts = remote_trajectory_path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "tool-runs":
        return f"{parts[0]}/{parts[1]}"
    raise DeepOriginException(
        title="Invalid trajectory path",
        message=f"Could not locate tool-runs root in {remote_trajectory_path!r}.",
        fix="Report this path to support if the job completed successfully.",
    ) from None


@beartype
def _abfe_pick_analysis_block(
    *,
    blocks: list[Any],
    repeat: int,
) -> dict[str, Any]:
    """Pick one binding or solvation analysis dict for the given repeat index."""
    if not blocks:
        raise DeepOriginException(
            title="No analysis repeats in results",
            message="The results payload has no analysis entries for this step.",
        ) from None
    for block in blocks:
        if isinstance(block, dict) and block.get("repeat") == repeat:
            return block
    if 1 <= repeat <= len(blocks):
        candidate = blocks[repeat - 1]
        if isinstance(candidate, dict):
            return candidate
    raise DeepOriginException(
        title="Invalid repeat index",
        message=f"No analysis block for repeat={repeat!r}.",
        fix=f"Use repeat between 1 and {len(blocks)} (or a repeat id present in results).",
    ) from None


@beartype
def _abfe_sorted_window_numbers(*, trajectories: dict[str, Any]) -> list[int]:
    """Sorted lambda-window indices from a ``trajectories`` mapping."""
    out: list[int] = []
    for key in trajectories:
        if not isinstance(key, str) or not key.startswith("window_"):
            continue
        suffix = key.removeprefix("window_")
        if suffix.isdigit():
            out.append(int(suffix))
    return sorted(out)


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
        prepared_system: PreparedSystem,
    ) -> dict:
        """Build the calculation-parameter portion of the tool input dict.

        The returned dict carries ``prepared_system``, ``binding``, and
        ``solvation`` only -- the ``mode`` discriminator required by the
        ``deeporigin.abfe-e2e-workflow`` tool is added by
        :meth:`ABFE._build_params`.

        Args:
            prepared_system: Prepared system with XML paths and entity IDs (same
                shape as system-prep ``system`` output).

        Returns:
            Calculation-parameter dict ready to be merged into the tool input.
        """
        md_options = {
            "T": self.temperature,
            "cutoff": self.cutoff,
            "dt": self.dt,
        }
        ps_out: dict = {
            "binding_xml_file_path": prepared_system.binding_xml_path,
            "solvation_xml_ligand_file_path": prepared_system.solvation_xml_path,
        }
        if prepared_system.protein_id is not None:
            ps_out["protein_id"] = prepared_system.protein_id
        if prepared_system.ligand1_id is not None:
            ps_out["ligand1_id"] = prepared_system.ligand1_id
        if prepared_system.ligand2_id is not None:
            ps_out["ligand2_id"] = prepared_system.ligand2_id
        return {
            "prepared_system": ps_out,
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


class ABFE(Execution, AsyncExecutableMixin, NotebookWatchMixin):
    """Absolute Binding Free Energy calculation (async-only).

    Drives the ``deeporigin.abfe-e2e-workflow`` tool in ``mode="abfe"``: the
    workflow takes an already-prepared system (binding + solvation XML files)
    and runs the ABFE legs only. To produce the prepared system, use the
    separate :class:`~deeporigin.drug_discovery.system_prep.SystemPrep` class
    (``deeporigin.system-prep`` tool); this class does not run system prep.

    Requires a ``PreparedSystem`` from system preparation before ``start()``.
    After success, :meth:`show_trajectory` can download trajectory and structure
    files and open a Mol* viewer in Jupyter (or marimo), and
    :meth:`show_overlap_matrix` / :meth:`show_convergence_time` can display
    binding or solvation diagnostic PNGs from the ABFE result row for this
    execution.

    Attributes:
        prepared_system: Prepared system containing binding and solvation XML paths.
        name: Execution label, set from platform entities when IDs are present unless overridden.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["abfe"]["tool_key"]
    mode: Literal["abfe"] = "abfe"

    @beartype
    def __init__(
        self,
        *,
        prepared_system: PreparedSystem,
        params: ABFEParams | None = None,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["abfe"]["tool_version"],
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
        inputs = instance._dto.get("userInputs", {})  # ty:ignore[unresolved-attribute]
        metadata = instance._dto.get("metadata", {})  # ty:ignore[unresolved-attribute]

        # dto_mode = inputs.get("mode")
        # if dto_mode is not None and dto_mode != cls.mode:
        #     raise ValueError(
        #         f"Cannot rehydrate ABFE from a DTO with mode={dto_mode!r}; "
        #         f"this class only supports mode={cls.mode!r}."
        #     )

        prepared_system_input = inputs.get("prepared_system", {})
        binding = inputs.get("binding", {})
        solvation = inputs.get("solvation", {})
        md_options = binding.get("emeq_md_options", {})

        instance.prepared_system = PreparedSystem(
            binding_xml_path=prepared_system_input.get("binding_xml_file_path", ""),
            solvation_xml_path=prepared_system_input.get(
                "solvation_xml_ligand_file_path", ""
            ),
            system_pdb_path="",
            solute_pdb_path=prepared_system_input.get("solute_pdb_file_path"),
            protein_id=prepared_system_input.get("protein_id")
            or metadata.get("protein_id"),
            ligand1_id=prepared_system_input.get("ligand1_id")
            or metadata.get("ligand1_id")
            or metadata.get("ligand_id"),
            ligand2_id=prepared_system_input.get("ligand2_id"),
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

    def _make_payload(
        self,
        *,
        approve_amount: int | None,
        sync: bool,  # noqa: ARG002 -- ABFE is always async; parameter kept for API consistency
    ) -> dict[str, Any]:
        """Build create payload for ``executions.create``."""
        payload: dict[str, Any] = {
            "inputs": self._build_params(),
            "outputs": self._build_outputs(),
            "metadata": self._build_metadata(),
        }
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount
        if self.name is not None:
            payload["name"] = self.name
        return payload

    @beartype
    def _start_impl(self, *, approve_amount: int | None = None, **kwargs: Any) -> None:
        """Submit the ABFE execution to the platform.

        Args:
            approve_amount: Spend cap forwarded to the platform. ``0`` requests
                a quote only; ``None`` runs immediately.
        """
        payload = self._make_payload(
            approve_amount=approve_amount,
            sync=False,
        )
        execution_dto = self.client.executions.create(  # ty:ignore[unresolved-attribute]
            data=payload,
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )

        if execution_dto.get("executionId") is None:
            msg = "Execution response must contain 'executionId'"
            raise ValueError(msg)

        self.update_from_dto(execution_dto)

    def get_results(self, **_kwargs: Any) -> pd.DataFrame | None:
        """Retrieve ABFE results as a DataFrame.

        Uses :meth:`~deeporigin.drug_discovery.execution.Execution.get_results`
        (results for this execution by id), then builds a one-row table from the
        first record's ``data`` payload. Keyword arguments are accepted for
        signature compatibility with the base class but are not forwarded.

        Returns:
            A DataFrame with ABFE results, or ``None`` if not yet available.

        Raises:
            ValueError: If no execution has been started.
        """
        self.sync()
        if not is_success_status(self.status):
            return None

        response = super().get_results()
        records = response.get("data") or []
        if not records:
            return None
        row = records[0].get("data")
        if not isinstance(row, dict) or not row:
            return None
        df = pd.json_normalize([row])
        drop_roots = frozenset({"binding_analysis", "solvation_analysis"})
        to_drop = [
            c for c in df.columns if c in drop_roots or c.split(".", 1)[0] in drop_roots
        ]
        if to_drop:
            df = df.drop(columns=to_drop)
        priority = ["protein_id", "ligand1_id", "total", "unit"]
        head = [c for c in priority if c in df.columns]
        tail = [c for c in df.columns if c not in head]
        return df[head + tail]

    @beartype
    def show_trajectory(
        self,
        *,
        step: Literal["md", "binding", "solvation"],
        window: int = 1,
        repeat: int = 1,
    ) -> Any:
        """Visualize an ABFE trajectory in a notebook using Mol*.

        Trajectory remote paths are read from this execution's data-platform
        results (same payload as ``client.results.get(compute_job_id=abfe.id)``):
        for ``binding`` or ``solvation``, the per-window
        ``solute_trajectory_20ps.xtc`` paths under ``binding_analysis`` /
        ``solvation_analysis``. For ``md``, the equilibration/production MD path
        under ``tool-runs/<id>/protein/ligand/simple_md/...`` is derived from
        those paths.

        Args:
            step: ``md`` for the post-prep MD segment; ``binding`` or
                ``solvation`` for a lambda window from the corresponding leg.
            window: Lambda window index (1-based). Ignored when ``step`` is
                ``md``.
            repeat: Repeat index from the tool results (matched to the
                ``repeat`` field when present, otherwise 1-based index into the
                analysis list).

        Returns:
            Notebook display output from :func:`deeporigin.utils.notebook.render_html`.

        Raises:
            ValueError: If the execution has not been started (no id).
            DeepOriginException: If the job is not succeeded, results lack paths,
                ``window`` is invalid, or no system PDB can be resolved.
        """
        if self.id is None:
            raise ValueError(
                "Cannot show trajectory: no execution has been started (id is None)."
            )

        if window < 1:
            raise DeepOriginException(
                title="Invalid window number",
                message="Window number must be greater than 0",
                fix="Please specify a window number greater than 0",
            ) from None

        self.sync()
        if not is_success_status(self.status):
            raise DeepOriginException(
                title="Job not complete",
                message=(
                    "Trajectory is only available after a successful run. "
                    f"Current status is {self.status!r}."
                ),
                fix="Wait until the execution status is Completed, then try again.",
            ) from None

        response = self.client.results.get(compute_job_id=self.id)
        records = response.get("data") or []
        if not records:
            raise DeepOriginException(
                title="No results for this execution",
                message="The data platform returned no result rows for this job.",
            ) from None

        row = records[0]
        data = row.get("data")
        if not isinstance(data, dict) or not data:
            raise DeepOriginException(
                title="No result payload",
                message="The first result record has no data field.",
            ) from None

        prepared = self.prepared_system
        if prepared.system_pdb_path:
            remote_pdb = prepared.system_pdb_path
        elif prepared.binding_xml_path:
            remote_pdb = str(Path(prepared.binding_xml_path).parent / "system.pdb")
        else:
            raise DeepOriginException(
                title="No system structure path",
                message="Cannot locate system.pdb: set prepared_system.system_pdb_path "
                "or binding_xml_path.",
            ) from None

        if step in ("binding", "solvation"):
            analysis_key = (
                "binding_analysis" if step == "binding" else "solvation_analysis"
            )
            blocks = data.get(analysis_key)
            if not isinstance(blocks, list):
                raise DeepOriginException(
                    title="Missing analysis in results",
                    message=f"Results do not contain a list at {analysis_key!r}.",
                ) from None

            block = _abfe_pick_analysis_block(blocks=blocks, repeat=repeat)
            traj = block.get("trajectories")
            if not isinstance(traj, dict):
                raise DeepOriginException(
                    title="Missing trajectories",
                    message=f"No trajectories map in results for {analysis_key!r}.",
                ) from None

            window_key = f"window_{window}"
            if window_key not in traj:
                valid = _abfe_sorted_window_numbers(trajectories=traj)
                raise DeepOriginException(
                    title="Invalid window number",
                    message=f"Valid windows are: {valid}",
                ) from None

            remote_xtc = traj[window_key]
            if not isinstance(remote_xtc, str) or not remote_xtc.strip():
                raise DeepOriginException(
                    title="Invalid trajectory path",
                    message=f"Results entry {window_key!r} is missing or not a path string.",
                ) from None
            remote_xtc = remote_xtc.strip()
        else:
            sample_path = _abfe_first_remote_trajectory_path(data=data)
            root = _abfe_tool_run_root(remote_trajectory_path=sample_path)
            remote_xtc = (
                f"{root}/protein/ligand/simple_md/simple_md/prod/"
                "_allatom_trajectory_40ps.xtc"
            )

        local_pdb = self.client.files.download(remote_pdb, lazy=True)
        local_xtc = self.client.files.download(remote_xtc, lazy=True)

        print(local_pdb)
        print(local_xtc)

        from deeporigin_molstar import JupyterViewer, ProteinViewer

        protein_viewer = ProteinViewer(data=local_pdb, format="pdb")
        html_content = protein_viewer.render_trajectory(local_xtc)

        JupyterViewer.visualize(html_content)

    @beartype
    def show_overlap_matrix(
        self,
        *,
        run: Literal["binding", "solvation"] = "binding",
        repeat: int = 1,
    ) -> None:
        """Display the overlap-matrix PNG for this execution in Jupyter.

        Reads the first data-platform result row for this job (same payload as
        ``client.results.get(compute_job_id=abfe.id)``), takes
        ``overlap_matrix_plot`` from ``binding_analysis`` or
        ``solvation_analysis`` for the chosen repeat, downloads via
        :meth:`deeporigin.platform.files.Files.download`, and renders with
        :class:`IPython.display.Image`.

        Args:
            run: Which leg of the calculation to show: ``"binding"`` or
                ``"solvation"``.
            repeat: Repeat index from the tool results (matched to the
                ``repeat`` field when present, otherwise 1-based index into the
                analysis list). Same semantics as :meth:`show_trajectory`.

        Raises:
            ValueError: If the execution has no platform id yet.
            DeepOriginException: If the run is not complete, results are missing,
                or no overlap-matrix plot path is present for the chosen leg.
        """
        if self.id is None:
            raise ValueError(
                "Cannot show overlap matrix: no execution has been started (id is None)."
            )

        self.sync()
        if not is_success_status(self.status):
            raise DeepOriginException(
                title="ABFE run is not complete",
                message=(
                    "Overlap matrices are only available after a successful run. "
                    f"Current status is {self.status!r}."
                ),
            ) from None

        response = self.client.results.get(compute_job_id=self.id)
        records = response.get("data") or []
        if not records:
            raise DeepOriginException(
                title="No overlap matrix found for this run",
                message=(
                    "Unable to show overlap matrix because there are no result "
                    "records for this execution."
                ),
            ) from None

        row = records[0]
        data = row.get("data")
        if not isinstance(data, dict) or not data:
            raise DeepOriginException(
                title="No overlap matrix found for this run",
                message="ABFE result data is missing or not in the expected shape.",
            ) from None

        analysis_key = "binding_analysis" if run == "binding" else "solvation_analysis"
        blocks = data.get(analysis_key)
        if not isinstance(blocks, list):
            raise DeepOriginException(
                title="No overlap matrix found for this run",
                message=f"Results do not contain a list at {analysis_key!r}.",
            ) from None

        block = _abfe_pick_analysis_block(blocks=blocks, repeat=repeat)

        remote_path = block.get("overlap_matrix_plot")
        if not isinstance(remote_path, str) or not remote_path.strip():
            raise DeepOriginException(
                title="No overlap matrix found for this run",
                message=(
                    "Unable to show overlap matrix because overlap_matrix_plot is "
                    f"not set for the {run} leg."
                ),
            ) from None

        local_path = self.client.files.download(remote_path.strip(), lazy=True)

        from IPython.display import Image, display

        display(Image(local_path))

    @beartype
    def show_convergence_time(
        self,
        *,
        run: Literal["binding", "solvation"] = "binding",
        repeat: int = 1,
    ) -> None:
        """Display the time-convergence PNG for this execution in Jupyter.

        Reads the first data-platform result row for this job (same payload as
        ``client.results.get(compute_job_id=abfe.id)``), takes ``convergence_plot``
        from ``binding_analysis`` or ``solvation_analysis`` for the chosen
        repeat, downloads via :meth:`deeporigin.platform.files.Files.download`,
        and renders with :class:`IPython.display.Image`.

        Args:
            run: Which leg of the calculation to show: ``"binding"`` or
                ``"solvation"``.
            repeat: Repeat index from the tool results (matched to the
                ``repeat`` field when present, otherwise 1-based index into the
                analysis list). Same semantics as :meth:`show_trajectory`.

        Raises:
            ValueError: If the execution has no platform id yet.
            DeepOriginException: If the run is not complete, results are missing,
                or no convergence plot path is present for the chosen leg.
        """
        if self.id is None:
            raise ValueError(
                "Cannot show convergence plot: no execution has been started (id is None)."
            )

        self.sync()
        if not is_success_status(self.status):
            raise DeepOriginException(
                title="ABFE run is not complete",
                message=(
                    "Convergence plots are only available after a successful run. "
                    f"Current status is {self.status!r}."
                ),
            ) from None

        response = self.client.results.get(compute_job_id=self.id)
        records = response.get("data") or []
        if not records:
            raise DeepOriginException(
                title="No convergence plot found for this run",
                message=(
                    "Unable to show convergence plot because there are no result "
                    "records for this execution."
                ),
            ) from None

        row = records[0]
        data = row.get("data")
        if not isinstance(data, dict) or not data:
            raise DeepOriginException(
                title="No convergence plot found for this run",
                message="ABFE result data is missing or not in the expected shape.",
            ) from None

        analysis_key = "binding_analysis" if run == "binding" else "solvation_analysis"
        blocks = data.get(analysis_key)
        if not isinstance(blocks, list):
            raise DeepOriginException(
                title="No convergence plot found for this run",
                message=f"Results do not contain a list at {analysis_key!r}.",
            ) from None

        block = _abfe_pick_analysis_block(blocks=blocks, repeat=repeat)

        remote_path = block.get("convergence_plot")
        if not isinstance(remote_path, str) or not remote_path.strip():
            raise DeepOriginException(
                title="No convergence plot found for this run",
                message=(
                    "Unable to show convergence plot because convergence_plot is "
                    f"not set for the {run} leg."
                ),
            ) from None

        local_path = self.client.files.download(remote_path.strip(), lazy=True)

        from IPython.display import Image, display

        display(Image(local_path))

    def _build_params(self) -> dict:
        """Construct the tool input parameters dict for the abfe-e2e-workflow tool."""
        return {
            # "mode": self.mode,
            **self.params.to_dict(prepared_system=self.prepared_system),
        }

    def __repr__(self) -> str:
        """Return a multi-line string representation of this ABFE execution.

        Shows the tool key and version, execution mode and name, plus the
        prepared-system identifiers (protein and ligand IDs). Each field
        appears on its own line for readability.
        """
        ps = getattr(self, "prepared_system", None)
        if ps is None:
            return super().__repr__()
        parts = ["ABFE("]
        parts.append(f"  tool_key={self.tool_key!r},")
        parts.append(f"  tool_version={self.tool_version!r},")
        # parts.append(f"  mode={self.mode!r},")
        parts.append(f"  name={self.name!r},")
        parts.append(f"  protein_id={ps.protein_id!r},")
        parts.append(f"  ligand1_id={ps.ligand1_id!r},")
        if ps.ligand2_id is not None:
            parts.append(f"  ligand2_id={ps.ligand2_id!r},")
        parts.append(")")
        return "\n".join(parts)

    def _build_metadata(self) -> dict:
        """Construct execution metadata."""
        metadata = {}
        if self.prepared_system.protein_id:
            metadata["protein_id"] = self.prepared_system.protein_id
        if self.prepared_system.ligand1_id:
            metadata["ligand1_id"] = self.prepared_system.ligand1_id
        return metadata

    def _build_outputs(self) -> dict:
        """Construct the output file specification for the ABFE tool."""
        return {}
