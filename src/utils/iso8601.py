"""ISO-8601 timestamp parsing helpers for API payloads."""

from __future__ import annotations

from datetime import datetime, timezone

from beartype import beartype


@beartype
def parse_iso_timestamp_utc(value: str) -> datetime:
    """Parse an ISO-8601 timestamp string to an aware UTC :class:`~datetime.datetime`.

    Accepts API-style values ending in ``Z`` (normalized to ``+00:00`` for
    :func:`datetime.fromisoformat`) and offset-aware strings. Naive strings are
    interpreted as UTC.

    Args:
        value: ISO-8601 timestamp (e.g. tools API ``startedAt`` / ``completedAt``).

    Returns:
        The same instant in UTC (``tzinfo`` is :attr:`datetime.timezone.utc`).
    """
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
