"""Tests for import-dataset blocking sync helpers."""

from __future__ import annotations

import pytest

from deeporigin.drug_discovery.import_dataset_sync import require_uniform_scope
from deeporigin.exceptions import DeepOriginException


def test_require_uniform_scope_accepts_single_value() -> None:
    assert require_uniform_scope(["proj-a"], field_label="project_id") == "proj-a"


def test_require_uniform_scope_rejects_mixed() -> None:
    with pytest.raises(DeepOriginException, match="Mixed project_id"):
        require_uniform_scope(["proj-a", "proj-b"], field_label="project_id")


def test_require_uniform_scope_rejects_empty() -> None:
    with pytest.raises(DeepOriginException, match="project_id is required"):
        require_uniform_scope([None, ""], field_label="project_id")
