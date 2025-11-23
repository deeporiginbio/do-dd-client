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
        return self._c.get_json("/entities/protected/organizations")

    def users(
        self,
        *,
        page: int | None = None,
        page_size: int | None = None,
        order: str | None = None,
        filter: str | None = None,
    ) -> list[dict]:
        """List all users associated with the organization.

        Args:
            page: Page number of the pagination (default 0).
            page_size: Page size of the pagination (max 10,000).
            order: Order of the pagination.
            filter: Filter applied to the data set.

        Returns:
            List of user dictionaries, each containing fields like id, email,
            firstName, lastName, authId, avatar, createdAt, updatedAt, etc.
        """
        params: dict[str, int | str] = {}
        if page is not None:
            params["page"] = page
        if page_size is not None:
            params["pageSize"] = page_size
        if order is not None:
            params["order"] = order
        if filter is not None:
            params["filter"] = filter

        return self._c.get_json(
            f"/entities/{self._c.org_key}/organizations/users",
            params=params if params else None,
        )
