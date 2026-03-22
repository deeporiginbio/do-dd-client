"""Data Platform projects API wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deeporigin_sdk.platform.client import DeepOriginClient


class Projects:
    """Projects API wrapper.

    Provides access to project-related endpoints through the DeepOriginClient.
    """

    def __init__(self, client: DeepOriginClient) -> None:
        """Initialize Projects wrapper.

        Args:
            client: The DeepOriginClient instance to use for API calls.
        """
        self._c = client

    def list(self) -> dict:
        """List projects.

        Returns:
            Dictionary containing the list of projects.
        """
        return self._c.post_json(
            f"/data-platform/{self._c.org_key}/projects/search",
            body={},
        )
