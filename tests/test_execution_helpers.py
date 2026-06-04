"""Tests for ``deeporigin.drug_discovery.execution_helpers``."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

from deeporigin.drug_discovery.execution_helpers import (
    USER_LOG_COLUMNS,
    _format_user_log_timestamp,
    _strip_tool_key_prefix,
    price_total_from_execution_dto,
    user_logs_dataframe,
)


def test_price_total_from_execution_dto_missing() -> None:
    """Returns None when there is no successful quotation."""
    assert price_total_from_execution_dto({}) is None
    assert price_total_from_execution_dto({"quotationResult": {}}) is None


def test_price_total_from_execution_dto_present() -> None:
    """Parses priceTotal from the first successful quotation row."""
    dto = {
        "quotationResult": {
            "successfulQuotations": [{"priceTotal": 1.5}],
        }
    }
    assert price_total_from_execution_dto(dto) == 1.5


def test_strip_tool_key_prefix() -> None:
    """Strips the platform prefix from tool keys."""
    assert _strip_tool_key_prefix("deeporigin.rbfe") == "rbfe"
    assert _strip_tool_key_prefix("rbfe") == "rbfe"
    assert _strip_tool_key_prefix(None) is None


def test_format_user_log_timestamp_humanizes() -> None:
    """Formats ISO timestamps as compact relative times."""
    when = datetime(2026, 6, 4, 16, 35, 0, tzinfo=timezone.utc)
    assert (
        _format_user_log_timestamp("2026-06-04T16:18:53.034Z", when=when)
        == "16 minutes ago"
    )


def test_user_logs_dataframe_maps_rows() -> None:
    """Maps user_logs search rows to the expected column set."""
    when = datetime(2026, 6, 4, 16, 35, 0, tzinfo=timezone.utc)
    response = {
        "data": [
            {
                "log_level": "info",
                "tool_key": "deeporigin.rbfe",
                "date": "2026-06-04T16:18:53.034Z",
                "message": "CPU cpuset check passed.",
            },
            {
                "log_level": "info",
                "tool_key": "deeporigin.rbfe",
                "created_at": "2026-06-04T16:34:58.708Z",
                "message": "Finalize: reporting results.",
            },
        ]
    }
    with patch("deeporigin.drug_discovery.execution_helpers.datetime") as mock_datetime:
        mock_datetime.now.return_value = when
        df = user_logs_dataframe(response)

    assert list(df.columns) == USER_LOG_COLUMNS
    assert len(df) == 2
    assert df.iloc[0]["tool_key"] == "rbfe"
    assert df.iloc[1]["tool_key"] == "rbfe"
    assert df.iloc[0]["timestamp"] == "16 minutes ago"
    assert df.iloc[1]["timestamp"] == "a second ago"


def test_user_logs_dataframe_empty() -> None:
    """Returns an empty frame with the expected columns when there are no rows."""
    df = user_logs_dataframe({"data": []})
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == USER_LOG_COLUMNS
    assert df.empty
