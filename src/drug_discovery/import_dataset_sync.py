"""Hidden blocking import-dataset executions for entity .sync()."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

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


def require_project_id(
    *,
    entity_project_id: str | None,
    client: DeepOriginClient,
    entity_label: str,
) -> str:
    """Resolve and validate project scope for entity sync."""
    proj = entity_project_id
    if proj is None or not str(proj).strip():
        proj = client.project_id
    if proj is None or not str(proj).strip():
        raise DeepOriginException(
            title=f"Project required for {entity_label} sync",
            message=(
                f"{entity_label}.sync requires entity.project_id or client.project_id."
            ),
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
    return job_outputs(
        run_import_dataset_sync(inputs=inputs, project_id=project_id, client=client)
    )


def sync_process_csv(
    *,
    client: DeepOriginClient,
    project_id: str,
    file_path: str,
) -> dict[str, Any]:
    inputs = {"process_csv": True, "file_path": file_path}
    return job_outputs(
        run_import_dataset_sync(inputs=inputs, project_id=project_id, client=client)
    )
