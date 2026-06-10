"""Organizations API wrapper for DeepOriginClient."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


class Organizations:
    """Organizations API wrapper.

    Provides access to organizations-related endpoints through the DeepOriginClient.
    """

    def __init__(self, client: DeepOriginClient) -> None:
        """Initialize Organizations wrapper.

        Args:
            client: The DeepOriginClient instance to use for API calls.
        """
        self._c = client

    def list(self) -> list[dict]:
        """List all organizations accessible to the authenticated user.

        Returns:
            List of organization dictionaries, each containing fields like id,
            orgKey, name, mfaEnabled, threshold, autoApproveMaxAmount, status,
            createdAt, updatedAt, invites, roles, etc.
        """
        # we're moving to a response envelope pattern, so need to handle both cases

        response = self._c.get_json("/entities/protected/organizations")
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        else:
            return []

    def users(self) -> list[dict]:
        """List all users associated with the organization.


        Returns:
            List of user dictionaries, each containing fields like id, authId,
            email, firstName, lastName, company, title, mfaEnabled, roles,
            createdAt, updatedAt, etc.
        """

        response = self._c.get_json(f"/entities/{self._c.org_key}/organizations/users")

        # we're moving to a response envelope pattern, so need to handle both cases

        if isinstance(response, dict) and "data" in response:
            return response["data"]
        else:
            return []
