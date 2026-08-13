"""Shared FEP parameter serialization for ABFE and RBFE workflow tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from beartype import beartype

from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.pose import Pose
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.exceptions import DeepOriginException


@dataclass(frozen=True)
class ABFEParams:
    """FEP calculation parameters for absolute binding free energy (ABFE).

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

    annihilate: bool = True
    dt: float = 0.004
    temperature: float = 298.15
    cutoff: float = 0.9
    repeats: int = 1
    replex_period_ps: float = 2.5
    test_run: int = 0
    binding_n_windows: int = 48
    binding_npt_reduce_restraints_ns: float = 2.0
    binding_nvt_heating_ns: float = 1.0
    binding_steps: int = 1250000
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
        return f"{type(self).__name__}(\n" + "\n".join(lines) + "\n)"


@dataclass(frozen=True, repr=False)
class RBFEParams(ABFEParams):
    """FEP calculation parameters for relative binding free energy (RBFE).

    Window defaults match MDSuite relative-FEP (`is_relative`) when ``n_windows``
    is unset: 24 for both binding and solvation (vs ABFE's 48 / 32).
    """

    binding_n_windows: int = 24
    solvation_n_windows: int = 24


@beartype
def _ligand_tool_ref(ligand: Ligand) -> dict[str, str]:
    """Serialize a ligand for workflow ``ligand1`` / ``pairs[]`` inputs."""
    if ligand.remote_path is None:
        msg = "Ligand must be synced before submitting (remote_path is missing)."
        raise DeepOriginException(
            title="Ligand not synced",
            message=msg,
            fix="Call ligand.sync(client=...) before start().",
        )
    ref: dict[str, str] = {"file_path": ligand.remote_path}
    if ligand.id is not None:
        ref["id"] = ligand.id
    return ref


@beartype
def _pose_tool_ref(pose: Pose) -> dict[str, str]:
    """Serialize a pose for workflow ``pose1`` / ``pairs[].pose*`` inputs."""
    if pose.remote_path is None:
        msg = "Pose must be synced before submitting (remote_path is missing)."
        raise DeepOriginException(
            title="Pose not synced",
            message=msg,
            fix="Call pose.sync(client=...) or Pose.from_sdf(...) before start().",
        )
    if pose.id is None:
        msg = "Pose must have a platform id before submitting."
        raise DeepOriginException(
            title="Pose missing id",
            message=msg,
            fix="Register the pose (Pose.from_sdf) or load it from docking results.",
        )
    return {"id": pose.id, "file_path": pose.remote_path}


@beartype
def _prepared_system_tool_ref(prepared_system: PreparedSystem) -> dict[str, str]:
    """Serialize a :class:`PreparedSystem` for workflow prepared-system inputs."""
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
def _simulation_blocks(params: ABFEParams) -> dict[str, dict[str, Any]]:
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


@beartype
def _fep_params_from_inputs(
    inputs: dict[str, Any],
    *,
    params_cls: type[ABFEParams] = ABFEParams,
) -> ABFEParams:
    """Build FEP params from stored ``binding`` / ``solvation`` blocks.

    Args:
        inputs: Tool inputs containing optional ``binding`` / ``solvation`` dicts.
        params_cls: Params class to instantiate (:class:`ABFEParams` or
            :class:`RBFEParams`). Controls which defaults apply for missing fields.
    """
    binding = inputs.get("binding", {})
    solvation = inputs.get("solvation", {})
    md_options = binding.get("emeq_md_options", {})

    binding_key_map = {
        "annihilate": "annihilate",
        "n_windows": "binding_n_windows",
        "npt_reduce_restraints_ns": "binding_npt_reduce_restraints_ns",
        "nvt_heating_ns": "binding_nvt_heating_ns",
        "steps": "binding_steps",
        "repeats": "repeats",
        "replex_period_ps": "replex_period_ps",
        "test_run": "test_run",
    }
    solvation_key_map = {
        "n_windows": "solvation_n_windows",
        "npt_reduce_restraints_ns": "solvation_npt_reduce_restraints_ns",
        "nvt_heating_ns": "solvation_nvt_heating_ns",
        "steps": "solvation_steps",
    }
    md_options_key_map = {
        "dt": "dt",
        "T": "temperature",
        "cutoff": "cutoff",
    }

    kwargs: dict[str, Any] = {}
    for dto_key, param_field in binding_key_map.items():
        if dto_key in binding:
            kwargs[param_field] = binding[dto_key]
    for dto_key, param_field in solvation_key_map.items():
        if dto_key in solvation:
            kwargs[param_field] = solvation[dto_key]
    for dto_key, param_field in md_options_key_map.items():
        if dto_key in md_options:
            kwargs[param_field] = md_options[dto_key]

    return params_cls(**kwargs)
