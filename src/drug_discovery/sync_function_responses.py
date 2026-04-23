"""Wrapper around function API responses for synchronous ``functions.run`` flows."""

from __future__ import annotations

from dataclasses import dataclass, field

from beartype import beartype


@dataclass
@beartype
class SyncFunctionResponses:
    """Wraps one or more raw ``functions.run`` JSON responses.

    Holds a list of responses so batch runs (for example docking many ligands)
    can aggregate costs and estimates. Callers may attach domain-specific
    attributes on the instance (for example ``result.poses = LigandSet(...)``).

    Attributes:
        responses: Raw JSON response dicts from the function API.
    """

    responses: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.responses is None:
            object.__setattr__(self, "responses", [])

    @property
    def response(self) -> dict:
        """The first raw API response (convenience for single-response results)."""
        if not self.responses:
            return {}
        return self.responses[0]

    @property
    def status(self) -> str | None:
        """Execution status from the first response."""
        if not self.responses:
            return None
        return self.responses[0].get("status")

    @property
    def id(self) -> str | None:
        """The execution ID from the first response."""
        if not self.responses:
            return None
        return self.responses[0].get("id")

    @staticmethod
    def _get_price(response: dict) -> float | None:
        """Extract priceTotal from a single response's quotationResult."""
        quotation = response.get("quotationResult", {})
        successful = quotation.get("successfulQuotations", [])
        if successful:
            price = successful[0].get("priceTotal")
            if price is not None:
                return float(price)
        return None

    _ESTIMATE_STATUSES = {"Quoted", "Approved"}

    @property
    def estimate(self) -> float | None:
        """Total cost estimate in dollars when ``quote=True`` was used."""
        if not self.responses:
            return None
        if not all(r.get("status") in self._ESTIMATE_STATUSES for r in self.responses):
            return None
        prices = [self._get_price(r) for r in self.responses]
        if any(p is None for p in prices):
            return None
        return float(sum(prices))

    @property
    def cost(self) -> float | None:
        """Total actual cost in dollars after completed execution."""
        if not self.responses:
            return None
        if not all(r.get("status") == "Completed" for r in self.responses):
            return None
        total = sum(self._get_price(r) or 0 for r in self.responses)
        return total if total > 0 else None

    @property
    def function_outputs(self) -> list[dict]:
        """The ``functionOutputs`` dicts from all responses."""
        return [r.get("functionOutputs", {}) for r in self.responses]

    @property
    def function_key(self) -> str | None:
        """The function key from the first response."""
        if not self.responses:
            return None
        func = self.responses[0].get("function", {})
        return func.get("manifestBody", {}).get("key")

    @property
    def function_version(self) -> str | None:
        """The function version from the first response."""
        if not self.responses:
            return None
        func = self.responses[0].get("function", {})
        return func.get("version")

    def __repr__(self) -> str:
        parts: list[str] = []
        n = len(self.responses)
        if n > 1:
            parts.append(f"n={n}")
        if self.function_key:
            label = f"{self.function_key}"
            if self.function_version:
                label += f"/{self.function_version}"
            parts.append(f"function={label!r}")
        if self.status:
            parts.append(f"status={self.status!r}")
        if self.estimate is not None:
            parts.append(f"estimate=${self.estimate:.2f}")
        if self.cost is not None:
            parts.append(f"cost=${self.cost:.2f}")
        return f"SyncFunctionResponses({', '.join(parts)})"
