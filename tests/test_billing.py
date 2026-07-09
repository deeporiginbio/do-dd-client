"""Tests for the billing API wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


def test_get_usage_by_tag_returns_mock_usage(client: DeepOriginClient) -> None:
    """get_usage_by_tag returns billing usage from the mock server."""
    result = client.billing.get_usage_by_tag(
        tag="project-alpha",
        start_date="2024-01-01",
    )

    assert result["status"] == "OK"
    assert isinstance(result.get("items"), list)
    assert len(result["items"]) >= 1
    assert result["items"][0]["billing_tag"] == "project-alpha"


def test_get_usage_by_tag_explicit_end_date(client: DeepOriginClient) -> None:
    """get_usage_by_tag accepts an explicit end_date and returns usage rows."""
    result = client.billing.get_usage_by_tag(
        tag="tag-1",
        start_date="2024-01-01",
        end_date="2024-06-30",
    )

    assert result["status"] == "OK"
    assert all(item["billing_tag"] == "tag-1" for item in result["items"])
