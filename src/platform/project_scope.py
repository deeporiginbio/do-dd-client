"""Project scoping helpers for platform writes."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

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


@contextmanager
def execution_project_scope(
    client: DeepOriginClient,
    dto: dict[str, Any],
) -> Iterator[None]:
    """Temporarily align ``client.project_id`` with an execution DTO.

    Tool executions may omit ``projectId`` (org-wide runs) or use a different
    project than the notebook's current ``projects.load()`` selection. Entity
    lookups during :meth:`~deeporigin.drug_discovery.execution.Execution.from_dto`
    should use the execution's scope, not the caller's session project.

    When ``projectId`` is absent from *dto*, the client's project is left unchanged.
    """
    if "projectId" not in dto:
        yield
        return
    saved = client.project_id
    raw = dto.get("projectId")
    client.project_id = str(raw).strip() if raw else None
    try:
        yield
    finally:
        client.project_id = saved


def adopt_client_project_from_execution_dto(
    client: DeepOriginClient,
    dto: dict[str, Any],
) -> None:
    """Set ``client.project_id`` from an execution DTO after :meth:`from_dto`.

    Rehydration uses :func:`execution_project_scope` only while inputs are
    parsed; follow-up ``results.get`` / entity calls need the execution's
    project (or explicit org-wide ``None``) on the client. When ``projectId``
    is absent from *dto*, the client's project is left unchanged.
    """
    if "projectId" not in dto:
        return
    raw = dto.get("projectId")
    client.project_id = str(raw).strip() if raw else None
