"""Cost and billing classes for controlling and reporting API operation costs."""

from beartype import beartype


class Cost:
    """Cost limits for API operations.

    Supports dollar-based limits, action-based limits, or both.

    Examples:
        >>> Cost(100)                        # up to $100
        >>> Cost({"DO_DOCK": 5})             # up to 5 docking actions
        >>> Cost(100, {"DO_DOCK": 1})        # 1 docking action and $100
    """

    max_dollars: float | None
    max_actions: dict[str, int] | None

    @beartype
    def __init__(
        self,
        dollars_or_actions: float | int | dict[str, int],
        actions: dict[str, int] | None = None,
    ) -> None:
        """Initialize a Cost limit.

        Args:
            dollars_or_actions: Either a dollar amount (int/float) or a dict
                mapping action codes to their max counts.
            actions: Optional dict mapping action codes to max counts.
                Only used when the first argument is a dollar amount.
        """
        if isinstance(dollars_or_actions, dict):
            self.max_dollars = None
            self.max_actions = dollars_or_actions
        elif isinstance(dollars_or_actions, (int, float)):
            self.max_dollars = float(dollars_or_actions)
            self.max_actions = actions
        else:
            raise TypeError(
                f"Expected int, float, or dict, got {type(dollars_or_actions)}"
            )

    @property
    def approve_amount(self) -> int | None:
        """Dollar limit as an integer for the API approveAmount field.

        Returns:
            The dollar limit rounded to int, or None if no dollar limit is set.
        """
        if self.max_dollars is not None:
            return int(self.max_dollars)
        return None

    def __repr__(self) -> str:
        """Return string representation."""
        parts = []
        if self.max_dollars is not None:
            parts.append(f"${self.max_dollars:.2f}")
        if self.max_actions is not None:
            parts.append(f"actions={self.max_actions}")
        return f"Cost({', '.join(parts)})"

    def __eq__(self, other: object) -> bool:
        """Check equality."""
        if not isinstance(other, Cost):
            return NotImplemented
        return (
            self.max_dollars == other.max_dollars
            and self.max_actions == other.max_actions
        )


class Estimate:
    """Cost/pricing information from an API response.

    Wraps the quotationResult returned by the functions API, providing
    convenient access to total price, individual line items, and free actions.
    """

    total_price: float
    items: list[dict]
    raw: dict

    @beartype
    def __init__(
        self, *, total_price: int | float, items: list[dict], raw: dict
    ) -> None:
        """Initialize an Estimate.

        Args:
            total_price: Total price across all items.
            items: List of individual quotation item dicts from the API.
            raw: Raw quotationResult dict(s) from the API response.
        """
        self.total_price = total_price
        self.items = items
        self.raw = raw

    @classmethod
    def from_response(cls, response: dict) -> "Estimate":
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
    def from_responses(cls, responses: list[dict]) -> "Estimate":
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
