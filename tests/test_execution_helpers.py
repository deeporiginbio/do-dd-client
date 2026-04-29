"""Tests for ``deeporigin.drug_discovery.execution_helpers``."""

from __future__ import annotations

from deeporigin.drug_discovery.execution_helpers import price_total_from_execution_dto


def test_price_total_from_execution_dto_missing() -> None:
    """Returns None when there is no successful quotation."""
    assert price_total_from_execution_dto({}) is None
    assert price_total_from_execution_dto({"quotationResult": {}}) is None


def test_price_total_from_execution_dto_present() -> None:
    """Parses priceTotal from the first successful quotation row."""
    dto = {
        "quotationResult": {
            "successfulQuotations": [{"priceTotal": 1.5}],
        }
    }
    assert price_total_from_execution_dto(dto) == 1.5
