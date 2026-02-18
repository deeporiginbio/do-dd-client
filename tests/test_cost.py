"""Tests for Cost, Estimate, and Result classes."""

import pytest

from deeporigin.utils.cost import Cost, Estimate
from deeporigin.utils.result import Result


class TestCost:
    """Tests for the Cost class."""

    def test_dollar_limit(self):
        """Cost initialized with a number sets max_dollars."""
        cost = Cost(100)
        assert cost.max_dollars == 100.0
        assert cost.max_actions is None

    def test_dollar_limit_float(self):
        """Cost accepts float dollar amounts."""
        cost = Cost(49.99)
        assert cost.max_dollars == 49.99
        assert cost.max_actions is None

    def test_action_limit(self):
        """Cost initialized with a dict sets max_actions."""
        cost = Cost({"DO_DOCK": 5})
        assert cost.max_dollars is None
        assert cost.max_actions == {"DO_DOCK": 5}

    def test_mixed_limit(self):
        """Cost initialized with both dollar and action limits."""
        cost = Cost(100, {"DO_DOCK": 1})
        assert cost.max_dollars == 100.0
        assert cost.max_actions == {"DO_DOCK": 1}

    def test_approve_amount_from_dollars(self):
        """approve_amount returns int version of max_dollars."""
        cost = Cost(100)
        assert cost.approve_amount == 100

    def test_approve_amount_none_for_actions_only(self):
        """approve_amount is None when only action limits are set."""
        cost = Cost({"DO_DOCK": 5})
        assert cost.approve_amount is None

    def test_approve_amount_from_mixed(self):
        """approve_amount uses the dollar portion of mixed limits."""
        cost = Cost(100, {"DO_DOCK": 1})
        assert cost.approve_amount == 100

    def test_repr_dollars(self):
        """Repr includes dollar amount."""
        cost = Cost(100)
        assert "$100.00" in repr(cost)

    def test_repr_actions(self):
        """Repr includes action limits."""
        cost = Cost({"DO_DOCK": 5})
        assert "DO_DOCK" in repr(cost)

    def test_repr_mixed(self):
        """Repr includes both dollar and action limits."""
        cost = Cost(100, {"DO_DOCK": 1})
        r = repr(cost)
        assert "$100.00" in r
        assert "DO_DOCK" in r

    def test_equality(self):
        """Two Costs with the same limits are equal."""
        assert Cost(100) == Cost(100)
        assert Cost({"DO_DOCK": 5}) == Cost({"DO_DOCK": 5})
        assert Cost(100, {"DO_DOCK": 1}) == Cost(100, {"DO_DOCK": 1})

    def test_inequality(self):
        """Different Costs are not equal."""
        assert Cost(100) != Cost(200)
        assert Cost(100) != Cost({"DO_DOCK": 5})

    def test_invalid_type_raises(self):
        """Cost raises for unsupported types."""
        from beartype.roar import BeartypeCallHintParamViolation

        with pytest.raises(BeartypeCallHintParamViolation):
            Cost("invalid")  # type: ignore[arg-type]


class TestEstimate:
    """Tests for the Estimate class."""

    def test_from_response_with_quotation(self):
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
        assert estimate.total_price == 1.50
        assert len(estimate.items) == 1
        assert estimate.items[0]["itemCode"] == "DO_DOCK"

    def test_from_response_empty(self):
        """Estimate handles a response with no quotationResult."""
        estimate = Estimate.from_response({})
        assert estimate.total_price == 0.0
        assert estimate.items == []

    def test_from_responses_aggregates(self):
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
        assert estimate.total_price == 3.0
        assert len(estimate.items) == 2

    def test_from_responses_empty_list(self):
        """Estimate handles an empty list of responses."""
        estimate = Estimate.from_responses([])
        assert estimate.total_price == 0.0
        assert estimate.items == []

    def test_free_actions(self):
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

    def test_free_actions_none(self):
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

    def test_repr(self):
        """Repr shows total price and item count."""
        estimate = Estimate(total_price=1.50, items=[{"a": 1}], raw={})
        assert "$1.50" in repr(estimate)
        assert "1" in repr(estimate)

    def test_equality(self):
        """Estimates with the same price and items are equal."""
        items = [{"itemCode": "DO_DOCK", "priceTotal": 1.0}]
        assert Estimate(total_price=1.0, items=items, raw={}) == Estimate(
            total_price=1.0, items=items, raw={}
        )


class TestResult:
    """Tests for the Result class."""

    def test_quote_result_has_no_data(self):
        """A quote result should have data=None and an estimate."""
        estimate = Estimate(total_price=1.5, items=[], raw={})
        result = Result(data=None, estimate=estimate)
        assert result.data is None
        assert result.estimate is not None
        assert result.estimate.total_price == 1.5
        assert result.cost is None

    def test_run_result_has_data_and_cost(self):
        """A completed run result should have data and cost."""
        data = {"some": "output"}
        cost = Estimate(total_price=1.5, items=[], raw={})
        result = Result(data=data, cost=cost)
        assert result.data is data
        assert result.cost is not None
        assert result.cost.total_price == 1.5
        assert result.estimate is None

    def test_default_all_none(self):
        """Default Result has all fields as None."""
        result = Result()
        assert result.data is None
        assert result.estimate is None
        assert result.cost is None
