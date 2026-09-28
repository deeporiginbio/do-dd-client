"""Tests for large LigandSet sync via import-dataset workflow (DDOS-7979)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from deeporigin.drug_discovery.import_dataset_sync import (
    DATA_PLATFORM_DATA_INGESTING_STATUS,
    hydrate_ligand_ids_after_import,
    wait_for_data_platform_ingestion,
)
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.platform.client import DeepOriginClient


def test_wait_for_data_platform_ingestion_leaves_data_ingesting() -> None:
    client = MagicMock()
    client.executions.search.side_effect = [
        {"data": [{"status": DATA_PLATFORM_DATA_INGESTING_STATUS, "id": "dp-1"}]},
        {"data": [{"status": "Completed", "id": "dp-1"}]},
    ]
    row = wait_for_data_platform_ingestion(
        client,
        "exec-1",
        poll_interval=0.01,
        timeout=5.0,
    )
    assert row["status"] == "Completed"
    assert client.executions.search.call_count == 2


def test_hydrate_ligand_ids_from_subjects_and_smiles_fallback() -> None:
    lig_a = Ligand.from_smiles("CCO")
    lig_b = Ligand.from_smiles("CCCO")
    client = MagicMock()
    client.entities.search.return_value = {
        "data": [
            {
                "entity_type": "ligand",
                "entity_canonical_id": "lig-a",
            }
        ]
    }
    client.entities.get_ligands.return_value = [
        {"id": "lig-a", "canonical_smiles": lig_a.canonical_smiles},
    ]
    client.entities.search_ligands.return_value = {
        "data": [{"id": "lig-b", "canonical_smiles": lig_b.canonical_smiles}],
    }

    hydrate_ligand_ids_after_import(
        client,
        [lig_a, lig_b],
        compute_job_id="exec-1",
        project_id="proj-1",
        dp_execution_row={"id": "dp-row-1"},
    )
    assert lig_a.id == "lig-a"
    assert lig_b.id == "lig-b"


def test_ligand_set_sync_uses_workflow_above_served_cap(
    client: DeepOriginClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """More than MAX served ligands routes through csv_path workflow import."""
    monkeypatch.setattr(
        "deeporigin.drug_discovery.import_dataset_sync.MAX_SERVED_FILE_LIGAND_RECORDS",
        2,
    )
    smiles = [f"C{'C' * i}" for i in range(3)]
    ls = LigandSet.from_smiles(smiles)
    ls.sync(client=client)
    assert len(ls) == 3
    assert all(lig.id for lig in ls.ligands)
