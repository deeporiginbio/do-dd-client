"""Tests for drug_discovery.utils helpers."""

from __future__ import annotations

from contextlib import contextmanager
from io import StringIO
import json
from unittest.mock import patch

from deeporigin.drug_discovery.utils import _load_params, _set_test_run, is_test_run


def test_is_test_run_nested_dict() -> None:
    """is_test_run finds test_run=1 in nested dicts."""
    payload = {"outer": {"inner": {"test_run": 1}}}

    assert is_test_run(payload) is True


def test_is_test_run_nested_list() -> None:
    """is_test_run finds test_run=1 inside lists."""
    payload = [{"foo": 1}, [{"test_run": 1}]]

    assert is_test_run(payload) is True


def test_is_test_run_false() -> None:
    """is_test_run returns False when test_run is absent."""
    assert is_test_run({"foo": "bar"}) is False


def test_set_test_run_recurses() -> None:
    """_set_test_run sets every test_run key in nested structures."""
    payload = {
        "test_run": 0,
        "nested": [{"test_run": 0}, {"other": {"test_run": 0}}],
    }

    _set_test_run(payload, value=1)

    assert payload["test_run"] == 1
    assert payload["nested"][0]["test_run"] == 1
    assert payload["nested"][1]["other"]["test_run"] == 1


def test_load_params_reads_json() -> None:
    """_load_params loads JSON from the packaged params resource."""
    fixture = {"effort": 2, "mode": "fast"}

    @contextmanager
    def fake_open_text(_package: str, resource: str):
        assert resource == "docking.json"
        yield StringIO(json.dumps(fixture))

    with patch(
        "deeporigin.drug_discovery.utils.importlib.resources.open_text",
        fake_open_text,
    ):
        assert _load_params("docking") == fixture
