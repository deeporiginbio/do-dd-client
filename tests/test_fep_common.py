"""Unit tests for :mod:`deeporigin.drug_discovery.fep_common`."""

from __future__ import annotations

import pytest

from deeporigin.drug_discovery.fep_common import (
    ABFEParams,
    RBFEParams,
    _fep_params_from_inputs,
    _ligand_tool_ref,
    _pose_tool_ref,
    _prepared_system_tool_ref,
    _simulation_blocks,
)
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.pose import Pose
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.exceptions import DeepOriginException


def test_simulation_blocks_round_trip() -> None:
    """_simulation_blocks emits binding/solvation keys expected by workflow tools."""
    params = ABFEParams(test_run=1, binding_n_windows=12, solvation_steps=99)
    blocks = _simulation_blocks(params)
    assert blocks["binding"]["test_run"] == 1
    assert blocks["binding"]["n_windows"] == 12
    assert blocks["solvation"]["steps"] == 99
    assert blocks["binding"]["emeq_md_options"]["T"] == pytest.approx(298.15)


def test_fep_params_from_inputs_round_trip() -> None:
    """_fep_params_from_inputs restores ABFEParams from stored tool inputs."""
    inputs = {
        "binding": {
            "annihilate": False,
            "emeq_md_options": {"T": 310.0, "cutoff": 1.1, "dt": 0.003},
            "n_windows": 20,
            "npt_reduce_restraints_ns": 1.5,
            "nvt_heating_ns": 0.8,
            "prod_md_options": {"T": 310.0, "cutoff": 1.1, "dt": 0.003},
            "repeats": 3,
            "replex_period_ps": 4.0,
            "steps": 200000,
            "test_run": 1,
        },
        "solvation": {
            "annihilate": False,
            "emeq_md_options": {"T": 310.0, "cutoff": 1.1, "dt": 0.003},
            "n_windows": 10,
            "npt_reduce_restraints_ns": 0.2,
            "nvt_heating_ns": 0.1,
            "prod_md_options": {"T": 310.0, "cutoff": 1.1, "dt": 0.003},
            "repeats": 3,
            "replex_period_ps": 4.0,
            "steps": 80000,
            "test_run": 1,
        },
    }
    params = _fep_params_from_inputs(inputs)
    assert isinstance(params, ABFEParams)
    assert not isinstance(params, RBFEParams)
    assert params.temperature == pytest.approx(310.0)
    assert params.binding_n_windows == 20
    assert params.solvation_steps == 80000
    assert params.repeats == 3


def test_fep_params_from_inputs_rbfe_cls() -> None:
    """_fep_params_from_inputs can hydrate RBFEParams with relative defaults."""
    params = _fep_params_from_inputs({}, params_cls=RBFEParams)
    assert isinstance(params, RBFEParams)
    assert params.binding_n_windows == 24
    assert params.solvation_n_windows == 24


def test_abfe_params_defaults_and_repr() -> None:
    """ABFEParams keep absolute window defaults and label themselves in repr."""
    params = ABFEParams()
    assert params.binding_n_windows == 48
    assert params.solvation_n_windows == 32
    text = repr(params)
    assert text.startswith("ABFEParams(")
    assert "binding_n_windows: 48" in text


def test_rbfe_params_defaults_and_repr() -> None:
    """RBFEParams use MDSuite relative window defaults and label themselves."""
    params = RBFEParams()
    assert params.binding_n_windows == 24
    assert params.solvation_n_windows == 24
    text = repr(params)
    assert text.startswith("RBFEParams(")
    assert "binding_n_windows: 24" in text
    assert "solvation_n_windows: 24" in text


def test_simulation_blocks_accept_rbfe_params() -> None:
    """_simulation_blocks serializes RBFEParams window counts."""
    blocks = _simulation_blocks(RBFEParams())
    assert blocks["binding"]["n_windows"] == 24
    assert blocks["solvation"]["n_windows"] == 24


def test_prepared_system_tool_ref_includes_optional_ids() -> None:
    """_prepared_system_tool_ref serializes paths and entity IDs."""
    ps = PreparedSystem(
        binding_xml_path="testing/a.xml",
        solvation_xml_path="testing/b.xml",
        system_pdb_path="testing/c.pdb",
        protein_id="prot-1",
        ligand1_id="lig-1",
        ligand2_id="lig-2",
    )
    ref = _prepared_system_tool_ref(ps)
    assert ref["binding_xml_file_path"] == "testing/a.xml"
    assert ref["ligand2_id"] == "lig-2"


def test_pose_tool_ref_serializes_synced_pose() -> None:
    """_pose_tool_ref emits platform id and remote file_path."""
    pose = Pose(
        ligand_id="lig-1",
        id="pose-1",
        remote_path="testing/pose.sdf",
    )
    assert _pose_tool_ref(pose) == {
        "id": "pose-1",
        "file_path": "testing/pose.sdf",
    }


def test_pose_tool_ref_requires_remote_path() -> None:
    """_pose_tool_ref rejects poses that are not synced."""
    pose = Pose(ligand_id="lig-1", id="pose-1")
    with pytest.raises(DeepOriginException, match="remote_path"):
        _pose_tool_ref(pose)


def test_pose_tool_ref_requires_platform_id() -> None:
    """_pose_tool_ref rejects poses without a platform id."""
    pose = Pose(ligand_id="lig-1", remote_path="testing/pose.sdf")
    with pytest.raises(DeepOriginException, match="platform id"):
        _pose_tool_ref(pose)


def test_ligand_tool_ref_serializes_synced_ligand() -> None:
    """_ligand_tool_ref emits remote file_path and optional platform id."""
    ligand = Ligand.from_smiles("CCO", id="lig-1", remote_path="testing/lig.sdf")
    assert _ligand_tool_ref(ligand) == {
        "id": "lig-1",
        "file_path": "testing/lig.sdf",
    }


def test_ligand_tool_ref_allows_missing_id() -> None:
    """_ligand_tool_ref omits id when the ligand is file-only."""
    ligand = Ligand.from_smiles("CCO", id=None, remote_path="testing/lig.sdf")
    assert _ligand_tool_ref(ligand) == {"file_path": "testing/lig.sdf"}


def test_ligand_tool_ref_requires_remote_path() -> None:
    """_ligand_tool_ref rejects ligands that are not synced."""
    ligand = Ligand.from_smiles("CCO", id="lig-1")
    with pytest.raises(DeepOriginException, match="remote_path"):
        _ligand_tool_ref(ligand)
