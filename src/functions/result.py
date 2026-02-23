"""Lean wrapper around function API responses.

The FunctionResult class wraps one or more raw JSON responses from the
Deep Origin function execution API, providing convenient access to status,
cost estimates, and domain-specific attributes (like docking poses).
"""

from dataclasses import dataclass

from beartype import beartype


@dataclass
@beartype
class FunctionResult:
    """Wraps function API responses with convenient accessors.

    Holds a list of responses so that batch runs (e.g. docking many ligands)
    can aggregate costs and estimates naturally. Callers can attach
    domain-specific attributes directly on the instance
    (e.g. ``result.poses = LigandSet(...)``).

    Attributes:
        _responses: List of raw JSON response dicts from the function API.
    """

    _responses: list[dict]

    @property
    def response(self) -> dict:
        """The first raw API response (convenience for single-response results)."""
        return self._responses[0]

    @property
    def responses(self) -> list[dict]:
        """All raw API response dictionaries."""
        return self._responses

    @property
    def status(self) -> str | None:
        """Execution status from the first response."""
        if not self._responses:
            return None
        return self._responses[0].get("status")

    @property
    def id(self) -> str | None:
        """The execution ID from the first response."""
        if not self._responses:
            return None
        return self._responses[0].get("id")

    @staticmethod
    def _get_price(response: dict) -> float | None:
        """Extract priceTotal from a single response's quotationResult.

        Args:
            response: A single API response dict.

        Returns:
            The price as a float, or None if unavailable.
        """
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
        """Total cost estimate in dollars (set when ``quote=True`` was used)."""
        if not self._responses:
            return None
        if not all(
            r.get("status") in self._ESTIMATE_STATUSES for r in self._responses
        ):
            return None
        total = sum(self._get_price(r) or 0 for r in self._responses)
        return total if total > 0 else None

    @property
    def cost(self) -> float | None:
        """Total actual cost in dollars (set when the function was executed)."""
        if not self._responses:
            return None
        if not all(r.get("status") == "Completed" for r in self._responses):
            return None
        total = sum(self._get_price(r) or 0 for r in self._responses)
        return total if total > 0 else None

    @property
    def function_outputs(self) -> list[dict]:
        """The ``functionOutputs`` dicts from all responses."""
        return [r.get("functionOutputs", {}) for r in self._responses]

    @property
    def function_key(self) -> str | None:
        """The function key (e.g. ``'deeporigin.docking'``) from the first response."""
        if not self._responses:
            return None
        func = self._responses[0].get("function", {})
        return func.get("manifestBody", {}).get("key")

    @property
    def function_version(self) -> str | None:
        """The function version from the first response."""
        if not self._responses:
            return None
        func = self._responses[0].get("function", {})
        return func.get("version")

    def __repr__(self) -> str:
        """Return a concise string representation."""
        parts: list[str] = []
        n = len(self._responses)
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
        return f"FunctionResult({', '.join(parts)})"
