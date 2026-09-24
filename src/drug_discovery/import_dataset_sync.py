"""Hidden blocking import-dataset executions for entity .sync()."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import uuid

from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS


def run_import_dataset_sync(
    *,
    inputs: dict[str, Any],
    project_id: str,
    client: Optional[DeepOriginClient] = None,
) -> dict[str, Any]:
    """Run a blocking served import-dataset execution and return the execution DTO."""
    if client is None:
        client = DeepOriginClient()
    proj = str(project_id).strip()
    if not proj:
        raise DeepOriginException(
            title="Project required",
            message="import-dataset file processing requires project_id on the execution.",
        )
    tool_meta = TOOL_KEYS_AND_VERSIONS["import_dataset"]
    raw = client.executions.create(  # ty: ignore[unresolved-attribute]
        tool_key=tool_meta["tool_key"],
        tool_version=tool_meta["tool_version"],
        data={
            "inputs": inputs,
            "outputs": {},
            "metadata": {},
            "sync": True,
            "projectId": proj,
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
    """Resolve and validate project scope for entity sync."""
    proj = entity_project_id
    if proj is None or not str(proj).strip():
        proj = client.project_id
    if proj is None or not str(proj).strip():
        raise DeepOriginException(
            title="Project required",
            message="sync requires entity.project_id or client.project_id.",
        )
    return str(proj).strip()


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
