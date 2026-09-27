"""Project scoping helpers for platform writes."""

from __future__ import annotations

from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient


def require_client_project_id(
    client: DeepOriginClient,
    *,
    entity_project_id: str | None = None,
) -> str:
    """Return non-empty ``client.project_id`` for tool runs and entity sync.

    When ``entity_project_id`` is set, it must match the client's project.

    Args:
        client: Platform client that must be scoped to a project.
        entity_project_id: Optional project id already stored on an entity row.

    Returns:
        Stripped project id string from the client.

    Raises:
        DeepOriginException: If the client has no project or entity scope conflicts.
    """
    client_proj = client.project_id
    if client_proj is None or not str(client_proj).strip():
        raise DeepOriginException(
            title="Project required",
            message=(
                "Set client.project_id (constructor, DO_PROJECT_ID, or the "
                "project_id property) before running tools or syncing entities."
            ),
        )
    resolved = str(client_proj).strip()
    if entity_project_id is not None and str(entity_project_id).strip():
        entity = str(entity_project_id).strip()
        if entity != resolved:
            raise DeepOriginException(
                title="Project scope conflict",
                message=(
                    "entity project_id does not match client.project_id; "
                    "use a client scoped to the entity project instead of "
                    "mutating client.project_id."
                ),
            )
    return resolved


def stamp_execution_project_id(
    client: DeepOriginClient,
    payload: dict,
) -> None:
    """Set ``projectId`` on an execution create payload from the client.

    Rejects a non-empty ``projectId`` in ``payload`` that disagrees with the client.

    Args:
        client: Client supplying the authoritative project scope.
        payload: Execution create body (mutated in place).

    Raises:
        DeepOriginException: If the client has no project or payload conflicts.
    """
    resolved = require_client_project_id(client)
    explicit = payload.get("projectId")
    if explicit is not None and str(explicit).strip():
        if str(explicit).strip() != resolved:
            raise DeepOriginException(
                title="Project scope conflict",
                message=(
                    "execution payload projectId does not match client.project_id; "
                    "project scope is taken from the client only."
                ),
            )
    payload["projectId"] = resolved
