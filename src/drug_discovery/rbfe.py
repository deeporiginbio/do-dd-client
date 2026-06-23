"""RBFE -- batch relative binding free energy workflow executions."""

from __future__ import annotations

from typing import Any, Literal, Self

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import AsyncExecutableMixin
from deeporigin.drug_discovery.fep_common import (
    ABFEParams,
    _fep_params_from_inputs,
    _ligand_tool_ref,
    _prepared_system_tool_ref,
    _simulation_blocks,
)
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS

RBFEParams = ABFEParams
RBFEWorkflowStep = Literal["konnektor", "system-prep", "rbfe", "cycle-closure"]
KonnektorNetworkType = Literal["star", "mst", "cyclic"]
RBFEAnchorInput = dict[str, str | float]


@beartype
def _ligand_konnektor_tool_ref(ligand: Ligand) -> dict[str, str]:
    """Serialize a ligand for the RBFE Konnektor ``ligands[]`` input."""
    ligand_id = ligand.id
    if ligand_id is None or not str(ligand_id).strip():
        msg = "Ligand must be registered before submitting RBFE (id is missing)."
        raise DeepOriginException(
            title="Ligand not registered",
            message=msg,
            fix="Call ligand.sync(client=...) before RBFE.start().",
        )
    if ligand.remote_path is None:
        msg = "Ligand must be synced before submitting RBFE (remote_path is missing)."
        raise DeepOriginException(
            title="Ligand not synced",
            message=msg,
            fix="Call ligand.sync(client=...) before RBFE.start().",
        )
    return {"id": str(ligand_id), "file_path": ligand.remote_path}


