"""Unit tests for :mod:`deeporigin.drug_discovery.fep_common`."""

from __future__ import annotations

import pytest

from deeporigin.drug_discovery.fep_common import (
    ABFEParams,
    _fep_params_from_inputs,
    _prepared_system_tool_ref,
    _simulation_blocks,
)
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem


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
    assert params.temperature == pytest.approx(310.0)
    assert params.binding_n_windows == 20
    assert params.solvation_steps == 80000
    assert params.repeats == 3


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
