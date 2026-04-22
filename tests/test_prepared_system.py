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
