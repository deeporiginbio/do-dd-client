"""Data Platform projects API wrapper."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
import uuid

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

# Must match ``projects`` schema fields (snake_case). Versioned entities expose
# ``canonical_id`` at the API; ``renderRowForClient`` maps it to ``id`` when
# appropriate — include ``canonical_id`` so the created row is returned.
# Do not use ``id`` or ``project_id`` here: the former is storage-only for
# versioned rows, and ``project_id`` is not a column on ``projects``.
PROJECT_RETURNING_FIELDS = [
    "canonical_id",
    "version",
    "valid_from",
    "valid_to",
    "modified_by",
    "deleted",
    "subtable_name",
    "name",
    "slug",
    "description",
    "tags",
    "notes",
    "url_token",
]


def _slug_from_name(name: str) -> str:
    """Build a URL-safe slug from a display name.

    Args:
        name: Human-readable project name.

    Returns:
        A non-empty slug string (with a short suffix for uniqueness).
    """

    base = re.sub(r"[^a-z0-9]+", "-", name.lower().strip())
    base = base.strip("-")[:60]
    if not base:
        base = "project"
    return f"{base}-{uuid.uuid4().hex[:8]}"


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

    def list(self, *, limit: int | None = 100) -> dict[str, Any]:
        """List projects via search (non-deleted rows only).

        Args:
            limit: Maximum rows to return. Defaults to 100 (data platform default
                when a limit is applied). Pass ``None`` to omit ``limit`` from the
                request body (server default applies).

        Returns:
            Dictionary containing the list of projects (``data``, ``count``).
        """
        return self.search(limit=limit)

    def search(
        self,
        *,
        name: str | None = None,
        filter_dict: dict[str, Any] | None = None,
        limit: int | None = 100,
        offset: int | None = None,
        select: list[str] | None = None,
        sort: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Search projects with optional filters.

        The data platform applies ``filter`` as column predicates: plain values
        use equality; objects use operators (e.g. ``{"name": {"icontains": "x"}}``).
        See platform ``buildFilterWhere`` / entity search validation for supported ops.

        Args:
            name: If set, restricts to rows whose ``name`` matches this substring
                (case-insensitive), via ``{"icontains": name}``. Applied after
                ``filter_dict`` and overrides a ``name`` key there.
            filter_dict: Extra filter criteria (``deleted`` is set False if omitted).
            limit: Maximum rows to return.
            offset: Skip offset.
            select: Column selection list.
            sort: Sort mapping.

        Returns:
            Search response from the data platform.
        """
        body: dict[str, Any] = {}
        fd: dict[str, Any] = {"deleted": False}
        if filter_dict is not None:
            fd = filter_dict.copy()
            fd.setdefault("deleted", False)
        if name is not None:
            fd["name"] = {"icontains": name}
        body["filter"] = fd
        if limit is not None:
            body["limit"] = limit
        if offset is not None:
            body["offset"] = offset
        if select is not None:
            body["select"] = select
        if sort is not None:
            body["sort"] = sort
        return self._c.post_json(
            f"/data-platform/{self._c.org_key}/projects/search",
            body=body,
        )

    def get(self, *, project_id: str) -> dict[str, Any]:
        """Fetch a single project by id via search.

        Args:
            project_id: Data platform project id.

        Returns:
            Dict with a ``data`` key holding the project row.

        Raises:
            DeepOriginException: If no project matches ``project_id``.
        """
        from deeporigin.exceptions import DeepOriginException

        r = self.search(filter_dict={"id": project_id}, limit=1)
        rows = r.get("data") or []
        if not rows:
            raise DeepOriginException(
                title="Project not found",
                message=f"No project with id {project_id!r}.",
                fix="Use projects.list() to see available projects.",
                level="danger",
            )
        return {"data": rows[0]}

    def create(
        self,
        *,
        name: str,
        description: str | None = None,
        slug: str | None = None,
    ) -> dict[str, Any]:
        """Create a project row.

        Args:
            name: Display name (required by the platform schema).
            description: Optional long description.
            slug: Optional slug; generated from ``name`` when omitted.

        Returns:
            API response containing the created row under ``data``.
        """
        set_dict: dict[str, Any] = {
            "subtable_name": "projects",
            "name": name,
            "slug": slug if slug is not None else _slug_from_name(name),
        }
        if description is not None:
            set_dict["description"] = description

        body: dict[str, Any] = {
            "set": set_dict,
            "returning": PROJECT_RETURNING_FIELDS,
        }
        return self._c.post_json(
            f"/data-platform/{self._c.org_key}/projects",
            body=body,
        )
