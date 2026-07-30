"""Unit tests for Admet execution DTO parsing helpers."""

from __future__ import annotations

from deeporigin.drug_discovery.admet import _execution_predictions


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
