"""Tests for large LigandSet sync via import-dataset workflow (DDOS-7979)."""

from __future__ import annotations

import csv
from pathlib import Path
import tempfile

import pytest

from deeporigin.drug_discovery.import_dataset_sync import (
    poll_tools_execution_terminal,
    run_import_dataset_workflow,
    stage_local_file,
    wait_for_data_platform_ingestion,
)
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.platform.client import DeepOriginClient


def _write_smiles_csv(path: Path, smiles: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["smiles", "name"])
        writer.writeheader()
        for idx, smi in enumerate(smiles):
            writer.writerow({"smiles": smi, "name": f"lig-{idx}"})


def test_wait_for_data_platform_ingestion_on_mock_server(
    client: DeepOriginClient,
) -> None:
    """``Executions.search(compute_job_id=...)`` must filter before status polling."""
    smiles = ["CCO", "CCCO"]
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as handle:
        _write_smiles_csv(Path(handle.name), smiles)
        csv_local = handle.name
    remote = stage_local_file(client, csv_local)
    Path(csv_local).unlink(missing_ok=True)

    dto = run_import_dataset_workflow(
        inputs={
            "csv_path": remote,
            "mapper": [
                {"field": "smiles", "json-path": "ligands.smiles"},
                {"field": "name", "json-path": "ligands.name"},
            ],
            "database_key": "deeporigin.attributes_catalog",
            "database_version": "1.0.0",
        },
        project_id=str(client.project_id),
        client=client,
    )
    execution_id = str(dto["executionId"])
    poll_tools_execution_terminal(
        client,
        execution_id,
        poll_interval=0.01,
        timeout=30.0,
    )
    row = wait_for_data_platform_ingestion(
        client,
        execution_id,
        poll_interval=0.01,
        timeout=30.0,
    )
    assert row["status"] == "Completed"
    assert row["compute_job_id"] == execution_id


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
    for idx, lig in enumerate(ls.ligands):
        lig.name = f"lig-{idx}"
    ls.sync(client=client)
    assert len(ls) == 3
    assert all(lig.id for lig in ls.ligands)


def test_ligand_set_workflow_sync_preserves_names(
    client: DeepOriginClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Workflow CSV import maps ``name`` via the shared mapper."""
    monkeypatch.setattr(
        "deeporigin.drug_discovery.import_dataset_sync.MAX_SERVED_FILE_LIGAND_RECORDS",
        1,
    )
    lig = Ligand.from_smiles("CCO")
    lig.name = "ethanol-demo"
    ls = LigandSet([lig, Ligand.from_smiles("CCC")])
    ls.sync(client=client)
    assert ls.ligands[0].name == "ethanol-demo"
