"""Gateway SSE stream route for the mock server."""

from __future__ import annotations

from collections.abc import Iterator
import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

MOCK_SSE_RETRY_MS = 3000
"""``retry:`` value (milliseconds) sent when a mock stream opens."""


def create_sse_router() -> APIRouter:
    """Create a router for the gateway's project SSE stream.

    Returns:
        APIRouter instance with the SSE stream route.
    """
    router = APIRouter()

    @router.get("/sse/{org_key}/stream/{project_id}")
    def stream_project(
        org_key: str,
        project_id: str,
        request: Request,
    ) -> StreamingResponse:
        """Open a project stream that marks every requested filter dirty once.

        Sends the ``retry:`` line, one ``filters.dirty`` frame naming each
        ``filter=<id>=<pattern>`` query param, then closes, as the gateway does
        when its stream lifetime ends. A waiter therefore re-reads once on the
        frame and once more on reconnect.
        """
        filter_ids = [
            raw.split("=", 1)[0] for raw in request.query_params.getlist("filter")
        ]

        def frames() -> Iterator[str]:
            """Yield the retry line and one dirty frame, then end the stream."""
            yield f"retry: {MOCK_SSE_RETRY_MS}\n\n"
            payload = {
                "type": "filters.dirty",
                "filters": filter_ids,
                "flushedAt": int(time.time() * 1000),
            }
            yield f"data: {json.dumps(payload)}\n\n"

        return StreamingResponse(frames(), media_type="text/event-stream")

    return router
