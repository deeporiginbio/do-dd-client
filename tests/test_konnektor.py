"""Tests for :class:`~deeporigin.drug_discovery.konnektor.Konnektor`."""

from __future__ import annotations

import pytest

from deeporigin.drug_discovery import Konnektor, Ligand, LigandSet
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


def test_konnektor_run_returns_ligand_pairs(
    client: DeepOriginClient,
    registered_ligand: Ligand,
    registered_ligand_brd3: Ligand,
) -> None:
    """``run`` returns ligand pairs suitable for RBFE."""
    if client.env != "local":
        pytest.skip("Konnektor run integration requires the local mock server.")

    job = Konnektor(
        ligands=[registered_ligand, registered_ligand_brd3],
        client=client,
    )
    pairs = job.run()

    assert pairs == [(registered_ligand, registered_ligand_brd3)]
    assert job.status == "Succeeded"
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

    pairs = Konnektor(
        ligands=[brd_ligand, brd_ligand_brd3],
        client=client,
    ).run()

    assert pairs == [(brd_ligand, brd_ligand_brd3)]


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
