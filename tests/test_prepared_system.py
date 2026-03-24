"""Tests for PreparedSystem."""

import pytest

from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.exceptions import DeepOriginException


def test_prepared_system_show_raises_without_system_pdb_lv0():
    """show() raises when system_pdb_path is empty."""
    ps = PreparedSystem(
        binding_xml_path="b.xml",
        solvation_xml_path="s.xml",
        system_pdb_path="",
    )
    with pytest.raises(DeepOriginException, match="system_pdb_path is empty"):
        ps.show()
