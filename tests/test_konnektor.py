"""Tests for :class:`~deeporigin.drug_discovery.konnektor.Konnektor`."""

from __future__ import annotations

import pytest

from deeporigin.drug_discovery import Konnektor, KonnektorResult, Ligand, LigandSet
from deeporigin.drug_discovery.konnektor import _konnektor_result_from_dto
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient


def test_konnektor_requires_two_ligands(client: DeepOriginClient) -> None:
    """Konnektor rejects singleton ligand sets."""
    with pytest.raises(ValueError, match="at least two ligands"):
        Konnektor(ligands=[Ligand.from_smiles("CCO")], client=client)


def test_konnektor_make_payload_includes_file_paths_for_synced_ligands(
    client: DeepOriginClient,
    registered_ligand: Ligand,
    registered_ligand_brd3: Ligand,
) -> None:
    """Payload rows include 3D structure paths when available."""
    job = Konnektor(
        ligands=LigandSet(ligands=[registered_ligand, registered_ligand_brd3]),
        network_type="star",
        client=client,
        name="test network",
    )

    payload = job._make_payload(approve_amount=5, sync=True)

    assert payload["inputs"]["network_type"] == "star"
    assert payload["name"] == "test network"
    assert payload["sync"] is True
    assert payload["approveAmount"] == 5
    assert payload["outputs"] == {}
    assert payload["metadata"] == {}

    rows = payload["inputs"]["ligands"]
    assert len(rows) == 2
    assert rows[0] == {
        "file_path": registered_ligand.remote_path,
        "id": registered_ligand.id,
        "smiles": registered_ligand.smiles,
    }
    assert rows[1] == {
        "file_path": registered_ligand_brd3.remote_path,
        "id": registered_ligand_brd3.id,
        "smiles": registered_ligand_brd3.smiles,
    }


def test_konnektor_make_payload_uses_file_path_without_id(
    client: DeepOriginClient,
    brd_ligand: Ligand,
    brd_ligand_brd3: Ligand,
) -> None:
    """File paths are still sent for file-only ligands."""
    job = Konnektor(
        ligands=[brd_ligand, brd_ligand_brd3],
        client=client,
    )

    payload = job._make_payload(approve_amount=None, sync=True)

    rows = payload["inputs"]["ligands"]
    assert payload["inputs"]["network_type"] == "mst"
    assert len(rows) == 2
    assert rows[0] == {
        "file_path": brd_ligand.remote_path,
        "smiles": brd_ligand.smiles,
    }
    assert rows[1] == {
        "file_path": brd_ligand_brd3.remote_path,
        "smiles": brd_ligand_brd3.smiles,
    }


def _konnektor_v05_dto(
    *,
    edges: list[dict[str, str]],
    is_connected: bool = True,
    network_html: str = "<html><body>network</body></html>",
) -> dict[str, object]:
    """Build a v0.5 Konnektor execution DTO for unit tests."""
    return {
        "jobOutputs": {
            "ligand_network": {
                "edges": edges,
                "is_connected": is_connected,
                "network": {},
                "network_html_file": "tool-runs/test/network.html",
            },
            "network_html": network_html,
        }
    }


def test_konnektor_result_from_dto_resolves_pairs(
    registered_ligand: Ligand,
    registered_ligand_brd3: Ligand,
) -> None:
    """``_konnektor_result_from_dto`` resolves edges under ``ligand_network``."""
    ligands = LigandSet(ligands=[registered_ligand, registered_ligand_brd3])
    dto = _konnektor_v05_dto(
        edges=[
            {
                "source": registered_ligand.id,
                "target": registered_ligand_brd3.id,
            }
        ],
    )

    result = _konnektor_result_from_dto(dto, ligands=ligands)

    assert isinstance(result, KonnektorResult)
    assert result.pairs == [(registered_ligand, registered_ligand_brd3)]
    assert result.is_connected is True
    assert result.network_html == "<html><body>network</body></html>"


def test_konnektor_result_from_dto_rejects_flat_edges(
    registered_ligand: Ligand,
    registered_ligand_brd3: Ligand,
) -> None:
    """Flat ``jobOutputs.edges`` (v0.4) is rejected."""
    ligands = LigandSet(ligands=[registered_ligand, registered_ligand_brd3])
    dto = {
        "jobOutputs": {
            "edges": [
                {
                    "source": registered_ligand.id,
                    "target": registered_ligand_brd3.id,
                }
            ],
            "is_connected": True,
            "network": {},
        }
    }

    with pytest.raises(DeepOriginException, match="ligand_network"):
        _konnektor_result_from_dto(dto, ligands=ligands)


def test_konnektor_run_returns_konnektor_result(
    client: DeepOriginClient,
    registered_ligand: Ligand,
    registered_ligand_brd3: Ligand,
) -> None:
    """``run`` returns a :class:`KonnektorResult` suitable for RBFE."""
    if client.env != "local":
        pytest.skip("Konnektor run integration requires the local mock server.")

    job = Konnektor(
        ligands=[registered_ligand, registered_ligand_brd3],
        client=client,
    )
    result = job.run()

    assert isinstance(result, KonnektorResult)
    assert result.pairs == [(registered_ligand, registered_ligand_brd3)]
    assert result.is_connected is True
    assert result.network_html
    assert job.status == "Completed"
    assert job.id is not None


def test_konnektor_run_resolves_file_stem_when_id_missing(
    client: DeepOriginClient,
    brd_ligand: Ligand,
    brd_ligand_brd3: Ligand,
) -> None:
    """Edge endpoints match file stems when ligands have no platform id."""
    if client.env != "local":
        pytest.skip("Konnektor run integration requires the local mock server.")

    brd_ligand.id = None
    brd_ligand_brd3.id = None

    result = Konnektor(
        ligands=[brd_ligand, brd_ligand_brd3],
        client=client,
    ).run()

    assert result is not None
    assert result.pairs == [(brd_ligand, brd_ligand_brd3)]


def test_konnektor_run_quote_returns_none(
    client: DeepOriginClient,
    registered_ligand: Ligand,
    registered_ligand_brd3: Ligand,
) -> None:
    """``quote=True`` requests a quotation and does not extract edges."""
    if client.env != "local":
        pytest.skip("Konnektor run integration requires the local mock server.")

    job = Konnektor(
        ligands=[registered_ligand, registered_ligand_brd3],
        client=client,
    )

    assert job.run(quote=True) is None
    assert job.status == "Quoted"
    assert job.estimate == 1.23
