"""Cost and billing classes for controlling and reporting API operation costs."""

from dataclasses import dataclass
from typing import Self

from beartype import beartype


@dataclass
class Cost:
    """Cost limits for API operations.

    Supports dollar-based limits or free action limits.

    Examples:
        >>> Cost(100)                    # up to $100
        >>> Cost(free_actions=2)          # up to 2 free actions
    """

    max_dollars: float | None = None
    free_actions: int | None = None

    @beartype
    def __init__(
        self,
        max_dollars: float | int | None = None,
        *,
        free_actions: int | None = None,
    ) -> None:
        """Initialize a Cost limit.

        Args:
            max_dollars: Dollar amount limit (positional argument).
            free_actions: Number of free actions allowed (keyword-only argument).
        """
        if max_dollars is not None and free_actions is not None:
            raise ValueError(
                "Cannot specify both max_dollars and free_actions. "
                "Use either Cost(100) or Cost(free_actions=2)."
            )
        if max_dollars is None and free_actions is None:
            raise ValueError(
                "Must specify either max_dollars or free_actions. "
                "Use Cost(100) or Cost(free_actions=2)."
            )

        self.max_dollars = float(max_dollars) if max_dollars is not None else None
        self.free_actions = free_actions

    @property
    def approve_amount(self) -> int | None:
        """Dollar limit as an integer for the API approveAmount field.

        Returns:
            The dollar limit rounded to int, or None if no dollar limit is set.
        """
        if self.max_dollars is not None:
            return int(self.max_dollars)
        return None


@dataclass(kw_only=True)
class Estimate:
    """Cost/pricing information from an API response.

    Wraps the quotationResult returned by the functions API, providing
    convenient access to total price, individual line items, and free actions.
    """

    total_price: float
    items: list[dict]
    raw: dict

    def __post_init__(self) -> None:
        """Convert total_price to float if it's an int."""
        if isinstance(self.total_price, int):
            self.total_price = float(self.total_price)

    @classmethod
    def from_response(cls, response: dict) -> Self:
        """Create an Estimate from a single API response.

        Args:
            response: API response dict containing a quotationResult key.

        Returns:
            An Estimate summarizing the cost information.
        """
        quotation = response.get("quotationResult", {})
        items = quotation.get("successfulQuotations", [])
        total_price = sum(item.get("priceTotal", 0) for item in items)
        return cls(total_price=total_price, items=items, raw=quotation)

    @classmethod
    def from_responses(cls, responses: list[dict]) -> Self:
        """Create an aggregate Estimate from multiple API responses.

        Args:
            responses: List of API response dicts, each containing a quotationResult key.

        Returns:
            An Estimate aggregating cost information across all responses.
        """
        all_items: list[dict] = []
        total_price = 0.0
        raw_quotations: list[dict] = []

        for response in responses:
            quotation = response.get("quotationResult", {})
            items = quotation.get("successfulQuotations", [])
            total_price += sum(item.get("priceTotal", 0) for item in items)
            all_items.extend(items)
            raw_quotations.append(quotation)

        return cls(
            total_price=total_price,
            items=all_items,
            raw={"aggregated": raw_quotations},
        )

    @property
    def free_actions(self) -> int:
        """Count of free actions (items with zero unit price).

        Returns:
            Total quantity of items where priceEach is 0.
        """
        return sum(
            item.get("qty", 0) for item in self.items if item.get("priceEach", 0) == 0
        )

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Estimate(total_price=${self.total_price:.2f}, items={len(self.items)})"

    def __eq__(self, other: object) -> bool:
        """Check equality."""
        if not isinstance(other, Estimate):
            return NotImplemented
        return self.total_price == other.total_price and self.items == other.items
