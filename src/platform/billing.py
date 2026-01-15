"""Billing API wrapper for DeepOriginClient."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


class Billing:
    """Billing API wrapper.

    Provides access to billing-related endpoints through the DeepOriginClient.
    """

    def __init__(self, client: DeepOriginClient) -> None:
        """Initialize Billing wrapper.

        Args:
            client: The DeepOriginClient instance to use for API calls.
        """
        self._c = client

    def get_usage_by_tag(
        self,
        *,
        tag: str,
        start_date: str = "2020-01-01",
        end_date: str | None = None,
    ) -> dict:
        """Get usage information for a billing tag within a date range.

        Args:
            tag: The billing tag to get usage for.
            start_date: Start date in YYYY-MM-DD format. Defaults to "2020-01-01".
            end_date: End date in YYYY-MM-DD format. Defaults to today's date.

        Returns:
            Dictionary containing usage information with the following structure:
            - status: Status of the response (e.g., "OK")
            - org_id: Organization ID
            - items: List of usage items, each containing:
              - entry_dt: Entry date/time
              - item_code: Item code (e.g., "DO_HELLO_WORLD")
              - description: Description of the item
              - qty: Quantity
              - unit_cost: Unit cost
              - total_cost: Total cost
              - notes: Additional notes
              - billing_tag_transaction: Billing tag transaction ID
              - billing_tag: Billing tag
        """
        if end_date is None:
            end_date = date.today().strftime("%Y-%m-%d")

        params = {
            "startDate": start_date,
            "endDate": end_date,
        }

        response = self._c.get_json(
            f"/billing/{self._c.org_key}/usage/{tag}",
            params=params,
        )

        return response
