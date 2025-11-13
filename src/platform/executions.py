"""Executions API wrapper for DeepOriginClient."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

from deeporigin.platform.constants import TERMINAL_STATES


class Executions:
    """Executions API wrapper.

    Provides access to tool execution-related endpoints through the DeepOriginClient.
    """

    def __init__(self, client: DeepOriginClient) -> None:
        """Initialize Executions wrapper.

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
        """List tool executions with pagination and filtering.

        Args:
            page: Page number of the pagination (default 0).
            page_size: Page size of the pagination (max 10,000).
            order: Order of the pagination, e.g., "executionId? asc", "completedAt? desc".
            filter: Filter applied to the data set Execution Model.

        Returns:
            Dictionary containing paginated execution data.
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
            f"/tools/{self._c.org_key}/tools/executions",
            params=params if params else None,
        )

    def get_execution(self, *, execution_id: str) -> dict:
        """Get a tool execution by execution ID.

        Args:
            execution_id: The execution ID to get.

        Returns:
            Dictionary containing the tool execution data.
        """
        return self._c.get_json(
            f"/tools/{self._c.org_key}/tools/executions/{execution_id}"
        )

    def cancel(self, *, execution_id: str) -> None:
        """Cancel a tool execution.

        Args:
            execution_id: The execution ID to cancel.

        Returns:
            None. If the execution is already in a terminal state, returns early.
        """
        # Get the execution to check its status
        data = self.get_execution(execution_id=execution_id)

        # If already in a terminal state, no need to cancel
        if data.get("status") in TERMINAL_STATES:
            return

        # Cancel the execution
        self._c._patch(
            f"/tools/{self._c.org_key}/tools/executions/{execution_id}:cancel"
        )

    def confirm(self, *, execution_id: str) -> None:
        """Confirm a tool execution.

        Args:
            execution_id: The execution ID to confirm.

        Returns:
            None.
        """
        # Confirm the execution
        self._c._patch(
            f"/tools/{self._c.org_key}/tools/executions/{execution_id}:confirm"
        )

    def get_status(self, *, execution_id: str) -> str:
        """Get the status of a tool execution.

        Args:
            execution_id: The execution ID to get the status for.

        Returns:
            The status string, e.g., "Created", "Queued", "Running", "Succeeded", or "Failed".
        """
        data = self.get_execution(execution_id=execution_id)
        return data.get("status", "")
