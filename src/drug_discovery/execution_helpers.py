"""Shared helpers for tools-service execution DTOs."""

from __future__ import annotations

from typing import Any


def price_total_from_execution_dto(dto: dict[str, Any]) -> float | None:
    """Return ``priceTotal`` from the first successful quotation in an execution DTO.

    Args:
        dto: Raw execution dictionary from ``executions.create`` or ``get``.

    Returns:
        The total price, or ``None`` if no successful quotation row exists.
    """
    quotation = dto.get("quotationResult") or {}
    successful = quotation.get("successfulQuotations") or []
    if not successful:
        return None
    price = successful[0].get("priceTotal")
    return float(price) if price is not None else None
