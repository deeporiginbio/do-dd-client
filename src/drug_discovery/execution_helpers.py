"""Shared helpers for tools-service execution DTOs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from beartype import beartype
import humanize
import pandas as pd

from deeporigin.utils.constants import TOOL_KEY_PREFIX
from deeporigin.utils.iso8601 import parse_iso_timestamp_utc

USER_LOG_COLUMNS: list[str] = ["log_level", "tool_key", "timestamp", "message"]


def _strip_tool_key_prefix(tool_key: str | None) -> str | None:
    """Return ``tool_key`` without the platform ``deeporigin.`` prefix."""
    if tool_key is None:
        return None
    return tool_key.removeprefix(TOOL_KEY_PREFIX)


def _format_user_log_timestamp(
    raw: str | None,
    *,
    when: datetime | None = None,
) -> str | None:
    """Format an ISO log timestamp as a compact, human-readable relative time."""
    if raw is None:
        return None
    try:
        dt = parse_iso_timestamp_utc(raw)
    except (ValueError, TypeError):
        return raw
    ref = when or datetime.now(timezone.utc)
    return humanize.naturaltime(dt, when=ref)


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


@beartype
def user_logs_dataframe(response: dict[str, Any]) -> pd.DataFrame:
    """Build a tabular view from a data-platform ``user_logs`` search response.

    Args:
        response: Raw response from :meth:`~deeporigin.platform.user_logs.UserLogs.search`,
            typically containing a ``data`` list of log row dicts.

    Returns:
        A DataFrame with columns ``log_level``, ``tool_key``, ``timestamp``, and
        ``message``. ``tool_key`` values omit the ``deeporigin.`` prefix.
        ``timestamp`` values are humanized relative times (via ``humanize``).
        Returns an empty frame with those columns when there are no rows.
    """
    records = response.get("data") or []
    rows: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        rows.append(
            {
                "log_level": record.get("log_level"),
                "tool_key": _strip_tool_key_prefix(record.get("tool_key")),
                "timestamp": _format_user_log_timestamp(
                    record.get("date") or record.get("created_at")
                ),
                "message": record.get("message"),
            }
        )
    if not rows:
        return pd.DataFrame(columns=USER_LOG_COLUMNS)
    return pd.DataFrame(rows)[USER_LOG_COLUMNS]
