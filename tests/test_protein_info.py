"""Tests for protein information helpers."""

from __future__ import annotations

from deeporigin.drug_discovery.external_tools.protein_info import extract_dict_field


def test_extract_dict_field_nested_path() -> None:
    """extract_dict_field traverses nested dictionaries."""
    data = {"data": {"entry": {"title": "My Protein"}}}

    assert extract_dict_field(data, ["data", "entry", "title"]) == "My Protein"


def test_extract_dict_field_missing_key_returns_default() -> None:
    """extract_dict_field returns the default when a key is missing."""
    data = {"data": {"entry": {}}}

    assert extract_dict_field(data, ["data", "entry", "title"], "N/A") == "N/A"


def test_extract_dict_field_none_returns_default() -> None:
    """extract_dict_field returns the default when the resolved value is None."""
    data = {"data": {"entry": {"title": None}}}

    assert extract_dict_field(data, ["data", "entry", "title"], "N/A") == "N/A"
