"""RBFE -- batch relative binding free energy workflow executions."""

from __future__ import annotations

from typing import Any, Literal, Self

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import AsyncExecutableMixin
from deeporigin.drug_discovery.fep_common import (
    RBFEParams,
    _fep_params_from_inputs,
    _pose_tool_ref,
    _prepared_system_tool_ref,
    _protein_from_tool_input,
    _simulation_blocks,
)
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.pose import Pose, PoseSet
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS

RBFEWorkflowStep = Literal["konnektor", "system-prep", "rbfe", "cycle-closure"]
KonnektorNetworkType = Literal["star", "mst", "cyclic"]
RBFEAnchorInput = dict[str, str | int | float]
_RBFE_STEP_PLANS: tuple[list[str], ...] = (
    ["system-prep"],
    ["system-prep", "rbfe"],
    ["rbfe"],
    ["konnektor", "system-prep", "rbfe"],
    ["system-prep", "rbfe", "cycle-closure"],
    ["rbfe", "cycle-closure"],
    ["konnektor", "system-prep", "rbfe", "cycle-closure"],
)


def _ligand_from_pair_input(ref: dict[str, Any], *, client: DeepOriginClient) -> Ligand:
    """Rehydrate a ligand from a pre-3.0 RBFE ``pairs[]`` ligand reference."""
    lig_id = ref.get("id")
    file_path = ref.get("file_path")
    if lig_id is not None:
        assert client.entities is not None
        data = client.entities.get_ligand(id=str(lig_id))
        return Ligand._from_platform_record(
            data=data,
            client=client,
            download=False,
            mol_file_override=str(file_path) if file_path else None,
        )
    if not file_path:
        msg = "Ligand pair input must include 'id' or 'file_path'."
        raise ValueError(msg)
    return Ligand.from_remote_file(str(file_path), client=client, lazy=True)


def _pose_from_pair_input(ref: dict[str, Any]) -> Pose:
    """Rehydrate a pose from an RBFE ``pairs[]`` / ``poses[]`` reference."""
    pose_id = ref.get("id")
    file_path = ref.get("file_path")
    if pose_id is None and not file_path:
        msg = "Pose pair input must include 'id' or 'file_path'."
        raise ValueError(msg)
    return Pose(
        ligand_id=str(ref.get("ligand_id") or ""),
        id=str(pose_id) if pose_id is not None else None,
        remote_path=str(file_path) if file_path else None,
        name=ref.get("name"),
        smiles=ref.get("smiles"),
        protein_id=str(ref["protein_id"]) if ref.get("protein_id") else None,
    )


def _format_ddg(*, total: Any, unit: str | None) -> str | None:
    """Format RBFE ΔΔG from a result ``data`` payload."""
    if total is None:
        return None
    unit_str = (unit or "").strip()
    if unit_str:
        return f"{total} {unit_str}"
    return str(total)


def _cycle_closure_row_from_item(item: dict[str, Any]) -> dict[str, Any]:
    """Extract one cycle-closure summary row from a result item."""
    return {
        "pose_id": item.get("pose_id"),
        "ligand_id": item.get("ligand_id"),
        "dG": item.get("dG"),
        "unit": item.get("unit"),
        "cluster": item.get("cluster"),
    }


