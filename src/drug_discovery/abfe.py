"""ABFE -- class to run and control absolute binding free energy calculations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Self

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import AsyncExecutableMixin
from deeporigin.drug_discovery.fep_common import (
    ABFEParams,
    _fep_params_from_inputs,
    _pose_tool_ref,
    _prepared_system_tool_ref,
    _simulation_blocks,
)
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.pose import Pose
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status

ABFEWorkflowStep = Literal["system-prep", "abfe"]


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
def _abfe_default_name_from_entities(
    *,
    protein: Protein,
    pose: Pose,
    client: DeepOriginClient,
) -> str:
    """Build a short human-readable label for a combined ABFE execution.

    Args:
        protein: Protein used for system preparation.
        pose: Pose used for system preparation.
        client: API client used to resolve entities.

    Returns:
        A string such as ``ABFE: BRD4 with CCO``.
    """
    protein_id = protein.id
    ligand_id = pose.ligand_id
    protein_id_str = (
        str(protein_id).strip()
        if protein_id is not None and str(protein_id).strip()
        else ""
    )
    ligand_id_str = (
        str(ligand_id).strip() if ligand_id and str(ligand_id).strip() else ""
    )

    if protein_id_str:
        try:
            protein_label = _protein_display_name_from_entity(
                entity=client.entities.get_protein(id=protein_id_str),
                fallback_id=protein_id_str,
            )
        except Exception:
            protein_label = protein_id_str
    else:
        protein_label = protein.name or "unknown protein"

    if ligand_id_str:
        try:
            ligand_label = _ligand_display_label_from_entity(
                entity=client.entities.get_ligand(id=ligand_id_str),
                fallback_id=ligand_id_str,
            )
        except Exception:
            ligand_label = ligand_id_str
    else:
        ligand_label = pose.name or pose.smiles or pose.id or "unknown pose"

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


@beartype
def _abfe_filtered_records(
    response: dict[str, Any],
    *,
    tool_key: str,
) -> list[dict[str, Any]]:
    """Return result records whose ``tool_key`` matches the ABFE tool."""
    records = response.get("data") or []
    return [
        record
        for record in records
        if isinstance(record, dict) and record.get("tool_key") == tool_key
    ]


@beartype
def _abfe_first_result_data(
    response: dict[str, Any],
    *,
    tool_key: str,
) -> dict[str, Any] | None:
    """Return the ``data`` payload from the first ABFE result record."""
    for record in _abfe_filtered_records(response, tool_key=tool_key):
        data = record.get("data")
        if isinstance(data, dict) and data:
            return data
    return None


@beartype
def _abfe_results_dataframe(
    response: dict[str, Any],
    *,
    tool_key: str,
) -> pd.DataFrame | None:
    """Build a one-row summary table from ABFE result records.

    Combined workflow executions also store system-prep rows; those are excluded.
    """
    data = _abfe_first_result_data(response, tool_key=tool_key)
    if data is None:
        return None
    df = pd.json_normalize([data])
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


def _pose_from_tool_input(ref: dict[str, Any]) -> Pose:
    """Rehydrate a pose from an ABFE ``pose1`` reference."""
    pose_id = ref.get("id")
    file_path = ref.get("file_path")
    if pose_id is None and not file_path:
        msg = "Pose input must include 'id' or 'file_path'."
        raise ValueError(msg)
    return Pose(
        ligand_id=str(ref.get("ligand_id") or ""),
        id=str(pose_id) if pose_id is not None else None,
        remote_path=str(file_path) if file_path else None,
        name=ref.get("name"),
        smiles=ref.get("smiles"),
        protein_id=str(ref["protein_id"]) if ref.get("protein_id") else None,
    )


class ABFE(Execution, AsyncExecutableMixin, NotebookWatchMixin):
    """ABFE workflow (``deeporigin.abfe-end-to-end``).

    Platform ``steps`` are inferred from constructor inputs (see :meth:`_post_init`):

    - ``["system-prep", "abfe"]``: ``protein`` + ``pose`` / ``pose1``
    - ``["abfe"]``: ``prepared_system``

    Attributes:
        steps: Ordered workflow steps forwarded to the platform tool.
        name: Optional execution label (auto-generated for combined mode).
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["abfe"]["tool_key"]

    @beartype
    def __init__(
        self,
        *,
        protein: Protein | None = None,
        pose: Pose | None = None,
        pose1: Pose | None = None,
        prepared_system: PreparedSystem | None = None,
        params: ABFEParams | None = None,
        add_h_atoms: bool = False,
        protonate_protein: bool = False,
        retain_waters: bool = True,
        padding: float = 1.0,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["abfe"]["tool_version"],
        client: DeepOriginClient | None = None,
        name: str | None = None,
    ) -> None:
        """Create an ABFE workflow execution.

        Platform ``steps`` are inferred in :meth:`_post_init`:

        - ``prepared_system`` -> ``["abfe"]`` (FEP on existing system)
        - ``protein`` + ``pose`` / ``pose1`` -> ``["system-prep", "abfe"]``

        Exactly one of ``prepared_system`` or (``protein`` + pose) must be
        provided. ``pose`` and ``pose1`` are mutually exclusive aliases.

        Args:
            protein: Protein for combined system-prep + ABFE mode.
            pose: Pose for combined mode (alias for ``pose1``).
            pose1: Pose for combined mode.
            prepared_system: Prepared system for ABFE-only steps.
            params: FEP simulation parameters.
            add_h_atoms: Add hydrogens to pose during prep.
            protonate_protein: Protonate protein during prep.
            retain_waters: Retain crystal waters during prep.
            padding: Solvation box padding (nm) during prep.
            tool_version: Platform tool version pin.
            client: Optional API client.
            name: Optional execution label. Auto-generated for combined mode.

        Raises:
            ValueError: When inputs are missing or mutually exclusive.
        """
        super().__init__(client=client)
        self.tool_version = tool_version
        self.protein = protein
        if pose is not None and pose1 is not None:
            raise ValueError("Provide only one of pose or pose1, not both.")
        self.pose1 = pose if pose is not None else pose1
        self.prepared_system = prepared_system
        self._params = params if params is not None else ABFEParams()
        self.add_h_atoms = add_h_atoms
        self.protonate_protein = protonate_protein
        self.retain_waters = retain_waters
        self.padding = padding
        self.name = name
        self._post_init()

    def _post_init(self) -> None:
        """Infer platform ``steps`` from constructor inputs and validate."""
        has_prep = self.prepared_system is not None
        has_combined = self.protein is not None and self.pose1 is not None
        mode_count = sum([has_prep, has_combined])

        if mode_count != 1:
            raise ValueError(
                "Exactly one of prepared_system or (protein and pose/pose1) "
                "must be provided."
            )
        if has_prep:
            self.steps: list[ABFEWorkflowStep] = ["abfe"]
        else:
            self.steps = ["system-prep", "abfe"]
        self._validate_step_inputs()

        if has_combined and self.name is None:
            assert self.protein is not None
            assert self.pose1 is not None
            self.name = _abfe_default_name_from_entities(
                protein=self.protein,
                pose=self.pose1,
                client=self.client,
            )

    @property
    def params(self) -> ABFEParams:
        """FEP calculation parameters (read-only)."""
        return self._params

    @params.setter
    def params(self, value: ABFEParams) -> None:
        """Prevent modification of params after construction."""
        raise AttributeError("params can only be set in the constructor")

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct an ABFE instance from an execution DTO.

        Rehydrates ``steps``, prep inputs, ``prepared_system``, and ``_params`` from
        stored ``userInputs`` (falling back to ``inputs`` for older payloads).

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client. Uses the default if not provided.

        Returns:
            A fully-hydrated ABFE instance with status from the DTO.

        Raises:
            ValueError: When ``steps`` is missing or unsupported.
        """
        instance = super().from_dto(dto, client=client)
        inputs: dict[str, Any] = (
            instance._dto.get("userInputs")  # ty:ignore[unresolved-attribute]
            or instance._dto.get("inputs")  # ty:ignore[unresolved-attribute]
            or {}
        )

        raw_steps = inputs.get("steps")
        if not raw_steps:
            msg = "Missing 'steps' in execution userInputs."
            raise ValueError(msg)
        instance.steps = list(raw_steps)

        if instance.steps == ["system-prep"]:
            msg = (
                "Legacy steps=['system-prep'] executions are no longer supported "
                "by ABFE.from_dto()."
            )
            raise ValueError(msg)

        instance.protein = None
        instance.pose1 = None
        instance.prepared_system = None
        instance.add_h_atoms = bool(inputs.get("add_H_atoms", False))
        instance.protonate_protein = bool(inputs.get("protonate_protein", False))
        instance.retain_waters = bool(inputs.get("retain_waters", True))
        instance.padding = float(inputs.get("padding", 1.0))
        instance._params = (
            _fep_params_from_inputs(inputs)
            if "abfe" in instance.steps
            else ABFEParams()
        )

        if "system-prep" in instance.steps:
            protein_input = inputs.get("protein", {})
            protein_id = protein_input.get("id")
            if protein_id is not None:
                instance.protein = Protein.from_id(
                    str(protein_id),
                    client=instance.client,
                    download=False,
                    remote_path_override=protein_input.get("file_path"),
                )
            elif protein_input.get("file_path"):
                instance.protein = Protein(
                    name="rehydrated",
                    id=None,
                    remote_path=str(protein_input["file_path"]),
                )

            pose_input = inputs.get("pose1") or inputs.get("ligand1") or {}
            if pose_input:
                instance.pose1 = _pose_from_tool_input(pose_input)

        if instance.steps == ["abfe"]:
            prepared_system_input = inputs.get("prepared_system", {})
            instance.prepared_system = PreparedSystem(
                binding_xml_path=prepared_system_input.get("binding_xml_file_path", ""),
                solvation_xml_path=prepared_system_input.get(
                    "solvation_xml_ligand_file_path", ""
                ),
                system_pdb_path="",
                solute_pdb_path=prepared_system_input.get("solute_pdb_file_path"),
                protein_id=prepared_system_input.get("protein_id"),
                ligand1_id=prepared_system_input.get("ligand1_id"),
                ligand2_id=prepared_system_input.get("ligand2_id"),
            )

        return instance

    @classmethod
    def from_id(
        cls,
        id: str,
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct an ABFE instance from an existing platform execution ID.

        Fetches the execution record via the API and delegates to :meth:`from_dto`.

        Args:
            id: Platform execution ID.
            client: Optional API client. Uses the default if not provided.

        Returns:
            A fully-hydrated ABFE instance with status synced from the platform.
        """
        return super().from_id(id, client=client)

    def _validate_step_inputs(self) -> None:
        """Validate constructor arguments for the selected workflow steps."""
        if "system-prep" in self.steps:
            if self.protein is None:
                raise ValueError(f"protein is required for steps={self.steps!r}.")
            if self.pose1 is None:
                raise ValueError(f"pose/pose1 is required for steps={self.steps!r}.")
        if self.steps == ["abfe"] and self.prepared_system is None:
            raise ValueError("prepared_system is required for steps=['abfe'].")

    def _ensure_synced_inputs(self) -> None:
        """Sync protein and pose before submission."""
        client = self.client
        if self.protein is not None:
            self.protein.sync(lazy=True, client=client)
            self.protein.ensure_remote_path(client=client, label="Protein")
        if self.pose1 is not None and "system-prep" in self.steps:
            self.pose1.sync(lazy=True, client=client)
            self.pose1.ensure_remote_path(client=client, label="Pose")

    def _build_params(self) -> dict[str, Any]:
        """Construct workflow input parameters for ``deeporigin.abfe-end-to-end``."""
        out: dict[str, Any] = {"steps": self.steps}
        if "system-prep" in self.steps:
            assert self.protein is not None
            assert self.pose1 is not None
            out["protein"] = {
                "id": self.protein.id,
                "file_path": self.protein.remote_path,
            }
            out["pose1"] = _pose_tool_ref(self.pose1)
            out.update(
                {
                    "add_H_atoms": self.add_h_atoms,
                    "protonate_protein": self.protonate_protein,
                    "retain_waters": self.retain_waters,
                    "padding": self.padding,
                }
            )
        if self.steps == ["abfe"]:
            assert self.prepared_system is not None
            out["prepared_system"] = _prepared_system_tool_ref(self.prepared_system)
        if "abfe" in self.steps:
            out.update(_simulation_blocks(self._params))
        return out

    def _make_payload(
        self,
        *,
        approve_amount: int | None,
        sync: bool,  # noqa: ARG002
    ) -> dict[str, Any]:
        """Build create payload for ``executions.create``."""
        payload: dict[str, Any] = {
            "inputs": self._build_params(),
            "outputs": {},
        }
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount
        if self.name is not None:
            payload["name"] = self.name
        return payload

    @beartype
    def _start_impl(self, *, approve_amount: int | None = None, **kwargs: Any) -> None:
        """Submit the ABFE workflow execution to the platform.

        Args:
            approve_amount: Spend cap forwarded to the platform. ``0`` requests
                a quote only; ``None`` runs immediately.
        """
        self._ensure_synced_inputs()
        payload = self._make_payload(approve_amount=approve_amount, sync=False)
        execution_dto = self._create_execution(data=payload)

        if execution_dto.get("executionId") is None:
            msg = "Execution response must contain 'executionId'"
            raise ValueError(msg)

        self.update_from_dto(execution_dto)

    def get_results(self, **_kwargs: Any) -> pd.DataFrame | None:
        """Retrieve ABFE results as a DataFrame.

        Uses :meth:`~deeporigin.drug_discovery.execution.Execution.get_results`
        (results for this execution by id), then builds a one-row table from the
        first ``deeporigin.abfe-end-to-end`` record's ``data`` payload. System-prep rows
        from combined runs are excluded. Keyword arguments are accepted for
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
        return _abfe_results_dataframe(response, tool_key=self.tool_key)

    @beartype
    def get_prepared_system(
        self,
        *,
        ligand1_id: str | None = None,
    ) -> PreparedSystem:
        """Load a :class:`PreparedSystem` from system-prep results for this execution.

        Fetches prepared-system rows scoped to this ABFE execution via
        :meth:`~deeporigin.drug_discovery.structures.prepared_system.PreparedSystem.from_result`.
        When multiple rows match, returns the first.

        Args:
            ligand1_id: Optional ligand ID to filter by.

        Returns:
            A :class:`PreparedSystem` with paths and metadata from the result row.

        Raises:
            ValueError: If no execution has been started.
            DeepOriginException: If no matching system-prep results exist yet.
        """
        if self.id is None:
            raise ValueError(
                "Cannot get prepared system: no execution has been started (id is None)."
            )

        self.sync()

        try:
            systems = PreparedSystem.from_result(
                compute_job_id=self.id,
                ligand1_id=ligand1_id,
                client=self.client,
            )
        except ValueError as exc:
            raise DeepOriginException(
                title="No system-prep results found",
                message=(
                    "No system-prep results found for this ABFE execution. "
                    "Wait for the system-prep step to complete, or pass "
                    "ligand1_id to disambiguate."
                ),
            ) from exc

        if not systems:
            raise DeepOriginException(
                title="No system-prep results found",
                message=(
                    "No system-prep results found for this ABFE execution. "
                    "Wait for the system-prep step to complete, or pass "
                    "ligand1_id to disambiguate."
                ),
            )

        return systems[0]

    def _resolved_prepared_system(self) -> PreparedSystem:
        """Return ``prepared_system`` or load it from execution results."""
        if self.prepared_system is not None:
            return self.prepared_system
        return self.get_prepared_system()

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
        data = _abfe_first_result_data(response, tool_key=self.tool_key)
        if data is None:
            raise DeepOriginException(
                title="No ABFE results for this execution",
                message=(
                    "The data platform returned no ABFE result rows for this job. "
                    "System-prep-only rows are ignored."
                ),
            ) from None

        prepared = self._resolved_prepared_system()
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
        data = _abfe_first_result_data(response, tool_key=self.tool_key)
        if data is None:
            raise DeepOriginException(
                title="No overlap matrix found for this run",
                message=(
                    "Unable to show overlap matrix because there are no ABFE result "
                    "records for this execution."
                ),
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
        data = _abfe_first_result_data(response, tool_key=self.tool_key)
        if data is None:
            raise DeepOriginException(
                title="No convergence plot found for this run",
                message=(
                    "Unable to show convergence plot because there are no ABFE result "
                    "records for this execution."
                ),
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

    def __repr__(self) -> str:
        """Return a concise multi-line representation."""
        parts = ["ABFE("]
        if self.id is not None:
            parts.append(f"  id={self.id!r},")
        if self.status is not None:
            parts.append(f"  status={self.status!r},")
        ps = getattr(self, "prepared_system", None)
        parts.extend(
            [
                f"  steps={self.steps!r},",
                f"  tool_key={self.tool_key!r},",
                f"  has_prepared_system={ps is not None},",
                f"  has_protein={getattr(self, 'protein', None) is not None},",
                ")",
            ]
        )
        return "\n".join(parts)


__all__ = ["ABFE", "ABFEParams", "ABFEWorkflowStep"]
