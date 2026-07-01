"""Helpers for merging provenance tags onto data-platform entity rows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


def merge_entity_tags(
    client: DeepOriginClient,
    tags: dict[str, Any] | None,
    *,
    always: bool = False,
) -> dict[str, Any] | None:
    """Merge provenance ``app`` / ``session`` from the client onto entity tags.

    Caller-supplied keys win on collision. When ``always`` is True, returns at
    least ``{app, session}`` even when ``tags`` is ``None`` (create paths).
    When ``always`` is False and ``tags`` is ``None``, returns ``None`` so
    update callers omit the column.

    Args:
        client: API client supplying ``_app`` and ``_session``.
        tags: Optional user-defined tag dict.
        always: When True, always return a tags dict with provenance stamped.

    Returns:
        Merged tags dict, or ``None`` when ``always`` is False and ``tags`` is
        ``None``.

    Raises:
        TypeError: If ``tags`` is not a dict when provided.
    """
    if tags is not None and not isinstance(tags, dict):
        raise TypeError("tags must be a dict or None")

    if tags is None and not always:
        return None

    merged: dict[str, Any] = dict(tags) if tags is not None else {}
    merged.setdefault("app", client._app)
    merged.setdefault("session", client._session)
    return merged


def stamp_batch_row_tags(
    client: DeepOriginClient,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return row copies with provenance merged into each row's ``tags`` field.

    Args:
        client: API client supplying provenance fields.
        rows: Batch-create row dicts.

    Returns:
        New list of row dicts with ``tags`` always set.

    Raises:
        TypeError: If a row's ``tags`` value is not a dict when present.
    """
    stamped: list[dict[str, Any]] = []
    for row in rows:
        new_row = dict(row)
        user_tags = new_row.get("tags")
        if user_tags is not None and not isinstance(user_tags, dict):
            raise TypeError("row tags must be a dict or omitted")
        new_row["tags"] = merge_entity_tags(
            client,
            user_tags if isinstance(user_tags, dict) else None,
            always=True,
        )
        stamped.append(new_row)
    return stamped