def _ligand_from_pair_input(ref: dict[str, Any], *, client: DeepOriginClient) -> Ligand:
    """Rehydrate a ligand from an RBFE ``pairs[]`` ligand reference."""
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
    if "ligand_id" in payload and "dG" in payload:
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
    """Build a summary table from a data-platform RBFE results response."""
    records = response.get("data") or []
    rows: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("tool_key") != tool_key:
            continue
        payload = record.get("data")
        if not isinstance(payload, dict):
            continue
        rows.append(
            {
                "protein_id": payload.get("protein_id"),
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

    Platform ``steps`` are inferred from constructor inputs (see :meth:`_post_init`):

    - ``["konnektor", "system-prep", "rbfe"]``: ``protein`` + ``ligands``
    - ``["system-prep", "rbfe"]``: ``protein`` + ``pairs``
    - ``["rbfe"]``: ``prepared_systems``
    - Append ``cycle-closure`` when ``exp_abfe`` and/or ``fep_abfe`` anchors are set

    Attributes:
        steps: Ordered workflow steps forwarded to the platform tool.
        name: Optional execution label.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["rbfe"]["tool_key"]

    def __init__(
        self,  # NOSONAR(S107)
        *,
        protein: Protein | None = None,
        ligands: LigandSet | list[Ligand] | None = None,
        pairs: list[tuple[Ligand, Ligand]] | None = None,
        prepared_systems: list[PreparedSystem] | None = None,
        network_type: KonnektorNetworkType = "mst",
        params: RBFEParams | None = None,
        add_h_atoms: bool = False,
        protonate_protein: bool = False,
        retain_waters: bool = True,
        padding: float = 1.0,
        exp_abfe: list[RBFEAnchorInput] | None = None,
        fep_abfe: list[RBFEAnchorInput] | None = None,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["rbfe"]["tool_version"],
        client: DeepOriginClient | None = None,
    ) -> None:
        """Create an RBFE batch workflow execution.

        Platform ``steps`` are inferred in :meth:`_post_init`:

        - ``prepared_systems`` -> ``["rbfe"]`` (FEP on existing systems)
        - ``protein`` + ``pairs`` -> ``["system-prep", "rbfe"]``
        - ``protein`` + ``ligands`` -> ``["konnektor", "system-prep", "rbfe"]``

        Exactly one of ``ligands``, ``pairs``, or ``prepared_systems`` must be
        provided.

        Args:
            protein: Shared protein for prep modes (required with ``ligands`` or
                ``pairs``).
            ligands: Ligand set for Konnektor network planning (min 2).
            pairs: Explicit ligand pairs for system-prep steps.
            prepared_systems: Prepared systems for RBFE-only steps.
            network_type: Konnektor topology when ``ligands`` is provided.
            params: FEP simulation parameters for plans that include ``rbfe``.
            add_h_atoms: Add hydrogens to ligands during prep.
            protonate_protein: Protonate protein during prep.
            retain_waters: Retain crystal waters during prep.
            padding: Solvation box padding (nm) during prep.
            exp_abfe: Experimental ABFE anchor values for cycle closure.
            fep_abfe: FEP-ABFE anchor values for cycle closure.
            tool_version: Platform tool version pin.
            client: Optional API client.

        Raises:
            ValueError: When inputs are missing or mutually exclusive.
        """
        super().__init__(client=client)
        self.tool_version = tool_version
        self.exp_abfe = list(exp_abfe or [])
        self.fep_abfe = list(fep_abfe or [])
        self.protein = protein
        if ligands is None:
            self.ligands = LigandSet()
        elif isinstance(ligands, LigandSet):
            self.ligands = ligands
        else:
            self.ligands = LigandSet(ligands=list(ligands))
        self.pairs = pairs or []
        self.prepared_systems = prepared_systems or []
        self.network_type = network_type
        self._params = params if params is not None else RBFEParams()
        self.add_h_atoms = add_h_atoms
        self.protonate_protein = protonate_protein
        self.retain_waters = retain_waters
        self.padding = padding
        self._post_init()

    def _post_init(self) -> None:
        """Infer platform ``steps`` from constructor inputs and validate."""
        has_ligands = bool(self.ligands)
        has_pairs = bool(self.pairs)
        has_prep = bool(self.prepared_systems)
        mode_count = sum([has_ligands, has_pairs, has_prep])

        if mode_count != 1:
            raise ValueError(
                "Exactly one of ligands, pairs, or prepared_systems must be provided."
            )
        if has_prep:
            self.steps: list[RBFEWorkflowStep] = ["rbfe"]
        elif has_ligands:
            self.steps = ["konnektor", "system-prep", "rbfe"]
        else:
            self.steps = ["system-prep", "rbfe"]
        if (self.exp_abfe or self.fep_abfe) and "cycle-closure" not in self.steps:
            self.steps = [*self.steps, "cycle-closure"]
        self._validate_step_inputs()

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

        if instance.steps == ["system-prep"]:
            msg = (
                "Legacy steps=['system-prep'] executions are no longer supported "
                "by RBFE.from_dto()."
            )
            raise ValueError(msg)

        instance.protein = None
        instance.ligands = LigandSet()
        instance.pairs = []
        instance.prepared_systems = []
        raw_network_type = inputs.get("network_type", "mst")
        if raw_network_type not in ("star", "mst", "cyclic"):
            raw_network_type = "mst"
        instance.network_type = raw_network_type
        instance.add_h_atoms = bool(inputs.get("add_H_atoms", False))
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
            _fep_params_from_inputs(inputs)
            if "rbfe" in instance.steps
            else RBFEParams()
        )

        if "konnektor" in instance.steps:
            instance.ligands = LigandSet(
                ligands=[
                    _ligand_from_pair_input(ref, client=instance.client)
                    for ref in inputs.get("ligands", [])
                    if isinstance(ref, dict)
                ]
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

            if "konnektor" not in instance.steps:
                instance.pairs = [
                    (
                        _ligand_from_pair_input(
                            pair["ligand1"], client=instance.client
                        ),
                        _ligand_from_pair_input(
                            pair["ligand2"], client=instance.client
                        ),
                    )
                    for pair in inputs.get("pairs", [])
                    if "ligand1" in pair and "ligand2" in pair
                ]

        if instance.steps == ["rbfe"] or (
            "rbfe" in instance.steps and inputs.get("prepared_systems")
        ):
            instance.prepared_systems = [
                PreparedSystem(
                    binding_xml_path=ps.get("binding_xml_file_path", ""),
                    solvation_xml_path=ps.get("solvation_xml_ligand_file_path", ""),
                    system_pdb_path=ps.get("system_pdb_file_path", ""),
                    solute_pdb_path=ps.get("solute_pdb_file_path"),
                    protein_id=ps.get("protein_id"),
                    ligand1_id=ps.get("ligand1_id"),
                    ligand2_id=ps.get("ligand2_id"),
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
        if self.steps == ["rbfe"] and not self.prepared_systems:
            raise ValueError("prepared_systems is required for steps=['rbfe'].")
        if "cycle-closure" in self.steps:
            self._validate_cycle_closure_inputs()

    def _validate_konnektor_inputs(self) -> None:
        """Validate inputs for Konnektor workflow steps."""
        if self.protein is None:
            raise ValueError(f"protein is required for steps={self.steps!r}.")
        if len(self.ligands) < 2:
            raise ValueError(
                f"ligands requires at least two ligands for steps={self.steps!r}."
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
                ligand_id = anchor.get("ligand_id")
                if not isinstance(ligand_id, str) or not ligand_id:
                    raise ValueError(
                        f"{label} entries require a non-empty string 'ligand_id'."
                    )
                if not isinstance(anchor.get("dG"), (int, float)):
                    raise ValueError(f"{label} entries require a numeric 'dG' value.")

    def _ensure_synced_inputs(self) -> None:
        """Sync protein and ligands before submission."""
        client = self.client
        if self.protein is not None:
            self._sync_entity_if_needed(self.protein, client=client, label="Protein")
        if "konnektor" in self.steps:
            for ligand in self.ligands:
                self._sync_entity_if_needed(ligand, client=client, label="Ligand")
        for ligand1, ligand2 in self.pairs:
            self._sync_entity_if_needed(ligand1, client=client, label="Ligand")
            self._sync_entity_if_needed(ligand2, client=client, label="Ligand")

    @staticmethod
    def _sync_entity_if_needed(
        entity: Protein | Ligand,
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
            out["ligands"] = [
                _ligand_konnektor_tool_ref(ligand) for ligand in self.ligands
            ]
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
                        "ligand1": _ligand_tool_ref(ligand1),
                        "ligand2": _ligand_tool_ref(ligand2),
                    }
                    for ligand1, ligand2 in self.pairs
                ]
            out.update(
                {
                    "add_H_atoms": self.add_h_atoms,
                    "protonate_protein": self.protonate_protein,
                    "retain_waters": self.retain_waters,
                    "padding": self.padding,
                }
            )
        if self.steps == ["rbfe"]:
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
        """Retrieve RBFE ΔΔG results as a summary DataFrame.

        Uses :meth:`~deeporigin.drug_discovery.execution.Execution.get_results`
        (results for this tools execution id), then builds one row per result
        record with ``protein_id``, ligand ids, and ``ddG`` (``total`` plus
        ``unit`` from the stored payload).
        Keyword arguments are accepted for signature compatibility with the base
        class but are not forwarded.

        Returns:
            A DataFrame with columns ``protein_id``, ``ligand1_id``,
            ``ligand2_id``, and ``ddG``, or ``None`` if no result rows exist yet.

        Raises:
            ValueError: If no execution has been started.
        """
        self.sync()
        response = super().get_results()
        return _rbfe_results_dataframe(response, tool_key=self.tool_key)

    def get_cycle_closure_results(self, **_kwargs: Any) -> pd.DataFrame | None:
        """Retrieve per-ligand absolute dG values from cycle closure.

        Returns:
            A DataFrame with columns ``ligand_id``, ``dG``, ``unit``, and
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
    ) -> PreparedSystem:
        """Load a :class:`PreparedSystem` from system-prep results for this execution.

        Fetches prepared-system rows scoped to this RBFE execution via
        :meth:`~deeporigin.drug_discovery.structures.prepared_system.PreparedSystem.from_result`.
        When multiple rows match, returns the first. Call :meth:`PreparedSystem.show`
        on the returned object to visualize it in a notebook.

        Args:
            ligand1_id: Optional first ligand ID to filter by.
            ligand2_id: Optional second ligand ID to filter by.

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
                ligand2_id=ligand2_id,
                client=self.client,
            )
        except ValueError as exc:
            raise DeepOriginException(
                title="No system-prep results found",
                message=(
                    "No system-prep results found for this RBFE execution. "
                    "Wait for the system-prep step to complete, or pass "
                    "ligand1_id/ligand2_id to disambiguate."
                ),
            ) from exc

        if not systems:
            raise DeepOriginException(
                title="No system-prep results found",
                message=(
                    "No system-prep results found for this RBFE execution. "
                    "Wait for the system-prep step to complete, or pass "
                    "ligand1_id/ligand2_id to disambiguate."
                ),
            )

        return systems[0]

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
                f"  ligands={len(self.ligands)},",
                f"  pairs={len(self.pairs)},",
                f"  prepared_systems={len(self.prepared_systems)},",
                ")",
            ]
        )
        return "\n".join(parts)
