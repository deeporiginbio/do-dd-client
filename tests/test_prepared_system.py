"""Tests for PreparedSystem."""

import pytest

from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.exceptions import DeepOriginException


def test_from_record_uses_solvation_xml_ligand_file_path_lv0():
    """_from_record reads solvation_xml_ligand_file_path from result data."""
    record = {
        "id": "r1",
        "data": {
            "binding_xml_file_path": "b.xml",
            "solvation_xml_ligand_file_path": "s.xml",
            "system_pdb_file_path": "p.pdb",
            "solute_pdb_file_path": "solute.pdb",
        },
    }
    ps = PreparedSystem._from_record(record)
    assert ps.solvation_xml_path == "s.xml"
    assert ps.binding_xml_path == "b.xml"
    assert ps.solute_pdb_path == "solute.pdb"
    assert ps.id == "r1"


def test_from_record_merges_compute_job_id_lv0():
    """_from_record puts compute_job_id into the JSON passed to from_json."""
    record = {
        "id": "r1",
        "compute_job_id": "job-xyz",
        "data": {
            "binding_xml_file_path": "b.xml",
            "solvation_xml_ligand_file_path": "s.xml",
            "system_pdb_file_path": "p.pdb",
        },
    }
    ps = PreparedSystem._from_record(record)
    assert ps.compute_job_id == "job-xyz"


def test_from_json_reads_paths_and_metadata_lv0():
    """from_json builds a PreparedSystem from a single JSON dict."""
    ps = PreparedSystem.from_json(
        {
            "binding_xml_file_path": "b.xml",
            "solvation_xml_ligand_file_path": "s.xml",
            "system_pdb_file_path": "p.pdb",
            "protein_id": "prot-a",
            "ligand1_id": "lig-a",
            "padding": 1.5,
            "add_H_atoms": False,
            "retain_waters": True,
            "protonate_protein": False,
            "id": "rec-1",
            "compute_job_id": "job-9",
        },
    )
    assert ps.protein_id == "prot-a"
    assert ps.ligand1_id == "lig-a"
    assert ps.padding == 1.5
    assert ps.add_H_atoms is False
    assert ps.retain_waters is True
    assert ps.protonate_protein is False
    assert ps.id == "rec-1"
    assert ps.compute_job_id == "job-9"


def test_from_json_raises_when_paths_missing_lv0():
    """from_json raises when required path keys are absent."""
    with pytest.raises(ValueError, match="missing required paths"):
        PreparedSystem.from_json({})


def test_prepared_system_show_raises_without_system_pdb_lv0():
    """show() raises when system_pdb_path is empty."""
    ps = PreparedSystem(
        binding_xml_path="b.xml",
        solvation_xml_path="s.xml",
        system_pdb_path="",
    )
    with pytest.raises(DeepOriginException, match="system_pdb_path is empty"):
        ps.show()


def test_prepared_system_show_raises_without_solute_pdb_when_requested_lv0():
    """show(solute=True) raises when solute_pdb_path is missing."""
    ps = PreparedSystem(
        binding_xml_path="b.xml",
        solvation_xml_path="s.xml",
        system_pdb_path="full.pdb",
    )
    with pytest.raises(DeepOriginException, match="solute_pdb_path is not set"):
        ps.show(solute=True)
