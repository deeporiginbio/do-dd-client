"""Tests for import-dataset blocking sync helpers."""

from __future__ import annotations

import csv
from pathlib import Path
import tempfile
from unittest.mock import MagicMock

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR
from deeporigin.drug_discovery.import_dataset_sync import (
    apply_ligand_import_job_outputs,
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


def test_apply_ligand_import_job_outputs_warns_on_partial_import() -> None:
    ligands = [Ligand.from_smiles("CCO"), Ligand.from_smiles("CCN")]
    outputs = {
        "ligands": [{"id": "lig-1", "record_index": 0}],
        "import_execution_id": "exec-partial",
    }
    mock_client = MagicMock()
    mock_client.user_logs.search.return_value = {
        "data": [
            {
                "log_level": "error",
                "message": "Import: 1 ligand(s) had invalid SMILES.",
            }
        ]
    }
    with pytest.warns(UserWarning, match="1 of 2 ligand\\(s\\) were not imported"):
        apply_ligand_import_job_outputs(ligands, outputs, client=mock_client)
    assert ligands[0].id == "lig-1"
    assert ligands[1].id is None


def test_apply_ligand_import_job_outputs_warns_when_user_log_search_fails() -> None:
    ligands = [Ligand.from_smiles("CCO"), Ligand.from_smiles("CCN")]
    outputs = {
        "ligands": [{"id": "lig-1", "record_index": 0}],
        "import_execution_id": "exec-partial",
    }
    mock_client = MagicMock()
    mock_client.user_logs.search.side_effect = RuntimeError("user_logs unavailable")
    with pytest.warns(UserWarning, match="1 of 2 ligand\\(s\\) were not imported"):
        apply_ligand_import_job_outputs(ligands, outputs, client=mock_client)
    assert ligands[0].id == "lig-1"


def test_partial_import_warning_includes_mock_user_log_error_message(
    client: DeepOriginClient,
) -> None:
    """Partial served import enriches warnings via the mock user_logs search route."""
    invalid = "O=C(NCA1)CN1CCOCC1"
    fd = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", newline="")
    writer = csv.writer(fd)
    writer.writerow(["smiles", "name"])
    writer.writerow(["CCO", "ok"])
    writer.writerow([invalid, "bad"])
    fd.close()
    remote = stage_local_file(client, fd.name)
    Path(fd.name).unlink(missing_ok=True)
    outputs = sync_process_csv(
        client=client,
        project_id=str(client.project_id),
        file_path=remote,
    )
    ligands = [Ligand.from_smiles("CCO"), Ligand.from_smiles("CCN")]
    with pytest.warns(UserWarning) as records:
        apply_ligand_import_job_outputs(ligands, outputs, client=client)
    assert ligands[0].id
    assert ligands[1].id is None
    messages = " ".join(str(w.message) for w in records)
    assert "invalid SMILES" in messages
    assert "1 of 2 ligand(s) were not imported" in messages


def test_apply_ligand_import_job_outputs_uses_positional_rows_only_when_complete() -> (
    None
):
    ligands = [Ligand.from_smiles("CCO"), Ligand.from_smiles("CCN")]
    outputs = {"ligands": [{"id": "lig-1"}, {"id": "lig-2"}]}
    apply_ligand_import_job_outputs(ligands, outputs)
    assert ligands[0].id == "lig-1"
    assert ligands[1].id == "lig-2"


def test_apply_ligand_import_job_outputs_partial_without_record_index_raises() -> None:
    ligands = [
        Ligand.from_smiles("CCO"),
        Ligand.from_smiles("CCN"),
        Ligand.from_smiles("CCC"),
    ]
    outputs = {
        "ligands": [{"id": "lig-1"}, {"id": "lig-3"}],
        "import_execution_id": "exec-ambiguous",
    }
    with pytest.raises(DeepOriginException, match="missing index 0"):
        apply_ligand_import_job_outputs(ligands, outputs, client=MagicMock())


def test_apply_ligand_import_job_outputs_raises_when_none_imported() -> None:
    ligands = [Ligand.from_smiles("CCO")]
    outputs = {"ligands": [], "import_execution_id": "exec-empty"}
    with pytest.raises(DeepOriginException, match="missing index 0"):
        apply_ligand_import_job_outputs(ligands, outputs, client=MagicMock())


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


def test_sync_process_csv_mixed_invalid_returns_partial_job_outputs(
    client: DeepOriginClient,
) -> None:
    """Mock served import-dataset skips invalid CSV rows (DDOS-8713)."""
    invalid = "O=C(NCA1)CN1CCOCC1"
    fd = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", newline="")
    writer = csv.writer(fd)
    writer.writerow(["smiles", "name"])
    writer.writerow(["CCO", "ok"])
    writer.writerow([invalid, "bad"])
    fd.close()
    remote = stage_local_file(client, fd.name)
    Path(fd.name).unlink(missing_ok=True)
    outputs = sync_process_csv(
        client=client,
        project_id=str(client.project_id),
        file_path=remote,
    )
    assert outputs.get("import_execution_id")
    rows = outputs.get("ligands") or []
    assert len(rows) == 1
    assert rows[0]["record_index"] == 0


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


def test_sync_process_pdb_uses_import_dataset_v4_and_process_pdb_flag(
    client: DeepOriginClient,
) -> None:
    """Entity sync must target import-dataset v4 ``process_pdb`` on the mock server."""
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
    assert meta["tool_version"] == "4"
