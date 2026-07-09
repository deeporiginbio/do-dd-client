"""Tests for :class:`deeporigin.drug_discovery.system_prep.SystemPrep`."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.drug_discovery.system_prep import SystemPrep
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import SYSPREP_NO_OUTPUT_PATHS_MSG
from tests.conftest import check_tool_exists

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


def _block_prepared_system_from_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``PreparedSystem.from_result`` to fail so ``get_results`` uses fallbacks."""

    @classmethod
    def _raise_from_result(cls, **kwargs: object) -> list[PreparedSystem]:
        raise ValueError("no rows")

    monkeypatch.setattr(PreparedSystem, "from_result", _raise_from_result)


def test_system_prep_get_results_falls_back_to_job_outputs(
    client: DeepOriginClient,
    brd_protein: Protein,
    brd_ligand: Ligand,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``from_result`` fails, ``jobOutputs.system`` is parsed via ``from_json``."""
    _block_prepared_system_from_result(monkeypatch)

    sysprep = SystemPrep(protein=brd_protein, ligand=brd_ligand, client=client)
    prepared = sysprep.run()
    dto = client.executions.get(sysprep.id)  # ty:ignore[unresolved-attribute]

    out = sysprep.get_results(dto)

    assert isinstance(out, PreparedSystem)
    assert out.binding_xml_path == prepared.binding_xml_path
    assert out.system_pdb_path == prepared.system_pdb_path


def test_system_prep_get_results_requires_id(client: DeepOriginClient) -> None:
    """``get_results`` raises when ``id`` has not been set."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    ligand = Ligand.from_smiles("CCO")
    sysprep = SystemPrep(protein=protein, ligand=ligand, client=client)

    with pytest.raises(ValueError, match="id is None"):
        sysprep.get_results()


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


def test_system_prep_get_results_raises_when_no_paths(
    client: DeepOriginClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both data platform and ``jobOutputs`` fail, raise sysprep message."""
    _block_prepared_system_from_result(monkeypatch)
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    ligand = Ligand.from_smiles("CCO")
    sysprep = SystemPrep(protein=protein, ligand=ligand, client=client)
    sysprep.update_from_dto(_minimal_sysprep_dto())

    monkeypatch.setattr(
        client.executions,
        "get",
        lambda _exec_id: {"jobOutputs": {}},
    )

    with pytest.raises(ValueError, match=SYSPREP_NO_OUTPUT_PATHS_MSG):
        sysprep.get_results()


@pytest.mark.parametrize(
    ("protein_fixture", "ligand_fixture"),
    [
        pytest.param("brd_protein", "brd_ligand", id="backend_only"),
        pytest.param("registered_protein", "registered_ligand", id="data_platform"),
    ],
)
def test_sysprep_lv2(
    client: DeepOriginClient,
    protein_fixture: str,
    ligand_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    """Exercise ABFE system prep with upload-only vs data-platform entities.

    ``brd_*`` checks the tool end-to-end with file paths only. ``registered_*``
    additionally checks the result-explorer row for this job (tool key, protein
    id, stored ``data`` payload).
    """
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["sysprep"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["sysprep"]["tool_version"],
    ), "System prep tool not registered on platform (expected key/version)."

    protein: Protein = request.getfixturevalue(protein_fixture)
    ligand: Ligand = request.getfixturevalue(ligand_fixture)

    sysprep = SystemPrep(
        protein=protein,
        ligand=ligand,
        client=client,
        add_H_atoms=True,
        protonate_protein=True,
    )
    prepared = sysprep.run()

    assert isinstance(prepared, PreparedSystem), (
        "Expected SystemPrep.run() to return PreparedSystem"
    )
    assert prepared.binding_xml_path
    assert prepared.solvation_xml_path
    assert prepared.system_pdb_path

    if protein_fixture != "registered_protein":
        return

    execution_id = sysprep.id
    assert execution_id is not None

    response = client.results.get_prepared_systems(
        compute_job_id=execution_id,
    )
    records = response["data"]
    assert len(records) >= 1, f"Expected a prepared-system row for job: {execution_id}"
    record = records[0]
    assert record.get("compute_job_id") == execution_id
    assert record.get("tool_key") == TOOL_KEYS_AND_VERSIONS["sysprep"]["tool_key"]
    data = record["data"]
    assert isinstance(data, dict) and len(data) > 0
    assert data.get("protein_id") == protein.id
