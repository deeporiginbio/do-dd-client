"""Entities-related routes for the mock server."""

from __future__ import annotations

from typing import Any
import uuid

from fastapi import APIRouter


def _make_org(*, org_key: str, name: str) -> dict[str, Any]:
    """Build a mock organization record.

    Args:
        org_key: The organization key slug.
        name: Human-readable organization name.

    Returns:
        Dictionary matching the platform organization schema.
    """
    return {
        "createdAt": "2024-03-05T00:00:00.000Z",
        "updatedAt": "2024-08-01T19:01:49.614Z",
        "orgKey": org_key,
        "name": name,
        "mfaEnabled": False,
        "threshold": "50.00",
        "autoApproveMaxAmount": 500,
        "status": "READY",
        "id": str(uuid.uuid4()),
        "invites": [],
        "roles": ["Owner"],
    }


def _make_user(*, email: str) -> dict[str, Any]:
    """Build a mock organization user record.

    Args:
        email: Email address (also used for first/last name placeholders).

    Returns:
        Dictionary matching the platform user schema.
    """
    return {
        "id": str(uuid.uuid4()),
        "authId": f"google-apps|{email}",
        "createdAt": "2024-07-31T07:05:17.367Z",
        "updatedAt": "2024-07-31T07:05:20.452Z",
        "firstName": email,
        "lastName": email,
        "email": email,
        "company": None,
        "title": "",
        "mfaEnabled": False,
        "roles": ["Member"],
    }


def create_entities_router() -> APIRouter:
    """Create a router for entities-related endpoints.

    Returns:
        APIRouter instance with entities routes.
    """
    router = APIRouter()

    @router.get("/entities/protected/organizations")
    def list_organizations() -> dict[str, Any]:
        """List all organizations accessible to the authenticated user."""
        return {
            "data": [
                _make_org(org_key="deeporigin-com", name="Deep Origin"),
                _make_org(
                    org_key="deeporigin-platform",
                    name="Deep Origin - Platform Team",
                ),
            ]
        }

    @router.get("/entities/{org_key}/organizations/users")
    def list_organization_users(org_key: str) -> dict[str, Any]:
        """List organization users."""
        return {
            "data": [
                _make_user(email="user1@example.com"),
                _make_user(email="user2@example.com"),
            ]
        }

    return router
