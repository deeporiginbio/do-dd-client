"""Unit tests for Admet helpers (no platform client)."""

from __future__ import annotations

import pytest

from deeporigin.drug_discovery.admet import (
    _endpoints_from_definition,
    _execution_predictions,
    _ligands_from_inputs,
    _ligands_from_list_file_bytes,
    _properties_from_inputs,
    _rows_from_result_explorer,
    _validate_admet_properties,
)


def test_execution_predictions_reads_admet_properties() -> None:
    """Platform jobOutputs use the admet_properties key from the tool schema."""
    row = {
        "smiles": "CCO",
        "ligand_id": "0",
        "hERG_classification": 0.5,
    }
    dto = {"jobOutputs": {"admet_properties": [row]}}
    assert _execution_predictions(dto) == [row]


def test_execution_predictions_falls_back_to_predictions_key() -> None:
    """Legacy mock responses wrapped rows under predictions."""
    row = {"smiles": "CCN", "ligand_id": "1", "AMES_classification": 0.1}
    dto = {"jobOutputs": {"predictions": [row]}}
    assert _execution_predictions(dto) == [row]


def test_execution_predictions_empty_when_job_outputs_missing() -> None:
    """Missing or malformed jobOutputs yields no rows."""
    assert _execution_predictions({}) == []
    assert _execution_predictions({"jobOutputs": None}) == []
    assert _execution_predictions({"jobOutputs": {"other": []}}) == []


def test_endpoints_from_definition_reads_json_schema_enum() -> None:
    """The properties input enum is the Admet endpoint catalog."""
    definition = {
        "inputs": {
            "properties": {
                "properties": {
                    "items": {
                        "enum": ["hERG_classification", "Fu_regression"],
                    }
                }
            }
        }
    }
    assert _endpoints_from_definition(definition) == [
        "hERG_classification",
        "Fu_regression",
    ]


@pytest.mark.parametrize(
    "definition",
    [
        {},
        {"inputs": {}},
        {"inputs": {"properties": {}}},
        {"inputs": {"properties": {"properties": {"items": {}}}}},
        {"inputs": {"properties": {"properties": {"items": {"enum": []}}}}},
        {"inputs": {"properties": {"properties": {"items": {"enum": [1]}}}}},
        {
            "inputs": {
                "properties": {
                    "properties": {
                        "items": {
                            "enum": ["hERG_classification", "hERG_classification"]
                        }
                    }
                }
            }
        },
    ],
)
def test_endpoints_from_definition_rejects_missing_enum(
    definition: dict,
) -> None:
    """A missing or unusable enum fails construction of the allowlist."""
    with pytest.raises(ValueError, match="properties enum"):
        _endpoints_from_definition(definition)


def test_validate_admet_properties_rejects_empty_unknown_and_duplicates() -> None:
    """Draft selections must be a non-empty unique subset of the definition."""
    allowed = frozenset({"hERG_classification", "AMES_classification"})
    assert _validate_admet_properties(["AMES_classification"], allowed=allowed) == [
        "AMES_classification"
    ]
    with pytest.raises(ValueError, match="non-empty"):
        _validate_admet_properties([], allowed=allowed)
    with pytest.raises(ValueError, match="duplicates"):
        _validate_admet_properties(
            ["hERG_classification", "hERG_classification"], allowed=allowed
        )
    with pytest.raises(ValueError, match="Unknown"):
        _validate_admet_properties(["not_an_endpoint"], allowed=allowed)


def test_properties_from_inputs_omitted_is_none() -> None:
    """Historical payloads that omitted properties stay None."""
    assert _properties_from_inputs({}) is None
    assert _properties_from_inputs({"properties": None}) is None
    assert _properties_from_inputs({"properties": ["hERG_classification"]}) == (
        "hERG_classification",
    )


def test_properties_from_inputs_rejects_empty_blank_and_duplicates() -> None:
    """A present properties field must be a non-empty unique list of names."""
    with pytest.raises(ValueError, match="empty"):
        _properties_from_inputs({"properties": []})
    with pytest.raises(ValueError, match="non-empty strings"):
        _properties_from_inputs({"properties": [""]})
    with pytest.raises(ValueError, match="non-empty strings"):
        _properties_from_inputs({"properties": [1]})
    with pytest.raises(ValueError, match="duplicates"):
        _properties_from_inputs(
            {"properties": ["hERG_classification", "hERG_classification"]}
        )


def test_ligands_from_inputs_builds_ligands() -> None:
    """Stored ligand SMILES and ids are restored."""
    ligands = _ligands_from_inputs(
        {"ligands": [{"smiles": "CCO", "id": "lig-1"}, {"smiles": "CCN"}]}
    )
    assert [lig.smiles for lig in ligands] == ["CCO", "CCN"]
    assert ligands[0].id == "lig-1"
    assert ligands[1].id is None


def test_ligands_from_inputs_rejects_missing_rows() -> None:
    """Empty or malformed ligand rows fail rehydration."""
    with pytest.raises(ValueError, match="no ligands"):
        _ligands_from_inputs({})
    with pytest.raises(ValueError, match="not an object"):
        _ligands_from_inputs({"ligands": ["CCO"]})
    with pytest.raises(ValueError, match="no SMILES"):
        _ligands_from_inputs({"ligands": [{"id": "1"}]})


def test_ligands_from_list_file_bytes_parses_rows() -> None:
    """A Ligand list file rehydrates SMILES and platform ids."""
    ligands = _ligands_from_list_file_bytes(b'[{"smiles": "CCO", "id": 7}]')
    assert [(lig.smiles, lig.id) for lig in ligands] == [("CCO", "7")]


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        (b"\xff", "not valid UTF-8"),
        (b"{", "not valid JSON"),
        (b"[]", "non-empty JSON array"),
        (b'{"smiles": "CCO"}', "non-empty JSON array"),
    ],
)
def test_ligands_from_list_file_bytes_rejects_bad_bodies(
    payload: bytes, match: str
) -> None:
    """Corrupt list files raise ValueError instead of a parser exception."""
    with pytest.raises(ValueError, match=match):
        _ligands_from_list_file_bytes(payload)


def test_rows_from_result_explorer_flattens_and_skips_junk() -> None:
    """Nested, flat, and unrecognized result-explorer records."""
    flat = {"ligand_id": "1", "hERG_classification": 0.2}
    nested = {"smiles": "CCO", "AMES_classification": 0.1}
    response = {
        "data": [
            "not-a-record",
            {"data": {"admetproperties": [nested, "junk"]}},
            {"data": flat},
            {"data": {"unrelated": 1}},
        ]
    }
    assert _rows_from_result_explorer(response) == [nested, flat]
    assert _rows_from_result_explorer(None) == []
    assert _rows_from_result_explorer({"data": "nope"}) == []
