"""Tests for ligand/protein upsert and update helpers on Entities."""

from __future__ import annotations

import uuid

import pytest

from deeporigin.platform import DeepOriginClient


def _unique_smiles() -> str:
    """Return a unique aliphatic SMILES string for create tests."""
    suffix = uuid.uuid4().hex[:8]
    return f"CC(C)(C)OC(=O)N{suffix}"


def test_upsert_ligand_create_lv1(client: DeepOriginClient) -> None:
    """upsert_ligand without id creates a new ligand row."""
    smiles = _unique_smiles()
    result = client.entities.upsert_ligand(
        smiles=smiles,
        mol_file="testing/util-tool/new.sdf",
        name=f"upsert-create-{uuid.uuid4().hex[:8]}",
    )

    assert isinstance(result, dict)
    assert "data" in result
    assert result["data"]["id"]
    assert result["data"]["mol_file"] == "testing/util-tool/new.sdf"


def test_upsert_ligand_already_exists_updates_mol_file_lv1(
    client: DeepOriginClient,
) -> None:
    """Duplicate create returns already_exists; upsert patches mol_file when it differs."""
    smiles = _unique_smiles()
    name = f"upsert-dup-{uuid.uuid4().hex[:8]}"
    first = client.entities.upsert_ligand(
        smiles=smiles,
        mol_file="testing/util-tool/first.sdf",
        name=name,
    )
    ligand_id = first["data"]["id"]

    second = client.entities.upsert_ligand(
        smiles=smiles,
        mol_file="testing/util-tool/second.sdf",
        name=name,
    )

    assert second.get("meta", {}).get("disposition") == "already_exists" or (
        second["data"]["mol_file"] == "testing/util-tool/second.sdf"
    )
    assert second["data"]["id"] == ligand_id
    assert second["data"]["mol_file"] == "testing/util-tool/second.sdf"


def test_upsert_ligand_with_id_patches_lv1(client: DeepOriginClient) -> None:
    """upsert_ligand with id performs PATCH only."""
    smiles = _unique_smiles()
    created = client.entities.create_ligand(
        smiles=smiles,
        name=f"upsert-patch-{uuid.uuid4().hex[:8]}",
        mol_file="testing/util-tool/before.sdf",
    )
    ligand_id = created["data"]["id"]

    updated = client.entities.upsert_ligand(
        id=ligand_id,
        smiles=smiles,
        mol_file="testing/util-tool/after.sdf",
    )

    assert updated["data"]["id"] == ligand_id
    assert updated["data"]["mol_file"] == "testing/util-tool/after.sdf"


def test_update_ligand_lv1(client: DeepOriginClient) -> None:
    """update_ligand patches mol_file via PATCH."""
    smiles = _unique_smiles()
    created = client.entities.create_ligand(
        smiles=smiles,
        name=f"update-lig-{uuid.uuid4().hex[:8]}",
    )
    ligand_id = created["data"]["id"]

    updated = client.entities.update_ligand(
        ligand_id,
        mol_file="testing/util-tool/patched.sdf",
    )

    assert updated["data"]["id"] == ligand_id
    assert updated["data"]["mol_file"] == "testing/util-tool/patched.sdf"


def test_upsert_protein_with_id_patches_lv1(client: DeepOriginClient) -> None:
    """upsert_protein with id updates file_path."""
    created = client.entities.create_protein(
        file_path="testing/util-tool/protein-before.pdb",
    )
    protein_id = created["data"]["id"]

    updated = client.entities.upsert_protein(
        id=protein_id,
        file_path="testing/util-tool/protein-after.pdb",
    )

    assert updated["data"]["id"] == protein_id
    assert updated["data"]["file_path"] == "testing/util-tool/protein-after.pdb"


def test_update_protein_lv1(client: DeepOriginClient) -> None:
    """update_protein patches file_path."""
    created = client.entities.create_protein(
        file_path="testing/util-tool/update-before.pdb",
    )
    protein_id = created["data"]["id"]

    updated = client.entities.update_protein(
        protein_id,
        file_path="testing/util-tool/update-after.pdb",
    )

    assert updated["data"]["id"] == protein_id
    assert updated["data"]["file_path"] == "testing/util-tool/update-after.pdb"


def test_upsert_ligand_requires_smiles(client: DeepOriginClient) -> None:
    """upsert_ligand rejects empty id-only update path without smiles."""
    with pytest.raises(TypeError):
        client.entities.upsert_ligand(id="08TESTID12345")  # type: ignore[call-arg]