def _cycle_closure_rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse cycle-closure rows from a single data-platform result payload."""
    nested = payload.get("cycleclosureresults")
    if isinstance(nested, list):
        return [
            _cycle_closure_row_from_item(item)
            for item in nested
            if isinstance(item, dict)
        ]
    if ("pose_id" in payload or "ligand_id" in payload) and "dG" in payload:
        return [_cycle_closure_row_from_item(payload)]
    return []


def _cycle_closure_results_dataframe(
    response: dict[str, Any],
    *,
    tool_key: str,
) -> pd.DataFrame | None:
    """Build a summary table from cycle-closure result rows."""
    records = response.get("data") or []
    rows: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("tool_key") != tool_key:
            continue
        payload = record.get("data", record)
        if not isinstance(payload, dict):
            continue
        rows.extend(_cycle_closure_rows_from_payload(payload))
    if not rows:
        return None
    return pd.DataFrame(rows)


def _rbfe_results_dataframe(
    response: dict[str, Any],
    *,
    tool_key: str,
) -> pd.DataFrame | None:
    """Build a summary table from the pairwise RBFE rows of a results response.

    Cycle-closure and prepared-system rows share the tool key; only edge rows
    carry ``total``.
    """
    records = response.get("data") or []
    rows: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("tool_key") != tool_key:
            continue
        payload = record.get("data")
        if not isinstance(payload, dict) or "total" not in payload:
            continue
        rows.append(
            {
                "protein_id": payload.get("protein_id"),
                "pose1_id": payload.get("pose1_id"),
                "pose2_id": payload.get("pose2_id"),
                "ligand1_id": payload.get("ligand1_id"),
                "ligand2_id": payload.get("ligand2_id"),
                "ddG": _format_ddg(
                    total=payload.get("total"),
                    unit=payload.get("unit"),
                ),
            }
        )
    if not rows:
        return None
    return pd.DataFrame(rows)


class RBFE(Execution, AsyncExecutableMixin, NotebookWatchMixin):
    """Batch RBFE workflow (``deeporigin.rbfe``).

    Platform ``steps`` are inferred from constructor inputs (see :meth:`_post_init`)
    unless passed explicitly:

    - ``["konnektor", "system-prep", "rbfe"]``: ``protein`` + ``poses``
    - ``["system-prep", "rbfe"]``: ``protein`` + ``pairs``
    - ``["rbfe"]``: ``prepared_systems``
    - Append ``cycle-closure`` when ``exp_abfe`` and/or ``fep_abfe`` anchors are set

    Attributes:
        steps: Ordered workflow steps forwarded to the platform tool.
        name: Optional execution label.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["rbfe"]["tool_key"]
    tool_version: str = TOOL_KEYS_AND_VERSIONS["rbfe"]["tool_version"]

    @beartype
    def __init__(
        self,
        *,
        protein: Protein | None = None,
        poses: PoseSet | list[Pose] | None = None,
        pairs: list[tuple[Pose, Pose]] | None = None,
        prepared_systems: list[PreparedSystem] | None = None,
        network_type: KonnektorNetworkType = "mst",
        params: RBFEParams | None = None,
        add_h_atoms: bool = True,
        protonate_protein: bool = False,
        retain_waters: bool = True,
        padding: float = 1.0,
        exp_abfe: list[RBFEAnchorInput] | None = None,
        fep_abfe: list[RBFEAnchorInput] | None = None,
        steps: list[RBFEWorkflowStep] | None = None,
        tool_version: str | None = None,
        client: DeepOriginClient | None = None,
        name: str | None = None,
    ) -> None:
        """Create an RBFE batch workflow execution.

        Platform ``steps`` are inferred in :meth:`_post_init`:

        - ``prepared_systems`` -> ``["rbfe"]`` (FEP on existing systems)
        - ``protein`` + ``pairs`` -> ``["system-prep", "rbfe"]``
        - ``protein`` + ``poses`` -> ``["konnektor", "system-prep", "rbfe"]``

        Exactly one of ``poses``, ``pairs``, or ``prepared_systems`` must be
        provided.

        Args:
            protein: Shared protein for prep modes (required with ``poses`` or
                ``pairs``).
            poses: Poses for Konnektor network planning (min 2, one per ligand).
            pairs: Explicit pose pairs for system-prep steps.
            prepared_systems: Prepared systems for RBFE-only steps.
            network_type: Konnektor topology when ``poses`` is provided.
            params: FEP simulation parameters for plans that include ``rbfe``.
            add_h_atoms: Add hydrogens to poses during prep (default True;
                no-op for poses that already have them).
            protonate_protein: Protonate protein during prep.
            retain_waters: Retain crystal waters during prep.
            padding: Solvation box padding (nm) during prep.
            exp_abfe: Experimental anchors for cycle closure, each
                ``{"pose_id", "dG", "std"?, "abfe_result_id"?}``.
            fep_abfe: FEP-ABFE anchors for cycle closure, same shape as
                ``exp_abfe``; :meth:`ABFE.to_anchor` builds one from an ABFE run.
            steps: Explicit workflow steps, e.g. ``["system-prep"]`` to only
                prepare the systems. Inferred from the inputs when omitted.
            tool_version: Platform tool version pin.
            client: Optional API client.
            name: Optional execution label.

        Raises:
            ValueError: When inputs are missing or mutually exclusive, or
                ``steps`` is not a supported plan.
        """
        super().__init__(client=client, tool_version=tool_version)
        self.exp_abfe = list(exp_abfe or [])
        self.fep_abfe = list(fep_abfe or [])
        self.protein = protein
        self.poses = list(poses) if poses is not None else []
        self.pairs = pairs or []
        self.prepared_systems = prepared_systems or []
        self.network_type = network_type
        self._params = params if params is not None else RBFEParams()
        self.add_h_atoms = add_h_atoms
        self.protonate_protein = protonate_protein
        self.retain_waters = retain_waters
        self.padding = padding
        self.name = name
        self._explicit_steps = list(steps) if steps is not None else None
        self._post_init()

    def _post_init(self) -> None:
        """Infer platform ``steps`` from constructor inputs and validate."""
        has_poses = bool(self.poses)
        has_pairs = bool(self.pairs)
        has_prep = bool(self.prepared_systems)
        mode_count = sum([has_poses, has_pairs, has_prep])

        if mode_count != 1:
            raise ValueError(
                "Exactly one of poses, pairs, or prepared_systems must be provided."
            )
        if self._explicit_steps is not None:
            self._check_explicit_steps(self._explicit_steps)
            self.steps: list[RBFEWorkflowStep] = self._explicit_steps
        else:
            if has_prep:
                self.steps = ["rbfe"]
            elif has_poses:
                self.steps = ["konnektor", "system-prep", "rbfe"]
            else:
                self.steps = ["system-prep", "rbfe"]
            if (self.exp_abfe or self.fep_abfe) and "cycle-closure" not in self.steps:
                self.steps = [*self.steps, "cycle-closure"]
        self._validate_step_inputs()

    def _check_explicit_steps(self, steps: list[RBFEWorkflowStep]) -> None:
        """Reject unsupported plans and anchors that the plan would drop."""
        if steps not in _RBFE_STEP_PLANS:
            raise ValueError(
                f"Unsupported steps={steps!r}; use one of {list(_RBFE_STEP_PLANS)!r}."
            )
        if (self.exp_abfe or self.fep_abfe) and "cycle-closure" not in steps:
            raise ValueError(
                "exp_abfe/fep_abfe need 'cycle-closure' in steps; add it or "
                "drop the anchors."
            )

    def _uses_prepared_systems(self) -> bool:
        """Whether RBFE runs on given prepared systems (no system-prep step)."""
        return "rbfe" in self.steps and "system-prep" not in self.steps

    @property
    def params(self) -> RBFEParams:
        """FEP calculation parameters (read-only)."""
        return self._params

    @params.setter
    def params(self, value: RBFEParams) -> None:
        """Prevent modification of params after construction."""
        raise AttributeError("params can only be set in the constructor")

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct an RBFE instance from an execution DTO.

        Rehydrates ``steps``, prep inputs, ``prepared_systems``, and ``_params`` from
        stored ``userInputs`` (falling back to ``inputs`` for older payloads).

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client. Uses the default if not provided.

        Returns:
            A fully-hydrated RBFE instance with status from the DTO.
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
        instance._explicit_steps = list(raw_steps)

        instance.protein = None
        instance.poses = []
        instance.pairs = []
        instance.prepared_systems = []
        raw_network_type = inputs.get("network_type", "mst")
        if raw_network_type not in ("star", "mst", "cyclic"):
            raw_network_type = "mst"
        instance.network_type = raw_network_type
        instance.add_h_atoms = bool(inputs.get("add_H_atoms", True))
        instance.protonate_protein = bool(inputs.get("protonate_protein", False))
        instance.retain_waters = bool(inputs.get("retain_waters", True))
        instance.padding = float(inputs.get("padding", 1.0))
        instance.exp_abfe = [
            dict(item) for item in inputs.get("exp_abfe", []) if isinstance(item, dict)
        ]
        instance.fep_abfe = [
            dict(item) for item in inputs.get("fep_abfe", []) if isinstance(item, dict)
        ]
        instance._params = (
            _fep_params_from_inputs(inputs, params_cls=RBFEParams)
            if "rbfe" in instance.steps
            else RBFEParams()
        )

        if "konnektor" in instance.steps:
            instance.poses = [
                _pose_from_pair_input(ref)
                for ref in inputs.get("poses", [])
                if isinstance(ref, dict)
            ]
            # Pre-3.0 executions planned the network over ligands.
            instance.poses += [
                Pose(
                    ligand_id=str(ref.get("id") or ""), remote_path=ref.get("file_path")
                )
                for ref in inputs.get("ligands", [])
                if isinstance(ref, dict)
            ]

        if "system-prep" in instance.steps:
            protein_input = inputs.get("protein", {})
            if isinstance(protein_input, dict) and protein_input:
                instance.protein = _protein_from_tool_input(
                    protein_input,
                    client=instance.client,
                )

            if "konnektor" not in instance.steps:
                instance.pairs = []
                for pair in inputs.get("pairs", []):
                    if not isinstance(pair, dict):
                        continue
                    if "pose1" in pair and "pose2" in pair:
                        instance.pairs.append(
                            (
                                _pose_from_pair_input(pair["pose1"]),
                                _pose_from_pair_input(pair["pose2"]),
                            )
                        )
                    elif "ligand1" in pair and "ligand2" in pair:
                        # Legacy executions: rehydrate ligands as pose stubs.
                        lig1 = _ligand_from_pair_input(
                            pair["ligand1"], client=instance.client
                        )
                        lig2 = _ligand_from_pair_input(
                            pair["ligand2"], client=instance.client
                        )
                        instance.pairs.append(
                            (
                                Pose(
                                    ligand_id=str(lig1.id or ""),
                                    id=lig1.id,
                                    remote_path=lig1.remote_path,
                                    smiles=lig1.smiles,
                                    name=lig1.name,
                                ),
                                Pose(
                                    ligand_id=str(lig2.id or ""),
                                    id=lig2.id,
                                    remote_path=lig2.remote_path,
                                    smiles=lig2.smiles,
                                    name=lig2.name,
                                ),
                            )
                        )

        if instance._uses_prepared_systems() or inputs.get("prepared_systems"):
            instance.prepared_systems = [
                PreparedSystem(
                    binding_xml_path=ps.get("binding_xml_file_path", ""),
                    solvation_xml_path=ps.get("solvation_xml_ligand_file_path", ""),
                    system_pdb_path=ps.get("system_pdb_file_path", ""),
                    solute_pdb_path=ps.get("solute_pdb_file_path"),
                    protein_id=ps.get("protein_id"),
                    ligand1_id=ps.get("ligand1_id"),
                    ligand2_id=ps.get("ligand2_id"),
                    pose1_id=ps.get("pose1_id") or ps.get("ligand1_pose_id"),
                    pose2_id=ps.get("pose2_id") or ps.get("ligand2_pose_id"),
                )
                for ps in inputs.get("prepared_systems", [])
                if isinstance(ps, dict)
            ]

        return instance

    @classmethod
    def from_id(
        cls,
        id: str,
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct an RBFE instance from an existing platform execution ID.

        Fetches the execution record via the API and delegates to :meth:`from_dto`.

        Args:
            id: Platform execution ID.
            client: Optional API client. Uses the default if not provided.

        Returns:
            A fully-hydrated RBFE instance with status synced from the platform.
        """
        return super().from_id(id, client=client)

    def _validate_step_inputs(self) -> None:
        """Validate constructor arguments for the selected workflow steps."""
        if "konnektor" in self.steps:
            self._validate_konnektor_inputs()
        elif "system-prep" in self.steps:
            self._validate_system_prep_inputs()
        if self._uses_prepared_systems() and not self.prepared_systems:
            raise ValueError(f"prepared_systems is required for steps={self.steps!r}.")
        if "cycle-closure" in self.steps:
            self._validate_cycle_closure_inputs()

    def _validate_konnektor_inputs(self) -> None:
        """Validate inputs for Konnektor workflow steps."""
        if self.protein is None:
            raise ValueError(f"protein is required for steps={self.steps!r}.")
        if len(self.poses) < 2:
            raise ValueError(
                f"poses requires at least two poses for steps={self.steps!r}."
            )

    def _validate_system_prep_inputs(self) -> None:
        """Validate inputs for system-prep workflow steps."""
        if self.protein is None:
            raise ValueError(f"protein is required for steps={self.steps!r}.")
        if not self.pairs:
            raise ValueError(f"pairs is required for steps={self.steps!r}.")

    def _validate_cycle_closure_inputs(self) -> None:
        """Validate cycle-closure step ordering and anchor payloads."""
        if "rbfe" not in self.steps:
            raise ValueError("cycle-closure requires 'rbfe' in steps.")
        if self.steps[-1] != "cycle-closure":
            raise ValueError("cycle-closure must be the final workflow step.")
        if not (self.exp_abfe or self.fep_abfe):
            raise ValueError(
                "exp_abfe or fep_abfe is required when steps include 'cycle-closure'."
            )
        self._validate_cycle_closure_anchors()

    def _validate_cycle_closure_anchors(self) -> None:
        """Validate anchor payloads before cycle-closure submission."""
        for label, anchors in (
            ("exp_abfe", self.exp_abfe),
            ("fep_abfe", self.fep_abfe),
        ):
            for anchor in anchors:
                pose_id = anchor.get("pose_id")
                if not isinstance(pose_id, str) or not pose_id:
                    raise ValueError(
                        f"{label} entries require a non-empty string 'pose_id'."
                    )
                if not isinstance(anchor.get("dG"), (int, float)):
                    raise ValueError(f"{label} entries require a numeric 'dG' value.")

    def _ensure_synced_inputs(self) -> None:
        """Sync protein and poses before submission."""
        client = self.client
        if self.protein is not None:
            self._sync_entity_if_needed(self.protein, client=client, label="Protein")
        if "konnektor" in self.steps:
            for pose in self.poses:
                self._sync_entity_if_needed(pose, client=client, label="Pose")
        for pose1, pose2 in self.pairs:
            self._sync_entity_if_needed(pose1, client=client, label="Pose")
            self._sync_entity_if_needed(pose2, client=client, label="Pose")

    @staticmethod
    def _sync_entity_if_needed(
        entity: Protein | Ligand | Pose,
        *,
        client: DeepOriginClient,
        label: str,
    ) -> None:
        """Sync an entity only when platform metadata is incomplete."""
        if entity.remote_path is None or entity.id is None:
            entity.sync(lazy=True, client=client)
        entity.ensure_remote_path(client=client, label=label)

    def _build_params(self) -> dict[str, Any]:
        """Construct workflow input parameters for ``deeporigin.rbfe``."""
        out: dict[str, Any] = {"steps": self.steps}
        if "konnektor" in self.steps:
            out["poses"] = [_pose_tool_ref(pose) for pose in self.poses]
            out["network_type"] = self.network_type
        if "system-prep" in self.steps:
            assert self.protein is not None
            out["protein"] = {
                "id": self.protein.id,
                "file_path": self.protein.remote_path,
            }
            if "konnektor" not in self.steps:
                out["pairs"] = [
                    {
                        "pose1": _pose_tool_ref(pose1),
                        "pose2": _pose_tool_ref(pose2),
                    }
                    for pose1, pose2 in self.pairs
                ]
            out.update(
                {
                    "add_H_atoms": self.add_h_atoms,
                    "protonate_protein": self.protonate_protein,
                    "retain_waters": self.retain_waters,
                    "padding": self.padding,
                }
            )
        if self._uses_prepared_systems():
            out["prepared_systems"] = [
                _prepared_system_tool_ref(ps) for ps in self.prepared_systems
            ]
        if "rbfe" in self.steps:
            out.update(_simulation_blocks(self._params))
        if "cycle-closure" in self.steps:
            if self.exp_abfe:
                out["exp_abfe"] = self.exp_abfe
            if self.fep_abfe:
                out["fep_abfe"] = self.fep_abfe
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
        """Submit the RBFE workflow execution to the platform."""
        self._ensure_synced_inputs()
        payload = self._make_payload(approve_amount=approve_amount, sync=False)
        execution_dto = self._create_execution(data=payload)
        if execution_dto.get("executionId") is None:
            msg = "Execution response must contain 'executionId'"
            raise ValueError(msg)
        self.update_from_dto(execution_dto)

    def get_results(self, **_kwargs: Any) -> pd.DataFrame | None:
        """Retrieve RBFE ΔΔG results as a summary DataFrame.

        Uses :meth:`~deeporigin.drug_discovery.execution.Execution.get_results`
        (results for this tools execution id), then builds one row per result
        record with ``protein_id``, pose ids, ligand ids, and ``ddG`` (``total``
        plus ``unit`` from the stored payload).
        Keyword arguments are accepted for signature compatibility with the base
        class but are not forwarded.

        Returns:
            A DataFrame with columns ``protein_id``, ``pose1_id``, ``pose2_id``,
            ``ligand1_id``, ``ligand2_id``, and ``ddG``, or ``None`` if no result
            rows exist yet.

        Raises:
            ValueError: If no execution has been started.
        """
        self.sync()
        response = super().get_results()
        return _rbfe_results_dataframe(response, tool_key=self.tool_key)

    def get_cycle_closure_results(self, **_kwargs: Any) -> pd.DataFrame | None:
        """Retrieve per-pose absolute dG values from cycle closure.

        Returns:
            A DataFrame with columns ``pose_id``, ``ligand_id``, ``dG``, ``unit``, and
            optional ``cluster``, or ``None`` if no cycle-closure rows exist yet.

        Raises:
            ValueError: If no execution has been started.
        """
        self.sync()
        response = super().get_results()
        return _cycle_closure_results_dataframe(response, tool_key=self.tool_key)

    @beartype
    def get_prepared_system(
        self,
        *,
        ligand1_id: str | None = None,
        ligand2_id: str | None = None,
        pose1_id: str | None = None,
        pose2_id: str | None = None,
    ) -> PreparedSystem:
        """Load a :class:`PreparedSystem` from system-prep results for this execution.

        Fetches prepared-system rows scoped to this RBFE execution via
        :meth:`~deeporigin.drug_discovery.structures.prepared_system.PreparedSystem.from_result`.
        When multiple rows match, returns the first. Call :meth:`PreparedSystem.show`
        on the returned object to visualize it in a notebook.

        Args:
            ligand1_id: Optional first ligand ID to filter by.
            ligand2_id: Optional second ligand ID to filter by.
            pose1_id: Optional first pose ID to filter by.
            pose2_id: Optional second pose ID to filter by.

        Returns:
            A :class:`PreparedSystem` with paths and metadata from the result row.

        Raises:
            ValueError: If no execution has been started.
            DeepOriginException: If no matching system-prep results exist yet.
        """
        return self.get_prepared_systems(
            ligand1_id=ligand1_id,
            ligand2_id=ligand2_id,
            pose1_id=pose1_id,
            pose2_id=pose2_id,
        )[0]

    @beartype
    def get_prepared_systems(
        self,
        *,
        ligand1_id: str | None = None,
        ligand2_id: str | None = None,
        pose1_id: str | None = None,
        pose2_id: str | None = None,
    ) -> list[PreparedSystem]:
        """Load every :class:`PreparedSystem` this execution prepared.

        Args:
            ligand1_id: Optional first ligand ID to filter by.
            ligand2_id: Optional second ligand ID to filter by.
            pose1_id: Optional first pose ID to filter by.
            pose2_id: Optional second pose ID to filter by.

        Returns:
            One :class:`PreparedSystem` per prepared pair.

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
                ligand2_id=ligand2_id,
                pose1_id=pose1_id,
                pose2_id=pose2_id,
                client=self.client,
            )
        except ValueError as exc:
            raise DeepOriginException(
                title="No system-prep results found",
                message=(
                    "No system-prep results found for this RBFE execution. "
                    "Wait for the system-prep step to complete, or check the "
                    "pose/ligand ID filters."
                ),
            ) from exc

        if not systems:
            raise DeepOriginException(
                title="No system-prep results found",
                message=(
                    "No system-prep results found for this RBFE execution. "
                    "Wait for the system-prep step to complete, or check the "
                    "pose/ligand ID filters."
                ),
            )

        return systems

    def __repr__(self) -> str:
        """Return a concise multi-line representation."""
        parts = ["RBFE("]
        if self.id is not None:
            parts.append(f"  id={self.id!r},")
        if self.status is not None:
            parts.append(f"  status={self.status!r},")
        parts.extend(
            [
                f"  steps={self.steps!r},",
                f"  tool_key={self.tool_key!r},",
                f"  poses={len(self.poses)},",
                f"  pairs={len(self.pairs)},",
                f"  prepared_systems={len(self.prepared_systems)},",
                ")",
            ]
        )
        return "\n".join(parts)
