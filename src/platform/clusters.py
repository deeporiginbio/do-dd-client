"""Clusters API wrapper for DeepOriginClient."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


class Clusters:
    """Clusters API wrapper.

    Provides access to clusters-related endpoints through the DeepOriginClient.
    """

    def __init__(self, client: DeepOriginClient) -> None:
        """Initialize Clusters wrapper.

        Args:
            client: The DeepOriginClient instance to use for API calls.
        """
        self._c = client

    def list(
        self,
        *,
        page: int | None = None,
        page_size: int | None = None,
        order: str | None = None,
        filter: str | None = None,
    ) -> dict:
        """List all clusters associated with the organization.

        Args:
            page: Page number of the pagination (default 0).
            page_size: Page size of the pagination (max 10,000).
            order: Order of the pagination, can be any of the following:
                hostname? asc | desc, name? asc | desc, orgKey? asc | desc,
                enabled? asc | desc, status? asc | desc.
            filter: Filter applied to the data set.

        Returns:
            Dictionary containing 'data' (list of cluster dictionaries) and
            'pagination' (pagination metadata).
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
            f"/tools/{self._c.org_key}/clusters",
            params=params if params else None,
        )

    @functools.lru_cache(maxsize=1)
    def get_default_cluster_id(self) -> str:
        """Get the default cluster ID for the client.

        Returns the first cluster that does not have "dev" in the hostname.

        Returns:
            The ID of the default cluster.

        Raises:
            RuntimeError: If no clusters are found (excluding dev clusters).
        """
        response = self.list()
        clusters = response.get("data", [])
        # Filter out clusters with hostnames containing "dev"
        filtered_clusters = [
            cluster for cluster in clusters if "dev" not in cluster.get("hostname", "")
        ]
        if len(filtered_clusters) == 0:
            raise RuntimeError("No clusters found (excluding dev clusters).")
        cluster_id = filtered_clusters[0]["id"]
        return cluster_id
