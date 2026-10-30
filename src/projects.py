"""User-facing project helpers for the Deep Origin data platform.

Requires the ``core`` optional dependency (``pandas``) for DataFrame helpers.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import tempfile
from typing import Any, List

from beartype import beartype

from deeporigin.drug_discovery.import_dataset_sync import (
    run_import_dataset_workflow,
    stage_local_file,
    wait_for_import_ingestion,
)
from deeporigin.drug_discovery.structures.ligand import LigandSet
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.drug_discovery.structures.protein_files import (
    build_protein_bundle,
    find_structure_files,
    validate_structure_files,
)
from deeporigin.drug_discovery.structures.repr_display import (
    fetch_project_display_name,
)
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import is_success_status, normalize_platform_status
from deeporigin.utils.constants import (
    DATA_PLATFORM_INGESTION_TIMEOUT_SECONDS,
    ENTITIES_UNAVAILABLE_DETAIL,
    ENTITIES_UNAVAILABLE_TITLE,
    IMPORT_DATASET_PROTEINS_DATABASE_KEY,
    IMPORT_DATASET_PROTEINS_DATABASE_VERSION,
    PROTEIN_FOLDER_CSV_MAPPER,
    PROTEIN_FOLDER_IMPORT_TOOL_VERSION,
    PROTEIN_IMPORT_FAILED_TITLE,
    PROTEIN_SEARCH_PAGE_SIZE,
)


def _require_project_id() -> str:
    """Return the current project id or raise."""

    pid = DeepOriginClient().project_id
    if pid is None:
        raise DeepOriginException(
            title="No current project",
            message="Set a project with projects.load(...) or projects.create(...).",
            fix="Call projects.create('my-project') or projects.load('my-project').",
            level="danger",
        )
    return pid


@beartype
def current() -> tuple[str, str | None] | None:
    """Return the current project id and display name.

    The id comes from :attr:`deeporigin.platform.client.DeepOriginClient.project_id`
    (set via ``DO_PROJECT_ID`` env var, :func:`create`, or :func:`load`).
    The name is loaded from the data platform via
    :meth:`deeporigin.platform.projects.Projects.get`.

    Returns:
        ``(project_id, name)`` when a project is selected. ``name`` is ``None``
        if the project row could not be resolved.

        ``None`` when no project is selected.
    """

    client = DeepOriginClient()
    pid = client.project_id
    if pid is None:
        return None
    try:
        row = client.projects.get(project_id=pid)["data"]
    except DeepOriginException:
        return (pid, None)
    raw = row.get("name")
    return (pid, str(raw) if raw is not None else None)


@beartype
def list(*, limit: int | None = 100) -> Any:  # noqa: A001
    """List projects as a DataFrame.

    Args:
        limit: Maximum rows to return. Defaults to 100 (matches the data platform
            default for project search). Pass ``None`` to omit ``limit`` from the
            API request (server default applies).

    Returns:
        DataFrame with columns ``id``, ``name``, ``description`` only.

    Raises:
        ImportError: If pandas is not installed.
    """

    import pandas as pd

    client = DeepOriginClient()

    raw = client.projects.list(limit=limit)
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
    client: DeepOriginClient | None = None,
) -> str:
    """Create a project on the data platform, or select an existing one by name.

    If a non-deleted project already exists with the same display ``name`` (exact
    match), that row is used and no new project is created. Otherwise a new
    project is created. When multiple rows share the same name, the first search
    hit is used.

    Args:
        name: Project display name.
        description: Optional description. Used only when a new project is
            created; an existing match is not updated.
        load: When True (default), set the resolved project as active on the
            client instance.
        client: Platform client to use. Defaults to ``DeepOriginClient()``.

    Returns:
        The project id (canonical id string from the data platform).
    """

    if client is None:
        client = DeepOriginClient()

    # Use exact name match, not icontains (``name=`` in search is substring match).
    existing = client.projects.search(
        filter_dict={"name": {"eq": name}},
        limit=100,
    )
    rows = [r for r in existing.get("data") or [] if r.get("name") == name]
    if rows:
        row = rows[0]
        pid = row.get("id") or row.get("canonical_id")
    else:
        result = client.projects.create(name=name, description=description)
        data = result.get("data") or {}
        pid = data.get("id") or data.get("canonical_id")
        if pid is None:
            raise DeepOriginException(
                title="Project create failed",
                message="API did not return a project id.",
                level="danger",
            )

    if pid is None:
        raise DeepOriginException(
            title="Project create failed",
            message="API did not return a project id.",
            level="danger",
        )
    if load:
        client.project_id = str(pid)

    return str(pid)


@beartype
def load(identifier: str, *, client: DeepOriginClient | None = None) -> None:
    """Select a project by id, name, or slug.

    Sets ``client.project_id`` to the resolved id. No disk writes are performed.

    Args:
        identifier: Project id, name, or slug string.
        client: Platform client to use. Defaults to ``DeepOriginClient()``.

    Raises:
        DeepOriginException: If no matching project exists.
    """

    if client is None:
        client = DeepOriginClient()

    raw = client.projects.list()
    rows: List[dict[str, Any]] = raw.get("data") or []
    ident = identifier.strip()
    for row in rows:
        rid = str(row.get("id", ""))
        if rid == ident:
            client.project_id = rid
            return
        if str(row.get("name", "")) == ident:
            client.project_id = str(row["id"])
            return
        if str(row.get("slug", "")) == ident:
            client.project_id = str(row["id"])
            return

    raise DeepOriginException(
        title="Project not found",
        message=f"No project matches {identifier!r}.",
        fix="Use projects.list() to see available projects.",
        level="danger",
    )


@beartype
def ligands(*, client: DeepOriginClient | None = None) -> Any:
    """Ligands in the current project as a DataFrame.

    Returns:
        DataFrame with at least ``id``, ``name``, ``smiles``, ``canonical_smiles``.

    Raises:
        DeepOriginException: If no current project is set.
        ImportError: If pandas is not installed.
    """

    import pandas as pd

    pid = _require_project_id()
    if client is None:
        client = DeepOriginClient()

    raw = client.entities.search_ligands(
        filter_dict={"project_id": pid},
        limit=None,
        select=["id", "name", "smiles"],
    )
    rows = raw.get("data") or []
    if not rows:
        return pd.DataFrame(columns=["id", "name", "smiles"])
    df = pd.DataFrame(rows)
    for col in ("id", "name", "smiles"):
        if col not in df.columns:
            df[col] = None
    return df[["id", "name", "smiles"]]


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
    client = DeepOriginClient()
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
    client = DeepOriginClient()
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
                "execution_id",
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
    client = DeepOriginClient()
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
) -> Sequence[Protein]:
    """Load proteins for the current project as metadata-only Protein objects.

    Structures are not downloaded; call :meth:`~deeporigin.drug_discovery.structures.protein.Protein.download`
    to hydrate a protein. This keeps listing resilient when a remote PDB is
    missing or unparseable.

    Args:
        limit: Max proteins to fetch.
        **filter_kwargs: Extra equality filters merged into the search filter.

    Raises:
        DeepOriginException: If no current project is set.
    """

    pid = _require_project_id()
    client = DeepOriginClient()
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
    out: list[Protein] = []
    for row in raw.get("data") or []:
        row_id = row.get("id")
        if row_id is None:
            continue
        out.append(Protein.from_id(str(row_id), client=client, download=False))
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
    client = DeepOriginClient()
    ligands.sync(client=client)


@beartype
def set_proteins(proteins: Sequence[Protein]) -> None:
    """Sync proteins to the current project.

    Args:
        proteins: Proteins to persist under the current project.

    Raises:
        DeepOriginException: If no current project is set.
    """

    _require_project_id()
    client = DeepOriginClient()
    for p in proteins:
        p.sync(client=client)


@beartype
def sync_proteins(
    path: str | Path | Sequence[str | Path],
    *,
    recursive: bool = False,
    timeout: int | float = DATA_PLATFORM_INGESTION_TIMEOUT_SECONDS,
) -> Sequence[Protein]:
    """Import a folder of protein structure files into the current project.

    Each ``.pdb``, ``.cif``, ``.mmcif`` or ``.ent`` file becomes one protein
    named after its file name without extension, as with
    ``Protein.from_file(path).sync()``. Files that share a name become separate
    proteins. A structure already in the project is reused and keeps its name.

    Every file is checked first, and if any can't be imported nothing is
    uploaded and one error lists them all. The import then runs on Deep Origin;
    this waits on the platform's live update stream rather than holding a
    request open, and returns once the proteins are saved.

    Args:
        path: A folder, a single file, or a list of files.
        recursive: Also import files in subfolders.
        timeout: Seconds to wait for the import before giving up.

    Returns:
        Sequence[Protein]: Every protein in the current project, not only the
        imported files, metadata only (no structure downloaded).

    Raises:
        DeepOriginException: If no current project is set, the entities API is
            unavailable, any file can't be imported, or the import does not
            start or does not succeed.
        TimeoutError: If the import has not finished within ``timeout``. The
            message includes the import's execution id.
    """

    project_id = _require_project_id()
    client = DeepOriginClient()
    if client.entities is None:
        raise DeepOriginException(
            title=ENTITIES_UNAVAILABLE_TITLE,
            message=ENTITIES_UNAVAILABLE_DETAIL,
            level="danger",
        )
    files = find_structure_files(path, recursive=recursive)
    validate_structure_files(files)
    with tempfile.TemporaryDirectory() as tmp:
        zip_path, csv_path = build_protein_bundle(files, tmp)
        inputs = {
            "csv_path": stage_local_file(client, csv_path),
            "protein_zip_path": stage_local_file(client, zip_path),
            "mapper": PROTEIN_FOLDER_CSV_MAPPER,
            "database_key": IMPORT_DATASET_PROTEINS_DATABASE_KEY,
            "database_version": IMPORT_DATASET_PROTEINS_DATABASE_VERSION,
        }
    dto = run_import_dataset_workflow(
        inputs=inputs,
        project_id=project_id,
        client=client,
        tool_version=PROTEIN_FOLDER_IMPORT_TOOL_VERSION,
    )
    execution_id = dto.get("executionId")
    if not execution_id:
        raise DeepOriginException(
            title=PROTEIN_IMPORT_FAILED_TITLE,
            message="Deep Origin did not start the protein import.",
            fix="Try again. If it keeps failing, contact support.",
        )
    return _wait_for_import(client, str(execution_id), project_id, timeout=timeout)


def _wait_for_import(
    client: DeepOriginClient,
    execution_id: str,
    project_id: str,
    *,
    timeout: int | float,
) -> list[Protein]:
    """Wait for a protein import (SSE, else polling), raise if it failed, else return proteins."""
    row = wait_for_import_ingestion(
        client, execution_id, project_id=project_id, timeout=timeout
    )
    status = normalize_platform_status(row.get("status"))
    if not is_success_status(status):
        reason = _status_reason(client, execution_id) or status
        raise DeepOriginException(
            title=PROTEIN_IMPORT_FAILED_TITLE,
            message=(
                f"The protein import (execution_id={execution_id!r}) ended with "
                f"status {status!r}: {reason}"
            ),
            fix="Check the files, then run projects.sync_proteins again.",
        )
    return _project_proteins(client, project_id)


def _status_reason(client: DeepOriginClient, execution_id: str) -> str | None:
    """Return the tools-service ``statusReason`` for an execution.

    The data-platform execution row carries no failure reason, so it is read
    from the tools-service execution.
    """
    dto = client.executions.get(execution_id)  # ty: ignore[unresolved-attribute]
    reason = dto.get("statusReason") if isinstance(dto, dict) else None
    return str(reason) if reason else None


def _project_proteins(client: DeepOriginClient, project_id: str) -> list[Protein]:
    """Read every protein in a project as metadata-only proteins, following the search cursor."""
    project_name = fetch_project_display_name(project_id, None, client=client)[0]
    out: list[Protein] = []
    cursor: str | None = None
    while True:
        response = client.entities.search_proteins(  # ty: ignore[unresolved-attribute]
            project_id=project_id,
            limit=PROTEIN_SEARCH_PAGE_SIZE,
            cursor=cursor,
        )
        out.extend(
            Protein._from_platform_record(
                record,
                client=client,
                remote_path=record.get("file_path"),
                project_name=project_name,
            )
            for record in response.get("data") or []
            if isinstance(record, dict)
        )
        cursor = (response.get("meta") or {}).get("nextCursor")
        if not cursor:
            return out


__all__ = [
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
    "sync_proteins",
]
