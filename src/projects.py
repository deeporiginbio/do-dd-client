"""User-facing project helpers for the Deep Origin data platform.

Requires the ``core`` optional dependency (``pandas``) for DataFrame helpers.
"""

from __future__ import annotations

from typing import Any

from beartype import beartype
from beartype.typing import List

from deeporigin.config import clear_project_id, get_project_id, set_project_id
from deeporigin.drug_discovery.structures.ligand import LigandSet
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.constants import (
    ENTITIES_UNAVAILABLE_DETAIL,
    ENTITIES_UNAVAILABLE_TITLE,
    PROJECTS_UNAVAILABLE_DETAIL,
    PROJECTS_UNAVAILABLE_TITLE,
)


def _require_project_id() -> str:
    """Return the current project id or raise."""

    pid = get_project_id()
    if pid is None:
        raise DeepOriginException(
            title="No current project",
            message="Set a project with projects.load(...) or projects.create(...).",
            fix="Call projects.create('my-project') or projects.load('my-project').",
            level="danger",
        )
    return pid


@beartype
def current() -> str | None:
    """Return the current data platform project id from local config.

    Returns:
        Project id string, or None if none is selected.
    """

    return get_project_id()


def list_projects() -> Any:
    """List all projects as a DataFrame.

    Returns:
        DataFrame with columns ``id``, ``name``, ``description`` only.

    Raises:
        ImportError: If pandas is not installed.
    """

    import pandas as pd

    client = DeepOriginClient.get()
    if client.projects is None:
        raise DeepOriginException(
            title=PROJECTS_UNAVAILABLE_TITLE,
            message=PROJECTS_UNAVAILABLE_DETAIL,
            level="danger",
        )
    raw = client.projects.list()
    rows = raw.get("data") or []
    if not rows:
        return pd.DataFrame(columns=["id", "name", "description"])
    df = pd.DataFrame(rows)
    for col in ("id", "name", "description"):
        if col not in df.columns:
            df[col] = None
    return df[["id", "name", "description"]]


@beartype
def create(
    name: str,
    *,
    description: str | None = None,
    load: bool = True,
) -> None:
    """Create a project on the data platform.

    Args:
        name: Project display name.
        description: Optional description.
        load: When True (default), set the new project as current in
            ``~/.deeporigin/config.json``.
    """

    client = DeepOriginClient.get()
    if client.projects is None:
        raise DeepOriginException(
            title=PROJECTS_UNAVAILABLE_TITLE,
            message=PROJECTS_UNAVAILABLE_DETAIL,
            level="danger",
        )
    result = client.projects.create(name=name, description=description)
    data = result.get("data") or {}
    pid = data.get("id")
    if pid is None:
        raise DeepOriginException(
            title="Project create failed",
            message="API did not return a project id.",
            level="danger",
        )
    if load:
        set_project_id(str(pid))


@beartype
def load(identifier: str) -> None:
    """Select a project by id, name, or slug.

    Persists the resolved project id to ``~/.deeporigin/config.json``.

    Args:
        identifier: Project id, name, or slug string.

    Raises:
        DeepOriginException: If no matching project exists.
    """

    client = DeepOriginClient.get()
    if client.projects is None:
        raise DeepOriginException(
            title=PROJECTS_UNAVAILABLE_TITLE,
            message=PROJECTS_UNAVAILABLE_DETAIL,
            level="danger",
        )

    raw = client.projects.list()
    rows: List[dict[str, Any]] = raw.get("data") or []
    ident = identifier.strip()
    for row in rows:
        rid = str(row.get("id", ""))
        if rid == ident:
            set_project_id(rid)
            return
        if str(row.get("name", "")) == ident:
            set_project_id(str(row["id"]))
            return
        if str(row.get("slug", "")) == ident:
            set_project_id(str(row["id"]))
            return

    raise DeepOriginException(
        title="Project not found",
        message=f"No project matches {identifier!r}.",
        fix="Use projects.list() to see available projects.",
        level="danger",
    )


@beartype
def ligands() -> Any:
    """Ligands in the current project as a DataFrame.

    Returns:
        DataFrame with at least ``id``, ``name``, ``smiles``, ``canonical_smiles``.

    Raises:
        DeepOriginException: If no current project is set.
        ImportError: If pandas is not installed.
    """

    import pandas as pd

    pid = _require_project_id()
    client = DeepOriginClient.get()
    if client.entities is None:
        raise DeepOriginException(
            title=ENTITIES_UNAVAILABLE_TITLE,
            message=ENTITIES_UNAVAILABLE_DETAIL,
            level="danger",
        )
    raw = client.entities.search_ligands(
        filter_dict={"project_id": pid},
        limit=None,
        select=["id", "name", "smiles", "canonical_smiles"],
    )
    rows = raw.get("data") or []
    if not rows:
        return pd.DataFrame(columns=["id", "name", "smiles", "canonical_smiles"])
    df = pd.DataFrame(rows)
    for col in ("id", "name", "smiles", "canonical_smiles"):
        if col not in df.columns:
            df[col] = None
    return df[["id", "name", "smiles", "canonical_smiles"]]


