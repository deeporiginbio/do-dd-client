"""Tests for :class:`deeporigin.drug_discovery.system_prep.SystemPrep`."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.drug_discovery.system_prep import SystemPrep
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from tests.conftest import check_tool_exists


def _minimal_sysprep_dto(*, execution_id: str = "exec-sysprep-1") -> dict:
    """Build a minimal tools execution DTO for system prep."""
    sp = TOOL_KEYS_AND_VERSIONS["sysprep"]
    return {
        "executionId": execution_id,
        "tool": {"key": sp["tool_key"], "version": sp["tool_version"]},
        "status": "Succeeded",
        "name": "sysprep-test",
        "userInputs": {},
    }


@patch.object(PreparedSystem, "from_json", autospec=True)
@patch.object(PreparedSystem, "from_result", autospec=True)
def test_system_prep_get_results_falls_back_to_job_outputs(
    mock_from_result: MagicMock,
    mock_from_json: MagicMock,
) -> None:
    """When ``from_result`` fails, ``jobOutputs.system`` is parsed via ``from_json``."""
    mock_from_result.side_effect = ValueError("no rows")
    fake_ps = MagicMock(spec=PreparedSystem)
    mock_from_json.return_value = fake_ps

    client = MagicMock(spec=DeepOriginClient)
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    ligand = Ligand.from_smiles("CCO")
    dto_exec = _minimal_sysprep_dto()
    system_payload = {
        "binding_xml_file_path": "b.xml",
        "solvation_xml_ligand_file_path": "s.xml",
        "system_pdb_file_path": "p.pdb",
        "protein_id": protein.id,
        "ligand1_id": ligand.id,
    }
    dto_exec["jobOutputs"] = {"system": system_payload}

    sysprep = SystemPrep(protein=protein, ligand=ligand, client=client)
    sysprep.update_from_dto(dto_exec)

    out = sysprep.get_results(dto_exec)

    assert out is fake_ps
    mock_from_result.assert_called_once_with(
        compute_job_id="exec-sysprep-1",
        client=client,
    )
    mock_from_json.assert_called_once_with(system_payload)


def test_system_prep_get_results_requires_id() -> None:
    """``get_results`` raises when ``id`` has not been set."""
    client = MagicMock(spec=DeepOriginClient)
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    ligand = Ligand.from_smiles("CCO")
    sysprep = SystemPrep(protein=protein, ligand=ligand, client=client)

    with pytest.raises(ValueError, match="id is None"):
        sysprep.get_results()


def test_sysprep_lv2(
    client: DeepOriginClient,
    registered_protein: Protein,
    registered_ligand: Ligand,
) -> None:
    """Exercise ABFE system prep via :meth:`SystemPrep.run` on data-platform entities."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["sysprep"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["sysprep"]["tool_version"],
    ), "System prep tool not registered on platform (expected key/version)."

    sysprep = SystemPrep(
        protein=registered_protein,
        ligand=registered_ligand,
        client=client,
        add_H_atoms=True,
        protonate_protein=True,
    )
    prepared = sysprep.run()

    assert isinstance(prepared, PreparedSystem), (
        "Expected SystemPrep.run() to return PreparedSystem"
    )
