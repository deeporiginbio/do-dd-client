"""Formatting helpers shared by structure ``__repr__`` and notebook display."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

# Indent for fields inside ``TypeName( ... )`` pretty-print blocks.
REPR_INNER_INDENT = "  "


def fetch_project_display_name(
    project_id: str | None,
    cached_name: str | None = None,
    *,
    client: DeepOriginClient | None = None,
) -> tuple[str, str | None]:
    """Resolve a human-readable project name for structure reprs.

    Returns:
        ``(display, updated_cache)`` — ``updated_cache`` is set when a name was
        fetched from the platform.
    """
    if cached_name:
        return cached_name, cached_name
    if not project_id:
        return "", cached_name

    from deeporigin.exceptions import DeepOriginException

    pid_display = str(project_id).strip()

    if client is None:
        return pid_display, cached_name

    try:
        if client.projects is None:
            return pid_display, cached_name
        row = client.projects.get(project_id=str(project_id))["data"]
        raw = row.get("name")
        if raw is not None:
            name = str(raw)
            return name, name
    except DeepOriginException:
        pass
    return pid_display, cached_name


def metadata_repr_html(text: str) -> str:
    """Wrap plain-text metadata in a monospace ``<pre>`` for Jupyter."""
    from html import escape

    return (
        "<pre style='margin:0;font-family:ui-monospace,SFMono-Regular,Menlo,"
        "monospace'>"
        f"{escape(text, quote=False)}</pre>"
    )
