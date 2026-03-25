"""Data Platform progress reports API wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


class ProgressReports:
    """Progress reports API wrapper.

    Provides access to execution progress report endpoints through
    the Data Platform's ``executions/search`` API.
    """

    def __init__(self, client: DeepOriginClient) -> None:
        """Initialize ProgressReports wrapper.

        Args:
            client: The DeepOriginClient instance to use for API calls.
        """
        self._c = client

    def get(self, execution_id: str) -> dict[str, Any]:
        """Get progress reports for a tool execution.

        Searches the data platform executions table for records matching
        the given execution ID (mapped to ``compute_job_id`` in the API)
        and returns the full history.

        Args:
            execution_id: The tool execution ID to fetch progress reports for.

        Returns:
            Dictionary containing the search response with execution
            history data.
        """
        body: dict[str, Any] = {
            "filter": {
                "compute_job_id": {"eq": execution_id},
            },
            "with_history": True,
        }
        return self._c.post_json(
            f"/data-platform/{self._c.org_key}/executions/search",
            body=body,
        )
