"""Tests for import-dataset blocking sync helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from deeporigin.drug_discovery.import_dataset_sync import (
    require_uniform_scope,
    sync_process_pdb,
)
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS


def test_require_uniform_scope_accepts_single_value() -> None:
    assert require_uniform_scope(["proj-a"], field_label="project_id") == "proj-a"


def test_require_uniform_scope_rejects_mixed() -> None:
    with pytest.raises(DeepOriginException, match="Mixed project_id"):
        require_uniform_scope(["proj-a", "proj-b"], field_label="project_id")


def test_require_uniform_scope_rejects_empty() -> None:
    with pytest.raises(DeepOriginException, match="project_id is required"):
        require_uniform_scope([None, ""], field_label="project_id")


def test_sync_process_pdb_uses_import_dataset_v3_and_process_pdb_flag() -> None:
    """Entity sync must target import-dataset v3 ``process_pdb`` (not v2 ``register_protein``)."""
    client = MagicMock()
    client.executions.create.return_value = {"jobOutputs": {"proteins": []}}

    sync_process_pdb(
        client=client,
        project_id="proj-1",
        file_path="imports/staging/x.pdb",
        extra_inputs={"protein_name": "demo"},
    )

    meta = TOOL_KEYS_AND_VERSIONS["import_dataset"]
    client.executions.create.assert_called_once_with(
        tool_key=meta["tool_key"],
        tool_version=meta["tool_version"],
        data={
            "inputs": {
                "process_pdb": True,
                "file_path": "imports/staging/x.pdb",
                "protein_name": "demo",
            },
            "outputs": {},
            "metadata": {},
            "sync": True,
            "projectId": "proj-1",
            "visibility": "hidden",
        },
    )
    assert meta["tool_version"] == "3"
