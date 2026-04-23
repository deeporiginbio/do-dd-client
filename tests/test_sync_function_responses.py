"""Unit tests for :class:`~deeporigin.drug_discovery.sync_function_responses.SyncFunctionResponses`."""

from __future__ import annotations

import pytest

from deeporigin.drug_discovery.sync_function_responses import SyncFunctionResponses


def _quoted_response(*, price_total: float, status: str = "Quoted") -> dict:
    """Build a minimal API-shaped dict with quotationResult."""
    return {
        "status": status,
        "quotationResult": {
            "anyFailed": False,
            "failedQuotations": [],
            "successfulQuotations": [
                {
                    "itemCode": "DO_POCKET_FINDER",
                    "priceTotal": price_total,
                    "status": "OK",
                }
            ],
        },
    }


def test_sync_function_responses_estimate_free_tier_zero() -> None:
    """Staging/dev free-tier quotes return priceTotal 0; estimate must be 0.0 not None."""
    r = _quoted_response(price_total=0.0, status="Approved")
    assert SyncFunctionResponses([r]).estimate == pytest.approx(0.0)


def test_sync_function_responses_estimate_paid() -> None:
    """Non-zero quotations still return the dollar amount."""
    r = _quoted_response(price_total=10.0)
    assert SyncFunctionResponses([r]).estimate == pytest.approx(10.0)


def test_sync_function_responses_estimate_quoted_status() -> None:
    """Both Quoted and Approved are valid estimate statuses."""
    assert SyncFunctionResponses(
        [_quoted_response(price_total=0.0)]
    ).estimate == pytest.approx(0.0)


@pytest.mark.parametrize("status", ["Succeeded", "Completed", "Running"])
def test_sync_function_responses_estimate_wrong_status(status: str) -> None:
    """Estimate is None when execution status is not a quotation status."""
    r = _quoted_response(price_total=0.0)
    r["status"] = status
    assert SyncFunctionResponses([r]).estimate is None


def test_sync_function_responses_estimate_missing_quotation() -> None:
    """No successfulQuotations means no estimate."""
    r = {"status": "Quoted", "quotationResult": {"successfulQuotations": []}}
    assert SyncFunctionResponses([r]).estimate is None
