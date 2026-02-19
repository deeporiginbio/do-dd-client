"""Tests for Cost, Estimate, and Result classes."""

import pytest

from deeporigin.utils.cost import Cost, Estimate
from deeporigin.utils.result import Result


def test_cost_dollar_limit():
    """Cost initialized with a number sets max_dollars."""
    cost = Cost(100)
    assert cost.max_dollars == pytest.approx(100.0)
    assert cost.free_actions is None


def test_cost_dollar_limit_float():
    """Cost accepts float dollar amounts."""
    cost = Cost(49.99)
    assert cost.max_dollars == pytest.approx(49.99)
    assert cost.free_actions is None


def test_cost_free_actions_limit():
    """Cost initialized with free_actions keyword sets free_actions."""
    cost = Cost(free_actions=2)
    assert cost.max_dollars is None
    assert cost.free_actions == 2


def test_cost_approve_amount_from_dollars():
    """approve_amount returns int version of max_dollars."""
    cost = Cost(100)
    assert cost.approve_amount == 100


def test_cost_approve_amount_none_for_free_actions_only():
    """approve_amount is None when only free_actions is set."""
    cost = Cost(free_actions=2)
    assert cost.approve_amount is None


def test_cost_repr_dollars():
    """Repr includes dollar amount."""
    cost = Cost(100)
    assert "100" in repr(cost)


def test_cost_repr_free_actions():
    """Repr includes free_actions."""
    cost = Cost(free_actions=2)
    assert "2" in repr(cost)


def test_cost_equality():
    """Two Costs with the same limits are equal."""
    assert Cost(100) == Cost(100)
    assert Cost(free_actions=2) == Cost(free_actions=2)


def test_cost_inequality():
    """Different Costs are not equal."""
    assert Cost(100) != Cost(200)
    assert Cost(100) != Cost(free_actions=2)


def test_cost_both_arguments_raises():
    """Cost raises when both max_dollars and free_actions are specified."""
    with pytest.raises(ValueError, match="Cannot specify both"):
        Cost(100, free_actions=2)


def test_cost_no_arguments_raises():
    """Cost raises when neither argument is specified."""
    with pytest.raises(ValueError, match="Must specify either"):
        Cost()


def test_cost_invalid_type_raises():
    """Cost raises for unsupported types."""
    from beartype.roar import BeartypeCallHintParamViolation

    with pytest.raises(BeartypeCallHintParamViolation):
        Cost("invalid")  # type: ignore[arg-type]


def test_cost_per_ligand_dollars():
    """per_ligand divides dollar budget evenly across ligands."""
    cost = Cost(100)
    per_ligand = cost.per_ligand(4)
    assert per_ligand.max_dollars == pytest.approx(25.0)
    assert per_ligand.free_actions is None


def test_cost_per_ligand_dollars_single():
    """per_ligand with 1 ligand returns the same dollar amount."""
    cost = Cost(100)
    per_ligand = cost.per_ligand(1)
    assert per_ligand.max_dollars == pytest.approx(100.0)


def test_cost_per_ligand_free_actions():
    """per_ligand with free_actions allocates 1 free action per ligand."""
    cost = Cost(free_actions=5)
    per_ligand = cost.per_ligand(3)
    assert per_ligand.free_actions == 1
    assert per_ligand.max_dollars is None


def test_cost_per_ligand_free_actions_exceeds():
    """per_ligand raises when ligands exceed free_actions."""
    cost = Cost(free_actions=2)
    with pytest.raises(ValueError, match="Cannot dock 5 ligands"):
        cost.per_ligand(5)


def test_cost_per_ligand_zero_raises():
    """per_ligand raises for zero ligands."""
    cost = Cost(100)
    with pytest.raises(ValueError, match="num_ligands must be at least 1"):
        cost.per_ligand(0)