@beartype
def proteins() -> Any:
    """Proteins in the current project as a DataFrame.

    Returns:
        DataFrame with ``id``, ``name``, ``file_path``, ``pdb_id``.

    Raises:
        DeepOriginException: If no current project is set.
        ImportError: If pandas is not installed.
    """

    import pandas as pd

    pid = _require_project_id()
    client = DeepOriginClient.get()
    if client.entities is None:
        raise DeepOriginException(
            title=ENTITIES_UNAVAILABLE_TITLE,
            message=ENTITIES_UNAVAILABLE_DETAIL,
            level="danger",
        )
    raw = client.entities.search(
        "proteins",
        filter_dict={"project_id": pid, "deleted": False},
        limit=10_000,
        select=["id", "protein_name", "file_path", "pdb_id"],
    )
    rows = raw.get("data") or []
    if not rows:
        return pd.DataFrame(columns=["id", "name", "file_path", "pdb_id"])
    df = pd.DataFrame(rows)
    if "protein_name" in df.columns:
        df = df.rename(columns={"protein_name": "name"})
    else:
        df["name"] = None
    for col in ("id", "name", "file_path", "pdb_id"):
        if col not in df.columns:
            df[col] = None
    return df[["id", "name", "file_path", "pdb_id"]]


@beartype
def executions() -> Any:
    """Executions associated with the current project.

    Returns:
        DataFrame with execution id, tool key, version, and timestamps.

    Raises:
        DeepOriginException: If no current project is set.
        ImportError: If pandas is not installed.
    """

    import pandas as pd

    pid = _require_project_id()
    client = DeepOriginClient.get()
    if client.entities is None:
        raise DeepOriginException(
            title=ENTITIES_UNAVAILABLE_TITLE,
            message=ENTITIES_UNAVAILABLE_DETAIL,
            level="danger",
        )
    raw = client.entities.search(
        "executions",
        filter_dict={"project_id": pid, "deleted": False},
        limit=10_000,
        select=[
            "id",
            "tool_key",
            "tool_version",
            "status",
            "started_at",
            "completed_at",
            "compute_job_id",
        ],
    )
    rows = raw.get("data") or []
    if not rows:
        return pd.DataFrame(
            columns=[
                "id",
                "tool_key",
                "tool_version",
                "status",
                "started_at",
                "completed_at",
                "compute_job_id",
            ]
        )
    df = pd.DataFrame(rows)
    df = df.rename(columns={"compute_job_id": "execution_id"})
    cols = [
        "id",
        "tool_key",
        "tool_version",
        "status",
        "started_at",
        "completed_at",
        "execution_id",
    ]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]


@beartype
def get_ligands(
    *,
    limit: int | None = None,
    **filter_kwargs: Any,
) -> LigandSet:
    """Load ligands for the current project as a :class:`LigandSet`.

    Args:
        limit: Max ligands to fetch (passed through to search).
        **filter_kwargs: Extra equality filters merged into the search filter.

    Raises:
        DeepOriginException: If no current project is set.
    """

    pid = _require_project_id()
    client = DeepOriginClient.get()
    if client.entities is None:
        raise DeepOriginException(
            title=ENTITIES_UNAVAILABLE_TITLE,
            message=ENTITIES_UNAVAILABLE_DETAIL,
            level="danger",
        )
    fd: dict[str, Any] = {"project_id": pid, "deleted": False}
    fd.update(filter_kwargs)
    raw = client.entities.search_ligands(
        filter_dict=fd,
        limit=limit,
    )
    ids = [str(r["id"]) for r in raw.get("data") or [] if r.get("id")]
    if not ids:
        return LigandSet(ligands=[])
    return LigandSet.from_ids(ids, client=client)


@beartype
def get_proteins(
    *,
    limit: int | None = 100,
    **filter_kwargs: Any,
) -> List[Protein]:
    """Load proteins for the current project.

    Args:
        limit: Max proteins to fetch.
        **filter_kwargs: Extra equality filters merged into the search filter.

    Raises:
        DeepOriginException: If no current project is set.
    """

    pid = _require_project_id()
    client = DeepOriginClient.get()
    if client.entities is None:
        raise DeepOriginException(
            title=ENTITIES_UNAVAILABLE_TITLE,
            message=ENTITIES_UNAVAILABLE_DETAIL,
            level="danger",
        )
    fd: dict[str, Any] = {"project_id": pid, "deleted": False}
    fd.update(filter_kwargs)
    raw = client.entities.search(
        "proteins",
        filter_dict=fd,
        limit=limit,
    )
    out: List[Protein] = []
    for row in raw.get("data") or []:
        row_id = row.get("id")
        if row_id is None:
            continue
        out.append(Protein.from_id(str(row_id), client=client))
    return out


@beartype
def set_ligands(ligands: LigandSet) -> None:
    """Sync a ligand set to the current project (upload + register).

    Args:
        ligands: Ligands to persist under the current project.

    Raises:
        DeepOriginException: If no current project is set.
    """

    _require_project_id()
    client = DeepOriginClient.get()
    ligands.sync(client=client)


@beartype
def set_proteins(proteins: List[Protein]) -> None:
    """Sync proteins to the current project.

    Args:
        proteins: Proteins to persist under the current project.

    Raises:
        DeepOriginException: If no current project is set.
    """

    _require_project_id()
    client = DeepOriginClient.get()
    for p in proteins:
        p.sync(client=client)


list = list_projects

__all__ = [
    "clear_project_id",
    "create",
    "current",
    "executions",
    "get_ligands",
    "get_proteins",
    "ligands",
    "list",
    "load",
    "proteins",
    "set_ligands",
    "set_proteins",
]
