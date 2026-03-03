"""Tests for the FunctionResult class."""

import json
from pathlib import Path

import pytest

from deeporigin.functions.result import FunctionResult

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DOCKING_FIXTURES = FIXTURES_DIR / "function-runs" / "deeporigin.docking"

COMPLETED_FIXTURE = (
    DOCKING_FIXTURES
    / "7327071365baa19d589f03adeaf910cf5b22645976a57c19ea65bf301c9fa7e0.json"
)
QUOTED_FIXTURE = DOCKING_FIXTURES / "quoted.json"


@pytest.fixture()
def completed_response() -> dict:
    """Load a real completed docking response from fixtures."""
    return json.loads(COMPLETED_FIXTURE.read_text())


@pytest.fixture()
def quoted_response() -> dict:
    """Load a real quoted docking response from fixtures."""
    return json.loads(QUOTED_FIXTURE.read_text())


# --- single-response tests ---


def test_basic_properties(completed_response):
    """Test that status, id, and function_outputs are extracted correctly."""
    result = FunctionResult([completed_response])

    assert result.status == "Completed"
    assert result.id == "39334a67-8a64-4f00-bad4-ee3dd9c4bf72"
    assert len(result.function_outputs[0]["poses"]) == 16


def test_response_returns_first_dict(completed_response):
    """Test that .response returns the first response dict."""
    result = FunctionResult([completed_response])
    assert result.response is completed_response


def test_responses_returns_full_list(completed_response):
    """Test that .responses returns the full list."""
    result = FunctionResult([completed_response])
    assert result.responses == [completed_response]


def test_cost_from_completed_response(completed_response):
    """Test that a completed run has cost set and estimate None."""
    result = FunctionResult([completed_response])
    assert result.cost == pytest.approx(0.2)
    assert result.estimate is None


def test_estimate_from_quoted_response(quoted_response):
    """Test that a quoted run has estimate set and cost None."""
    result = FunctionResult([quoted_response])
    assert result.estimate == pytest.approx(0.2)
    assert result.cost is None


def test_estimate_from_approved_response(quoted_response):
    """Test that an Approved response (quote=True) has estimate set and cost None."""
    approved = {**quoted_response, "status": "Approved"}
    result = FunctionResult([approved])
    assert result.estimate == pytest.approx(0.2)
    assert result.cost is None


def test_estimate_none_when_missing():
    """Test that estimate is None when quotationResult is absent."""
    result = FunctionResult([{"status": "Quoted"}])
    assert result.estimate is None


def test_cost_none_when_missing():
    """Test that cost is None when quotationResult is absent."""
    result = FunctionResult([{"status": "Completed", "functionOutputs": {}}])
    assert result.cost is None


def test_cost_none_when_empty_quotations():
    """Test that cost is None when successfulQuotations is empty."""
    result = FunctionResult(
        [
            {
                "status": "Completed",
                "quotationResult": {
                    "anyFailed": False,
                    "successfulQuotations": [],
                },
            }
        ]
    )
    assert result.cost is None


def test_function_outputs_empty_when_quoted(quoted_response):
    """Test that function_outputs returns empty dict for a quoted response."""
    result = FunctionResult([quoted_response])
    assert result.function_outputs == [{}]


# --- multi-response tests ---


def test_cost_sums_across_responses(completed_response):
    """Test that cost is summed across multiple completed responses."""
    result = FunctionResult(
        [completed_response, completed_response, completed_response]
    )
    assert result.cost == pytest.approx(0.6)
    assert result.estimate is None


def test_estimate_sums_across_responses(quoted_response):
    """Test that estimate is summed across multiple quoted responses."""
    result = FunctionResult([quoted_response, quoted_response])
    assert result.estimate == pytest.approx(0.4)
    assert result.cost is None


def test_mixed_statuses_give_no_estimate(completed_response, quoted_response):
    """Test that mixing quoted and completed responses gives no estimate."""
    result = FunctionResult([completed_response, quoted_response])
    assert result.estimate is None


def test_function_outputs_from_multiple_responses(completed_response):
    """Test that function_outputs returns a list from all responses."""
    result = FunctionResult([completed_response, completed_response])
    assert len(result.function_outputs) == 2
    assert all("poses" in outputs for outputs in result.function_outputs)


def test_repr_multi_response(completed_response):
    """Test that repr shows count for multiple responses."""
    result = FunctionResult([completed_response, completed_response])
    r = repr(result)
    assert "n=2" in r
    assert "cost=$0.40" in r


# --- attribute assignment & repr ---


def test_direct_attribute_assignment(completed_response):
    """Test that arbitrary attributes can be set directly on the instance."""
    result = FunctionResult([completed_response])
    result.poses = ["pose_a", "pose_b"]

    assert result.poses == ["pose_a", "pose_b"]


def test_multiple_attribute_assignments(completed_response):
    """Test setting multiple custom attributes."""
    result = FunctionResult([completed_response])
    result.alpha = 42
    result.beta = "hello"

    assert result.alpha == 42
    assert result.beta == "hello"


def test_repr_completed(completed_response):
    """Test __repr__ for a single completed response."""
    result = FunctionResult([completed_response])
    r = repr(result)
    assert "function='deeporigin.docking/0.4.0'" in r
    assert "status='Completed'" in r
    assert "cost=$0.20" in r


def test_repr_minimal():
    """Test __repr__ with an empty response."""
    result = FunctionResult([{}])
    assert repr(result) == "FunctionResult()"


def test_id_none_when_missing():
    """Test that id is None when absent from response."""
    result = FunctionResult([{"status": "Completed"}])
    assert result.id is None


def test_status_none_when_missing():
    """Test that status is None when absent from response."""
    result = FunctionResult([{}])
    assert result.status is None


def test_empty_responses():
    """Test that an empty response list gives None for all properties."""
    result = FunctionResult([])
    assert result.status is None
    assert result.id is None
    assert result.estimate is None
    assert result.cost is None
    assert result.function_outputs == []


# --- protein.dock(quote=True) flow ---


def test_dock_quote_produces_estimate_not_cost(quoted_response):
    """Test that protein.dock(quote=True) produces estimate, not cost.

    Simulates the aggregated result from protein.dock(quote=True) where
    each ligand gets an Approved response from the API.
    """
    approved = {**quoted_response, "status": "Approved"}
    result = FunctionResult([approved, approved, approved])
    result.poses = None

    assert result.estimate is not None
    assert result.estimate == pytest.approx(0.6)
    assert result.cost is None
    assert result.poses is None


def test_dock_run_produces_cost_not_estimate(completed_response):
    """Test that protein.dock() (no quote) produces cost, not estimate.

    Simulates the aggregated result from protein.dock() where each
    ligand gets a Completed response from the API.
    """
    result = FunctionResult([completed_response, completed_response])
    result.poses = ["mock_pose"]

    assert result.cost is not None
    assert result.cost == pytest.approx(0.4)
    assert result.estimate is None
    assert result.poses == ["mock_pose"]
