"""RBFE -- batch relative binding free energy workflow executions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Self

from beartype import beartype

from deeporigin.drug_discovery.abfe import ABFEParams
from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import AsyncExecutableMixin
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS

RBFEParams = ABFEParams


@beartype
def _ligand_tool_ref(*, ligand: Ligand) -> dict[str, str]:
    """Serialize a ligand for the RBFE workflow ``pairs[]`` input."""
    if ligand.remote_path is None:
        msg = "Ligand must be synced before submitting RBFE (remote_path is missing)."
        raise DeepOriginException(
            title="Ligand not synced",
            message=msg,
            fix="Call ligand.sync(client=...) before RBFE.start().",
        )
    ref: dict[str, str] = {"file_path": ligand.remote_path}
    if ligand.id is not None:
        ref["id"] = ligand.id
    return ref


@beartype
def _prepared_system_tool_ref(*, prepared_system: PreparedSystem) -> dict[str, str]:
    """Serialize a :class:`PreparedSystem` for ``prepared_systems[]``."""
    out: dict[str, str] = {
        "binding_xml_file_path": prepared_system.binding_xml_path,
        "solvation_xml_ligand_file_path": prepared_system.solvation_xml_path,
    }
    if prepared_system.protein_id is not None:
        out["protein_id"] = prepared_system.protein_id
    if prepared_system.ligand1_id is not None:
        out["ligand1_id"] = prepared_system.ligand1_id
    if prepared_system.ligand2_id is not None:
        out["ligand2_id"] = prepared_system.ligand2_id
    return out


@beartype
def _simulation_blocks(*, params: RBFEParams) -> dict[str, dict[str, Any]]:
    """Return shared ``binding`` and ``solvation`` blocks from *params*."""
    md_options = {
        "T": params.temperature,
        "cutoff": params.cutoff,
        "dt": params.dt,
    }
    return {
        "binding": {
            "annihilate": params.annihilate,
            "emeq_md_options": md_options,
            "n_windows": params.binding_n_windows,
            "npt_reduce_restraints_ns": params.binding_npt_reduce_restraints_ns,
            "nvt_heating_ns": params.binding_nvt_heating_ns,
            "prod_md_options": md_options,
            "repeats": params.repeats,
            "replex_period_ps": params.replex_period_ps,
            "steps": params.binding_steps,
            "test_run": params.test_run,
        },
        "solvation": {
            "annihilate": params.annihilate,
            "emeq_md_options": md_options,
            "n_windows": params.solvation_n_windows,
            "npt_reduce_restraints_ns": params.solvation_npt_reduce_restraints_ns,
            "nvt_heating_ns": params.solvation_nvt_heating_ns,
            "prod_md_options": md_options,
            "repeats": params.repeats,
            "replex_period_ps": params.replex_period_ps,
            "steps": params.solvation_steps,
            "test_run": params.test_run,
        },
    }


class RBFE(Execution, AsyncExecutableMixin, NotebookWatchMixin):
    """Batch RBFE workflow (``deeporigin.rbfe``).

    Supports three platform modes:

    - ``full``: shared protein + ligand pairs → system prep → RBFE FEP per pair
    - ``sysprep``: shared protein + ligand pairs → RBFE system prep only
    - ``rbfe``: prepared systems → RBFE FEP only

    Attributes:
        mode: Workflow mode forwarded to the platform tool.
        name: Optional execution label.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["rbfe"]["tool_key"]

    @beartype
    def __init__(
        self,
        *,
        mode: Literal["full", "sysprep", "rbfe"],
        protein: Protein | None = None,
        pairs: list[tuple[Ligand, Ligand]] | None = None,
        prepared_systems: list[PreparedSystem] | None = None,
        params: RBFEParams | None = None,
        add_h_atoms: bool = False,
        protonate_protein: bool = False,
        retain_waters: bool = True,
        padding: float = 1.0,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["rbfe"]["tool_version"],
        client: DeepOriginClient | None = None,
        name: str | None = None,
    ) -> None:
        """Create an RBFE batch workflow execution.

        Args:
            mode: ``full``, ``sysprep``, or ``rbfe``.
            protein: Shared protein for prep modes.
            pairs: Ligand pairs for ``full`` / ``sysprep``.
            prepared_systems: Prepared systems for ``rbfe`` (and optional reuse).
            params: FEP simulation parameters for ``full`` / ``rbfe``.
            add_h_atoms: Add hydrogens to ligands during prep.
            protonate_protein: Protonate protein during prep.
            retain_waters: Retain crystal waters during prep.
            padding: Solvation box padding (nm) during prep.
            tool_version: Platform tool version pin.
            client: Optional API client.
            name: Optional execution label.

        Raises:
            ValueError: When required arguments for *mode* are missing.
        """
        super().__init__(client=client)
        self.mode = mode
        self.tool_version = tool_version
        self.protein = protein
        self.pairs = pairs or []
        self.prepared_systems = prepared_systems or []
        self._params = params if params is not None else RBFEParams()
        self.add_h_atoms = add_h_atoms
        self.protonate_protein = protonate_protein
        self.retain_waters = retain_waters
        self.padding = padding
        self.name = name
        self._validate_mode_inputs()

    @classmethod
    def from_pairs(
        cls,
        *,
        protein: Protein,
        pairs: list[tuple[Ligand, Ligand]],
        mode: Literal["full", "sysprep"] = "full",
        params: RBFEParams | None = None,
        client: DeepOriginClient | None = None,
        name: str | None = None,
        **prep_kwargs: Any,
    ) -> Self:
        """Convenience constructor for prep-bearing modes."""
        return cls(
            mode=mode,
            protein=protein,
            pairs=pairs,
            params=params,
            client=client,
            name=name,
            **prep_kwargs,
        )

    @classmethod
    def from_prepared_systems(
        cls,
        *,
        prepared_systems: list[PreparedSystem],
        params: RBFEParams | None = None,
        client: DeepOriginClient | None = None,
        name: str | None = None,
    ) -> Self:
        """Convenience constructor for ``mode=rbfe``."""
        return cls(
            mode="rbfe",
            prepared_systems=prepared_systems,
            params=params,
            client=client,
            name=name,
        )

    @property
    def params(self) -> RBFEParams:
        """FEP calculation parameters (read-only)."""
        return self._params

    @params.setter
    def params(self, value: RBFEParams) -> None:
        """Prevent modification of params after construction."""
        raise AttributeError("params can only be set in the constructor")

    def _validate_mode_inputs(self) -> None:
        """Validate constructor arguments for the selected *mode*."""
        if self.mode in {"full", "sysprep"}:
            if self.protein is None:
                raise ValueError(f"protein is required for mode={self.mode!r}.")
            if not self.pairs:
                raise ValueError(f"pairs is required for mode={self.mode!r}.")
        if self.mode == "rbfe":
            if not self.prepared_systems:
                raise ValueError("prepared_systems is required for mode='rbfe'.")

    def _ensure_synced_inputs(self) -> None:
        """Sync protein and ligands before submission."""
        if self.protein is not None:
            self.protein.sync(lazy=True, client=self.client)
        for ligand1, ligand2 in self.pairs:
            ligand1.sync(lazy=True, client=self.client)
            ligand2.sync(lazy=True, client=self.client)

    def _build_params(self) -> dict[str, Any]:
        """Construct workflow input parameters for ``deeporigin.rbfe``."""
        out: dict[str, Any] = {"mode": self.mode}
        if self.mode in {"full", "sysprep"}:
            assert self.protein is not None
            out["protein"] = {
                "id": self.protein.id,
                "file_path": self.protein.remote_path,
            }
            out["pairs"] = [
                {
                    "ligand1": _ligand_tool_ref(ligand=ligand1),
                    "ligand2": _ligand_tool_ref(ligand=ligand2),
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
        if self.mode == "rbfe":
            out["prepared_systems"] = [
                _prepared_system_tool_ref(prepared_system=ps)
                for ps in self.prepared_systems
            ]
        if self.mode in {"full", "rbfe"}:
            out.update(_simulation_blocks(params=self._params))
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

    def __repr__(self) -> str:
        """Return a concise multi-line representation."""
        parts = [
            "RBFE(",
            f"  mode={self.mode!r},",
            f"  tool_key={self.tool_key!r},",
            f"  pairs={len(self.pairs)},",
            f"  prepared_systems={len(self.prepared_systems)},",
            ")",
        ]
        return "\n".join(parts)
