"""Tests for :class:`deeporigin.drug_discovery.system_prep.SystemPrep`."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.pose import Pose
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.drug_discovery.system_prep import SystemPrep
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import SYSPREP_NO_OUTPUT_PATHS_MSG
from tests.conftest import check_tool_exists

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

# compute_job_id that the mock result-explorer treats as an empty page (no rematch).
_NO_PREPARED_SYSTEM_ROWS_ID = "__no_prepared_system_rows__"


def _minimal_sysprep_dto(
    *,
    execution_id: str = _NO_PREPARED_SYSTEM_ROWS_ID,
    job_outputs: dict | None = None,
) -> dict:
    """Build a minimal tools execution DTO for system prep."""
    sp = TOOL_KEYS_AND_VERSIONS["sysprep"]
    dto: dict = {
        "executionId": execution_id,
        "tool": {"key": sp["tool_key"], "version": sp["tool_version"]},
        "status": "Succeeded",
        "name": "sysprep-test",
        "userInputs": {},
    }
    if job_outputs is not None:
        dto["jobOutputs"] = job_outputs
    return dto


def test_system_prep_get_results_falls_back_to_job_outputs(
    client: DeepOriginClient,
) -> None:
    """When explorer has no rows, ``jobOutputs.system`` is parsed via ``from_json``."""
    system_payload = {
        "binding_xml_file_path": "tool-runs/exec/bsm_system.xml",
        "solvation_xml_ligand_file_path": "tool-runs/exec/solvation_ligand.xml",
        "system_pdb_file_path": "tool-runs/exec/system.pdb",
        "add_H_atoms": True,
        "padding": 1,
        "protein_id": "brd",
        "protonate_protein": True,
        "retain_waters": False,
    }
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    pose = Pose(ligand_id="L", id="P", smiles="CCO")
    sysprep = SystemPrep(protein=protein, pose=pose, client=client)
    sysprep.update_from_dto(
        _minimal_sysprep_dto(job_outputs={"system": system_payload})
    )

    out = sysprep.get_results(
        _minimal_sysprep_dto(job_outputs={"system": system_payload})
    )

    assert isinstance(out, PreparedSystem)
    assert out.binding_xml_path == system_payload["binding_xml_file_path"]
    assert out.system_pdb_path == system_payload["system_pdb_file_path"]


def test_system_prep_get_results_requires_id(client: DeepOriginClient) -> None:
    """``get_results`` raises when ``id`` has not been set."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    pose = Pose(ligand_id="L", id="P", smiles="CCO")
    sysprep = SystemPrep(protein=protein, pose=pose, client=client)

    with pytest.raises(ValueError, match="id is None"):
        sysprep.get_results()


def test_system_prep_get_results_raises_when_no_paths(
    client: DeepOriginClient,
) -> None:
    """When both data platform and ``jobOutputs`` fail, raise sysprep message."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    pose = Pose(ligand_id="L", id="P", smiles="CCO")
    sysprep = SystemPrep(protein=protein, pose=pose, client=client)
    sysprep.update_from_dto(_minimal_sysprep_dto(job_outputs={}))

    with pytest.raises(ValueError, match=SYSPREP_NO_OUTPUT_PATHS_MSG):
        sysprep.get_results(_minimal_sysprep_dto(job_outputs={}))


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
    ligand.sync(client=client)
    sdf = BRD_DATA_DIR / "brd-2.sdf"
    pose = Pose.from_sdf(sdf, ligand=ligand, client=client)

    sysprep = SystemPrep(
        protein=protein,
        pose=pose,
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
