"""Hidden import-dataset executions for entity .sync() (served and workflow)."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Optional
import uuid

from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import (
    TERMINAL_STATES,
    TOOL_KEYS_AND_VERSIONS,
    is_success_status,
    normalize_platform_status,
)
from deeporigin.platform.project_scope import require_client_project_id

MAX_SERVED_FILE_LIGAND_RECORDS = 500

IMPORT_DATASET_LIGANDS_DATABASE_KEY = "deeporigin.attributes_catalog"
IMPORT_DATASET_LIGANDS_DATABASE_VERSION = "1.0.0"
LIGANDS_CSV_MAPPER: list[dict[str, str]] = [
    {"field": "smiles", "json-path": "ligands.smiles"},
]

DATA_PLATFORM_DATA_INGESTING_STATUS = "DataIngesting"

_FAILED_DP_STATUSES = frozenset({"Failed", "Cancelled"})
_SMILES_LIST_SEARCH_CHUNK = 500
_DEFAULT_TOOLS_POLL_INTERVAL_S = 2.0
_DEFAULT_TOOLS_WAIT_TIMEOUT_S = 3600.0
_DEFAULT_INGESTION_POLL_INTERVAL_S = 2.0
_DEFAULT_INGESTION_WAIT_TIMEOUT_S = 3600.0


def run_import_dataset_sync(
    *,
    inputs: dict[str, Any],
    project_id: str,
    client: Optional[DeepOriginClient] = None,
) -> dict[str, Any]:
    """Run a blocking served import-dataset execution and return the execution DTO."""
    return _create_import_dataset_execution(
        inputs=inputs,
        project_id=project_id,
        client=client,
        sync=True,
    )


def run_import_dataset_workflow(
    *,
    inputs: dict[str, Any],
    project_id: str,
    client: Optional[DeepOriginClient] = None,
) -> dict[str, Any]:
    """Start a workflow import-dataset execution and return the creation DTO."""
    return _create_import_dataset_execution(
        inputs=inputs,
        project_id=project_id,
        client=client,
        sync=False,
    )


def _create_import_dataset_execution(
    *,
    inputs: dict[str, Any],
    project_id: str,
    client: Optional[DeepOriginClient] | None,
    sync: bool,
) -> dict[str, Any]:
    if client is None:
        client = DeepOriginClient()
    proj = require_client_project_id(client)
    if project_id is not None and str(project_id).strip():
        if str(project_id).strip() != proj:
            raise DeepOriginException(
                title="Project scope conflict",
                message=(
                    "import-dataset project_id does not match client.project_id; "
                    "scope is taken from the client only."
                ),
            )
    tool_meta = TOOL_KEYS_AND_VERSIONS["import_dataset"]
    raw = client.executions.create(  # ty: ignore[unresolved-attribute]
        tool_key=tool_meta["tool_key"],
        tool_version=tool_meta["tool_version"],
        data={
            "inputs": inputs,
            "outputs": {},
            "metadata": {},
            "sync": sync,
            "visibility": "hidden",
        },
    )
    return raw if isinstance(raw, dict) else {}


def job_outputs(dto: dict[str, Any]) -> dict[str, Any]:
    """Return jobOutputs dict from an execution DTO."""
    jo = dto.get("jobOutputs")
    return jo if isinstance(jo, dict) else {}


def job_outputs_with_execution_id(dto: dict[str, Any]) -> dict[str, Any]:
    """Return jobOutputs plus ``import_execution_id`` when the DTO has one."""
    outputs = job_outputs(dto)
    eid = dto.get("executionId")
    if eid:
        outputs = {**outputs, "import_execution_id": str(eid)}
    return outputs


def require_uniform_scope(
    values: list[str | None],
    *,
    field_label: str,
    title: str = "Sync failed",
) -> str:
    """Require every entity in a batch sync shares the same scope value."""
    normalized = [str(v).strip() for v in values if v is not None and str(v).strip()]
    if not normalized:
        raise DeepOriginException(
            title=title,
            message=f"{field_label} is required for batch sync.",
        )
    unique = set(normalized)
    if len(unique) > 1:
        raise DeepOriginException(
            title=title,
            message=(
                f"Mixed {field_label} values in one batch are not supported "
                f"({len(unique)} distinct values). Sync each scope separately."
            ),
        )
    return normalized[0]


def require_project_id(
    *,
    entity_project_id: str | None,
    client: DeepOriginClient,
) -> str:
    """Resolve and validate project scope for entity sync (client is authoritative)."""
    return require_client_project_id(client, entity_project_id=entity_project_id)


def stage_local_file(
    client: DeepOriginClient,
    local_path: str | Path,
    *,
    remote_path: str | None = None,
) -> str:
    """Upload a local file to UFA and return the remote key."""
    path = Path(local_path)
    suffix = path.suffix or ".dat"
    dest = remote_path or f"imports/staging/{uuid.uuid4().hex}{suffix}"
    client.files.upload(str(path), remote_path=dest)
    return dest


def poll_tools_execution_terminal(
    client: DeepOriginClient,
    execution_id: str,
    *,
    poll_interval: float = _DEFAULT_TOOLS_POLL_INTERVAL_S,
    timeout: float | None = _DEFAULT_TOOLS_WAIT_TIMEOUT_S,
) -> dict[str, Any]:
    """Block until the tools-service execution reaches a terminal state."""
    dtos = client.executions.wait(  # ty: ignore[unresolved-attribute]
        execution_id,
        poll_interval=poll_interval,
        timeout=timeout,
    )
    dto = dtos[0]
    status = normalize_platform_status(dto.get("status"))
    if status in _FAILED_DP_STATUSES:
        raise DeepOriginException(
            title="Ligand import failed",
            message=f"import-dataset execution ended with status {status!r}.",
        )
    if not is_success_status(status):
        raise DeepOriginException(
            title="Ligand import failed",
            message=(
                f"import-dataset execution ended with unexpected status {status!r}."
            ),
        )
    return dto


def wait_for_data_platform_ingestion(
    client: DeepOriginClient,
    compute_job_id: str,
    *,
    poll_interval: float = _DEFAULT_INGESTION_POLL_INTERVAL_S,
    timeout: float | None = _DEFAULT_INGESTION_WAIT_TIMEOUT_S,
) -> dict[str, Any]:
    """Poll data-platform execution until ingestion leaves ``DataIngesting``."""
    deadline = time.monotonic() + timeout if timeout is not None else None
    last_row: dict[str, Any] | None = None
    while True:
        resp = client.executions.search(  # ty: ignore[unresolved-attribute]
            compute_job_id=compute_job_id,
            limit=1,
        )
        rows = resp.get("data") or []
        if rows:
            last_row = rows[0] if isinstance(rows[0], dict) else None
        if last_row is not None:
            status = normalize_platform_status(last_row.get("status"))
            if status == DATA_PLATFORM_DATA_INGESTING_STATUS:
                pass
            elif status in _FAILED_DP_STATUSES:
                raise DeepOriginException(
                    title="Ligand import failed",
                    message=(
                        f"Data platform ingestion failed with status {status!r}."
                    ),
                )
            elif is_success_status(status):
                return last_row
            elif status in TERMINAL_STATES:
                raise DeepOriginException(
                    title="Ligand import failed",
                    message=(
                        f"Data platform execution ended with status {status!r}."
                    ),
                )

        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError(
                f"Timed out waiting for data-platform ingestion (compute_job_id="
                f"{compute_job_id!r})."
            )
        time.sleep(poll_interval)


def _dp_execution_row_id(row: dict[str, Any]) -> str | None:
    for key in ("id", "canonical_id", "execution_id", "executionId"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _ligand_ids_from_execution_subjects(
    client: DeepOriginClient,
    *,
    execution_row_id: str,
) -> list[str]:
    filter_dict: dict[str, Any] = {
        "execution_id": {"eq": execution_row_id},
        "entity_type": {"eq": "ligand"},
    }
    resp = client.entities.search(  # ty: ignore[unresolved-attribute]
        "execution_subjects",
        filter_dict=filter_dict,
        limit=50_000,
    )
    rows = resp.get("data") or []
    ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ref = row.get("entity_canonical_id") or row.get("entityCanonicalId")
        if ref is not None and str(ref).strip():
            ids.append(str(ref).strip())
    return ids


def _ligand_records_by_canonical_smiles(
    client: DeepOriginClient,
    *,
    canonical_smiles: list[str],
    project_id: str,
) -> dict[str, dict[str, Any]]:
    unique = list(dict.fromkeys(s for s in canonical_smiles if s))
    by_canonical: dict[str, dict[str, Any]] = {}
    for start in range(0, len(unique), _SMILES_LIST_SEARCH_CHUNK):
        chunk = unique[start : start + _SMILES_LIST_SEARCH_CHUNK]
        if not chunk:
            continue
        resp = client.entities.search_ligands(  # ty: ignore[unresolved-attribute]
            smiles_list=chunk,
            filter_dict={"project_id": project_id},
            limit=len(chunk) * 2,
        )
        for row in resp.get("data") or []:
            if not isinstance(row, dict):
                continue
            canon = row.get("canonical_smiles")
            lid = row.get("id")
            if canon and lid and canon not in by_canonical:
                by_canonical[str(canon)] = row
    return by_canonical


def hydrate_ligand_ids_after_import(
    client: DeepOriginClient,
    ligands: list[Any],
    *,
    compute_job_id: str,
    project_id: str,
    dp_execution_row: dict[str, Any] | None = None,
) -> None:
    """Set ``id`` on in-memory ligands after a workflow import completes."""
    by_canonical: dict[str, dict[str, Any]] = {}
    execution_row_id = (
        _dp_execution_row_id(dp_execution_row) if dp_execution_row else None
    )
    if execution_row_id:
        subject_ids = _ligand_ids_from_execution_subjects(
            client, execution_row_id=execution_row_id
        )
        if subject_ids:
            records = client.entities.get_ligands(ids=subject_ids)  # ty: ignore[unresolved-attribute]
            for row in records:
                if not isinstance(row, dict):
                    continue
                canon = row.get("canonical_smiles")
                if canon:
                    by_canonical[str(canon)] = row

    needed = [
        str(lig.canonical_smiles)
        for lig in ligands
        if getattr(lig, "canonical_smiles", None)
    ]
    missing = [c for c in dict.fromkeys(needed) if c not in by_canonical]
    if missing:
        by_canonical.update(
            _ligand_records_by_canonical_smiles(
                client,
                canonical_smiles=missing,
                project_id=project_id,
            )
        )

    for lig in ligands:
        canon = lig.canonical_smiles
        if canon is None:
            continue
        record = by_canonical.get(str(canon))
        if record is None or not record.get("id"):
            raise DeepOriginException(
                title="Ligand sync failed",
                message=(
                    f"import-dataset did not return a ligand id for canonical_smiles "
                    f"{canon!r}."
                ),
            )
        lig.id = str(record["id"])
        mol_file = record.get("mol_file")
        if mol_file:
            lig.remote_path = str(mol_file)


def workflow_import_smiles_csv(
    *,
    client: DeepOriginClient,
    project_id: str,
    csv_path: str,
    poll_interval: float = _DEFAULT_TOOLS_POLL_INTERVAL_S,
    tools_timeout: float | None = _DEFAULT_TOOLS_WAIT_TIMEOUT_S,
    ingestion_poll_interval: float = _DEFAULT_INGESTION_POLL_INTERVAL_S,
    ingestion_timeout: float | None = _DEFAULT_INGESTION_WAIT_TIMEOUT_S,
) -> tuple[str, dict[str, Any]]:
    """Run large SMILES CSV import via workflow and block until ingestion completes.

    Returns:
        ``(tools_execution_id, data_platform_execution_row)`` from the final
        ingestion poll.
    """
    inputs: dict[str, Any] = {
        "csv_path": csv_path,
        "mapper": LIGANDS_CSV_MAPPER,
        "database_key": IMPORT_DATASET_LIGANDS_DATABASE_KEY,
        "database_version": IMPORT_DATASET_LIGANDS_DATABASE_VERSION,
    }
    dto = run_import_dataset_workflow(
        inputs=inputs,
        project_id=project_id,
        client=client,
    )
    execution_id = dto.get("executionId")
    if not execution_id:
        raise DeepOriginException(
            title="Ligand import failed",
            message="import-dataset workflow did not return an execution id.",
        )
    execution_id = str(execution_id)
    poll_tools_execution_terminal(
        client,
        execution_id,
        poll_interval=poll_interval,
        timeout=tools_timeout,
    )
    dp_row = wait_for_data_platform_ingestion(
        client,
        execution_id,
        poll_interval=ingestion_poll_interval,
        timeout=ingestion_timeout,
    )
    return execution_id, dp_row


def sync_process_pdb(
    *,
    client: DeepOriginClient,
    project_id: str,
    file_path: str,
    extra_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run blocking import-dataset PDB processing and return jobOutputs."""
    inputs: dict[str, Any] = {"process_pdb": True, "file_path": file_path}
    if extra_inputs:
        inputs.update(extra_inputs)
    return job_outputs(
        run_import_dataset_sync(inputs=inputs, project_id=project_id, client=client)
    )


def sync_process_sdf(
    *,
    client: DeepOriginClient,
    project_id: str,
    file_path: str,
    register_poses: bool = False,
    protein_id: str | None = None,
    origin: str = "registered",
    tags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run blocking import-dataset SDF processing and return jobOutputs."""
    inputs: dict[str, Any] = {
        "process_sdf": True,
        "file_path": file_path,
        "register_poses": register_poses,
        "origin": origin,
    }
    if protein_id is not None:
        inputs["protein_id"] = protein_id
    if tags is not None:
        inputs["tags"] = tags
    return job_outputs_with_execution_id(
        run_import_dataset_sync(inputs=inputs, project_id=project_id, client=client)
    )


def sync_process_csv(
    *,
    client: DeepOriginClient,
    project_id: str,
    file_path: str,
) -> dict[str, Any]:
    """Run blocking import-dataset CSV processing and return jobOutputs."""
    inputs = {"process_csv": True, "file_path": file_path}
    return job_outputs(
        run_import_dataset_sync(inputs=inputs, project_id=project_id, client=client)
    )
