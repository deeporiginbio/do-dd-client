"""Functions API wrapper for DeepOriginClient."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


class Functions:
    """Functions API wrapper.

    Provides access to functions-related endpoints through the DeepOriginClient.
    """

    def __init__(self, client: DeepOriginClient) -> None:
        """Initialize Functions wrapper.

        Args:
            client: The DeepOriginClient instance to use for API calls.
        """
        self._c = client

    def run_latest(
        self,
        *,
        key: str,
        params: dict,
        cluster_id: str | None = None,
        tag: str | None = None,
    ) -> dict:
        """Run the latest enabled version of a function.

        Args:
            key: Key of the function to run.
            params: Function execution parameters.
            cluster_id: Cluster ID to run the function on. If None, uses the
                default cluster ID (first non-dev cluster, cached).
            tag: Optional tag for the execution.

        Returns:
            Dictionary containing the execution response from the API.
        """
        if cluster_id is None:
            cluster_id = self._c.clusters.get_default_cluster_id()

        body: dict[str, dict | str] = {
            "params": params,
            "clusterId": cluster_id,
        }
        if tag is not None:
            body["tag"] = tag

        # functions need a longer timeout
        original_timeout = self._c._client.timeout
        self._c._client.timeout = 600

        response = self._c.post_json(
            f"/tools/{self._c.org_key}/functions/{key}",
            json=body,
        )
        self._c._client.timeout = original_timeout

        return response

    def run(
        self,
        *,
        key: str,
        version: str,
        params: dict,
        cluster_id: str | None = None,
        tag: str | None = None,
    ) -> dict:
        """Run a specific version of a function.

        Args:
            key: Key of the function to run.
            version: Version of the function to run.
            params: Function execution parameters.
            cluster_id: Cluster ID to run the function on. If None, uses the
                default cluster ID (first non-dev cluster, cached).
            tag: Optional tag for the execution.

        Returns:
            Dictionary containing the execution response from the API.
        """
        if cluster_id is None:
            cluster_id = self._c.clusters.get_default_cluster_id()

        body: dict[str, dict | str] = {
            "params": params,
            "clusterId": cluster_id,
        }
        if tag is not None:
            body["tag"] = tag

        # functions need a longer timeout
        original_timeout = self._c._client.timeout
        self._c._client.timeout = 600

        response = self._c.post_json(
            f"/tools/{self._c.org_key}/functions/{key}/{version}",
            json=body,
        )
        self._c._client.timeout = original_timeout

        return response
