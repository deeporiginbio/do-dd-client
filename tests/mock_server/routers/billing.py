"""Billing-related routes for the mock server."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def create_billing_router() -> APIRouter:
    """Create a router for billing-related endpoints.

    Returns:
        APIRouter instance with billing routes.
    """
    router = APIRouter()

    @router.get("/billing/health")
    def billing_health() -> dict[str, str]:
        """Health check for the billing service."""
        return {"status": "ok"}

    @router.get("/billing/{org_key}/usage/{billing_tag}")
    def get_billing_usage(
        org_key: str,
        billing_tag: str,
        startDate: str,
        endDate: str,
    ) -> dict[str, Any]:
        """Get billing usage for a billing tag."""
        return {
            "status": "OK",
            "org_id": "ee3c9030-18cd-4373-98c9-fd9e48d4f7fd",
            "items": [
                {
                    "entry_dt": "2026-01-15T01:02:41.551+00:00",
                    "item_code": "DO_HELLO_WORLD",
                    "description": "Hello world function",
                    "qty": 1,
                    "unit_cost": 0,
                    "total_cost": 0,
                    "notes": "",
                    "billing_tag_transaction": f"{billing_tag}:e4ebaafb-e35f-4fd8-9813-716c78a3949c",
                    "billing_tag": billing_tag,
                },
                {
                    "entry_dt": "2026-01-15T01:05:12.755+00:00",
                    "item_code": "DO_HELLO_WORLD",
                    "description": "Hello world function",
                    "qty": 1,
                    "unit_cost": 0,
                    "total_cost": 0,
                    "notes": "",
                    "billing_tag_transaction": f"{billing_tag}:f03cfb94-139c-42f0-911f-33fb105650ea",
                    "billing_tag": billing_tag,
                },
            ],
        }

    return router