def test_estimate_from_response_with_quotation():
    """Estimate extracts total price from a quotationResult response."""
    response = {
        "quotationResult": {
            "anyFailed": False,
            "successfulQuotations": [
                {
                    "itemCode": "DO_DOCK",
                    "priceTotal": 1.50,
                    "priceEach": 0.50,
                    "qty": 3,
                    "status": "OK",
                }
            ],
        }
    }
    estimate = Estimate.from_response(response)
    assert estimate.total_price == pytest.approx(1.50)
    assert len(estimate.items) == 1
    assert estimate.items[0]["itemCode"] == "DO_DOCK"


def test_estimate_from_response_empty():
    """Estimate handles a response with no quotationResult."""
    estimate = Estimate.from_response({})
    assert estimate.total_price == pytest.approx(0.0)
    assert estimate.items == []


def test_estimate_from_responses_aggregates():
    """Estimate aggregates multiple responses."""
    responses = [
        {
            "quotationResult": {
                "successfulQuotations": [
                    {
                        "itemCode": "DO_DOCK",
                        "priceTotal": 1.0,
                        "priceEach": 1.0,
                        "qty": 1,
                    }
                ]
            }
        },
        {
            "quotationResult": {
                "successfulQuotations": [
                    {
                        "itemCode": "DO_DOCK",
                        "priceTotal": 2.0,
                        "priceEach": 1.0,
                        "qty": 2,
                    }
                ]
            }
        },
    ]
    estimate = Estimate.from_responses(responses)
    assert estimate.total_price == pytest.approx(3.0)
    assert len(estimate.items) == 2


def test_estimate_from_responses_empty_list():
    """Estimate handles an empty list of responses."""
    estimate = Estimate.from_responses([])
    assert estimate.total_price == pytest.approx(0.0)
    assert estimate.items == []


def test_estimate_free_actions():
    """free_actions counts items with zero unit price."""
    response = {
        "quotationResult": {
            "successfulQuotations": [
                {
                    "itemCode": "DO_DOCK",
                    "priceTotal": 0.0,
                    "priceEach": 0,
                    "qty": 3,
                },
                {
                    "itemCode": "DO_PREP",
                    "priceTotal": 2.0,
                    "priceEach": 1.0,
                    "qty": 2,
                },
            ]
        }
    }
    estimate = Estimate.from_response(response)
    assert estimate.free_actions == 3


def test_estimate_free_actions_none():
    """free_actions returns 0 when no free items exist."""
    response = {
        "quotationResult": {
            "successfulQuotations": [
                {
                    "itemCode": "DO_DOCK",
                    "priceTotal": 1.5,
                    "priceEach": 0.5,
                    "qty": 3,
                },
            ]
        }
    }
    estimate = Estimate.from_response(response)
    assert estimate.free_actions == 0


def test_estimate_repr():
    """Repr shows total price and item count."""
    estimate = Estimate(total_price=1.50, items=[{"a": 1}], raw={})
    assert "$1.50" in repr(estimate)
    assert "1" in repr(estimate)


def test_estimate_equality():
    """Estimates with the same price and items are equal."""
    items = [{"itemCode": "DO_DOCK", "priceTotal": 1.0}]
    assert Estimate(total_price=1.0, items=items, raw={}) == Estimate(
        total_price=1.0, items=items, raw={}
    )


def test_result_quote_result_has_no_data():
    """A quote result should have data=None and an estimate."""
    estimate = Estimate(total_price=1.5, items=[], raw={})
    result = Result(data=None, estimate=estimate)
    assert result.data is None
    assert result.estimate is not None
    assert result.estimate.total_price == pytest.approx(1.5)
    assert result.cost is None


def test_result_run_result_has_data_and_cost():
    """A completed run result should have data and cost."""
    data = {"some": "output"}
    cost = Estimate(total_price=1.5, items=[], raw={})
    result = Result(data=data, cost=cost)
    assert result.data is data
    assert result.cost is not None
    assert result.cost.total_price == pytest.approx(1.5)
    assert result.estimate is None


def test_result_default_all_none():
    """Default Result has all fields as None."""
    result = Result()
    assert result.data is None
    assert result.estimate is None
    assert result.cost is None
