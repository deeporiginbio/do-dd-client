"""Tests for import-dataset blocking sync helpers."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR
from deeporigin.drug_discovery.import_dataset_sync import (
    DATA_PLATFORM_DATA_INGESTING_STATUS,
    hydrate_ligand_ids_after_import,
    job_outputs,
    job_outputs_with_execution_id,
    poll_tools_execution_terminal,
    require_project_id,
    require_uniform_scope,
    stage_local_file,
    sync_process_csv,
    sync_process_pdb,
    sync_process_sdf,
    wait_for_data_platform_ingestion,
    workflow_import_smiles_csv,
)
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS


def test_job_outputs_helpers() -> None:
    assert job_outputs({}) == {}
    assert job_outputs({"jobOutputs": "nope"}) == {}
    merged = job_outputs_with_execution_id(
        {"executionId": "exec-1", "jobOutputs": {"ligands": []}}
    )
    assert merged["import_execution_id"] == "exec-1"
    assert merged["ligands"] == []


def test_require_project_id_uses_client_scope(client: DeepOriginClient) -> None:
    assert require_project_id(entity_project_id=None, client=client) == str(
        client.project_id
    )


def test_poll_tools_execution_terminal_rejects_failed_status() -> None:
    client = MagicMock()
    client.executions.wait.return_value = [{"status": "Failed"}]
    with pytest.raises(DeepOriginException, match="import-dataset execution ended"):
        poll_tools_execution_terminal(client, "exec-1", poll_interval=0.01, timeout=1.0)


def test_wait_for_data_platform_ingestion_times_out() -> None:
    client = MagicMock()
    client.executions.search.return_value = {
        "data": [{"status": DATA_PLATFORM_DATA_INGESTING_STATUS, "id": "dp-1"}]
    }
    with pytest.raises(TimeoutError, match="Timed out waiting"):
        wait_for_data_platform_ingestion(
            client,
            "exec-1",
            poll_interval=0.01,
            timeout=0.05,
        )


def test_wait_for_data_platform_ingestion_returns_when_no_execution_row() -> None:
    client = MagicMock()
    client.executions.search.return_value = {"data": []}
    row = wait_for_data_platform_ingestion(
        client,
        "exec-1",
        poll_interval=0.01,
        no_row_timeout=0.05,
        timeout=3600.0,
    )
    assert row == {}


def test_wait_for_data_platform_ingestion_uses_result_explorer_without_dp_row() -> None:
    client = MagicMock()
    client.executions.search.return_value = {"data": []}
    client.results.get.return_value = {
        "data": [{"id": "pose-1", "compute_job_id": "exec-1"}]
    }
    row = wait_for_data_platform_ingestion(
        client,
        "exec-1",
        poll_interval=0.01,
        no_row_timeout=3600.0,
        timeout=3600.0,
    )
    assert row == {}
    client.results.get.assert_called()


def test_wait_for_data_platform_ingestion_failed_status() -> None:
    client = MagicMock()
    client.executions.search.return_value = {
        "data": [{"status": "Failed", "id": "dp-1", "compute_job_id": "exec-1"}]
    }
    with pytest.raises(DeepOriginException, match="Data platform ingestion failed"):
        wait_for_data_platform_ingestion(
            client,
            "exec-1",
            poll_interval=0.01,
            timeout=1.0,
        )


def test_poll_tools_execution_terminal_rejects_unexpected_status() -> None:
    client = MagicMock()
    client.executions.wait.return_value = [{"status": "Running"}]
    with pytest.raises(DeepOriginException, match="unexpected status"):
        poll_tools_execution_terminal(client, "exec-1", poll_interval=0.01, timeout=1.0)


def test_hydrate_ligand_ids_raises_when_platform_row_missing() -> None:
    lig = Ligand.from_smiles("CCO")
    client = MagicMock()
    client.entities.search.return_value = {"data": []}
    client.entities.search_ligands.return_value = {"data": []}
    with pytest.raises(DeepOriginException, match="did not return a ligand id"):
        hydrate_ligand_ids_after_import(
            client,
            [lig],
            compute_job_id="exec-1",
            project_id="proj-1",
            dp_execution_row={"id": "dp-row"},
        )


def test_sync_process_csv_on_mock_server(client: DeepOriginClient) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as handle:
        writer = csv.DictWriter(handle, fieldnames=["smiles", "name"])
        writer.writeheader()
        writer.writerow({"smiles": "CCO", "name": "ethanol"})
        csv_local = handle.name
    remote = stage_local_file(client, csv_local)
    Path(csv_local).unlink(missing_ok=True)
    outputs = sync_process_csv(
        client=client,
        project_id=str(client.project_id),
        file_path=remote,
    )
    assert isinstance(outputs.get("ligands"), list)
    assert outputs["ligands"]


def test_sync_process_sdf_on_mock_server(client: DeepOriginClient) -> None:
    remote = stage_local_file(client, BRD_DATA_DIR / "brd-2.sdf")
    outputs = sync_process_sdf(
        client=client,
        project_id=str(client.project_id),
        file_path=remote,
    )
    assert isinstance(outputs.get("ligands"), list)


def test_workflow_import_smiles_csv_end_to_end(client: DeepOriginClient) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as handle:
        writer = csv.DictWriter(handle, fieldnames=["smiles", "name"])
        writer.writeheader()
        writer.writerow({"smiles": "CCO", "name": "ethanol"})
        csv_local = handle.name
    remote = stage_local_file(client, csv_local)
    Path(csv_local).unlink(missing_ok=True)
    exec_id, row = workflow_import_smiles_csv(
        client=client,
        project_id=str(client.project_id),
        csv_path=remote,
        poll_interval=0.01,
        tools_timeout=30.0,
        ingestion_poll_interval=0.01,
        ingestion_timeout=30.0,
    )
    assert exec_id
    assert row["status"] == "Completed"


def test_require_uniform_scope_accepts_single_value() -> None:
    assert require_uniform_scope(["proj-a"], field_label="project_id") == "proj-a"


def test_require_uniform_scope_rejects_mixed() -> None:
    with pytest.raises(DeepOriginException, match="Mixed project_id"):
        require_uniform_scope(["proj-a", "proj-b"], field_label="project_id")


def test_require_uniform_scope_rejects_empty() -> None:
    with pytest.raises(DeepOriginException, match="project_id is required"):
        require_uniform_scope([None, ""], field_label="project_id")


def test_sync_process_pdb_uses_import_dataset_v3_and_process_pdb_flag(
    client: DeepOriginClient,
) -> None:
    """Entity sync must target import-dataset v3 ``process_pdb`` on the mock server."""
    pdb_path = BRD_DATA_DIR / "brd.pdb"
    remote = stage_local_file(client, pdb_path)
    outputs = sync_process_pdb(
        client=client,
        project_id=str(client.project_id),
        file_path=remote,
        extra_inputs={"protein_name": "brd-demo"},
    )
    proteins = outputs.get("proteins") or []
    assert isinstance(proteins, list)
    assert len(proteins) >= 1
    meta = TOOL_KEYS_AND_VERSIONS["import_dataset"]
    assert meta["tool_version"] == "3"
