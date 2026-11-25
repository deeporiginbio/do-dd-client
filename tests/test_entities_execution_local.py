"""Local mock-server tests: entity creates name the run that produced them."""

from __future__ import annotations

from typing import TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

_RUN_ID = "11111111-2222-4333-8444-555555555555"


def _unique_smiles() -> str:
    """Return a SMILES no other test creates (the mock refuses duplicate ligands)."""
    return "C" * (50 + uuid.uuid4().int % 2000)


def _output_links(client: DeepOriginClient, entity_id: str) -> list[dict]:
    """Return the ``execution_subjects`` rows linking a run to ``entity_id``."""
    response = client.entities.search(
        "execution_subjects",
        filter_dict={"entity_canonical_id": {"eq": entity_id}},
    )
    return response["data"]


def test_create_protein_links_the_run(client: DeepOriginClient) -> None:
    """``create_protein(execution_id=...)`` records the run as the protein's producer."""
    remote = f"testing/produced-{uuid.uuid4().hex[:12]}.pdb"
    created = client.entities.create_protein(file_path=remote, execution_id=_RUN_ID)

    links = _output_links(client, created["data"]["id"])

    assert [(link["execution_id"], link["role"]) for link in links] == [
        (_RUN_ID, "output")
    ]


def test_create_ligand_links_the_run(client: DeepOriginClient) -> None:
    """``create_ligand(execution_id=...)`` records the run as the ligand's producer."""
    created = client.entities.create_ligand(
        smiles=_unique_smiles(), execution_id=_RUN_ID
    )

    links = _output_links(client, created["data"]["id"])

    assert [(link["execution_id"], link["entity_type"]) for link in links] == [
        (_RUN_ID, "ligand")
    ]


def test_batch_create_ligands_links_every_row(client: DeepOriginClient) -> None:
    """``batch_create_ligands(execution_id=...)`` links each created ligand."""
    created = client.entities.batch_create_ligands(
        rows=[{"smiles": _unique_smiles()}, {"smiles": _unique_smiles()}],
        execution_id=_RUN_ID,
    )

    for row in created["data"]:
        assert [link["execution_id"] for link in _output_links(client, row["id"])] == [
            _RUN_ID
        ]


def test_create_without_execution_id_links_nothing(client: DeepOriginClient) -> None:
    """A create that names no run sends no header, so nothing is linked."""
    created = client.entities.create_ligand(smiles=_unique_smiles())

    assert _output_links(client, created["data"]["id"]) == []
