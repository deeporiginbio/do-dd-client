"""Tests for :mod:`deeporigin.utils.iso8601`."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from deeporigin.utils.iso8601 import parse_iso_timestamp_utc


def test_parse_iso_timestamp_utc_z_suffix() -> None:
    """``Z`` suffix is parsed as UTC."""
    dt = parse_iso_timestamp_utc("2025-04-16T18:03:16.154Z")
    assert dt.tzinfo == timezone.utc
    assert dt.year == 2025 and dt.month == 4 and dt.day == 16
    assert dt.hour == 18 and dt.minute == 3 and dt.second == 16
    assert dt.microsecond == 154000


def test_parse_iso_timestamp_utc_explicit_offset() -> None:
    """Offset strings are converted to UTC."""
    dt = parse_iso_timestamp_utc("2025-01-01T12:00:00-05:00")
    assert dt == datetime(2025, 1, 1, 17, 0, 0, tzinfo=timezone.utc)


def test_parse_iso_timestamp_utc_naive_treated_as_utc() -> None:
    """Naive ISO strings are interpreted as UTC wall time."""
    dt = parse_iso_timestamp_utc("2025-01-01T12:00:00")
    assert dt == datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("value", "expected_utc"),
    [
        (
            "2025-06-01T00:00:00.000001Z",
            datetime(2025, 6, 1, 0, 0, 0, 1, tzinfo=timezone.utc),
        ),
        (
            "2025-06-01T00:00:00+00:00",
            datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc),
        ),
    ],
)
def test_parse_iso_timestamp_utc_parametrized(
    value: str, expected_utc: datetime
) -> None:
    """Microseconds and ``+00:00`` normalize consistently."""
    assert parse_iso_timestamp_utc(value) == expected_utc
