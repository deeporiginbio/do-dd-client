"""Tests for import-dataset blocking sync helpers."""

from __future__ import annotations

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR
from deeporigin.drug_discovery.import_dataset_sync import (
    require_uniform_scope,
    stage_local_file,
    sync_process_pdb,
)
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS


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
