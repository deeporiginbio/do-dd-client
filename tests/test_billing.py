"""Tests for the billing API wrapper."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from deeporigin.platform.billing import Billing


def test_get_usage_by_tag_builds_request() -> None:
    """get_usage_by_tag calls the billing usage endpoint with date params."""
    client = MagicMock()
    client.org_key = "my-org"
    client.get_json.return_value = {"usage": 42}
    billing = Billing(client)

    result = billing.get_usage_by_tag(tag="project-alpha", start_date="2024-01-01")

    assert result == {"usage": 42}
    client.get_json.assert_called_once_with(
        "/billing/my-org/usage/project-alpha",
        params={
            "startDate": "2024-01-01",
            "endDate": date.today().strftime("%Y-%m-%d"),
        },
    )


def test_get_usage_by_tag_explicit_end_date() -> None:
    """get_usage_by_tag forwards an explicit end_date parameter."""
    client = MagicMock()
    client.org_key = "org-1"
    client.get_json.return_value = {}
    billing = Billing(client)

    billing.get_usage_by_tag(
        tag="tag-1",
        start_date="2024-01-01",
        end_date="2024-06-30",
    )

    client.get_json.assert_called_once_with(
        "/billing/org-1/usage/tag-1",
        params={"startDate": "2024-01-01", "endDate": "2024-06-30"},
    )
