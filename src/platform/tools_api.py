"""bridge module to interact with the platform tools api"""

import concurrent.futures
import functools
import sys
from typing import Literal, Optional

from beartype import beartype

from deeporigin.platform.utils import _add_functions_to_module

__all__ = _add_functions_to_module(
    module=sys.modules[__name__],
    api_name="ToolsApi",
)


TERMINAL_STATES = {
    "Succeeded",
    "Failed",
    "Cancelled",
    "Quoted",
    "InsufficientFunds",
    "FailedQuotation",
}
NON_TERMINAL_STATES = {"Created", "Queued", "Running"}

NON_FAILED_STATES = {"Succeeded", "Running", "Queued", "Created"}

# possible providers for files that work with the tools API
PROVIDER = Literal["ufa", "s3"]


@functools.lru_cache
def get_default_cluster_id(
    *,
    client=None,
    org_key: Optional[str] = None,
) -> str:
    """get the default cluster id for a client

    We default to using the first cluster that does not have "dev" in the hostname.
    """
    clusters = list_clusters(client=client, org_key=org_key)  # noqa: F821
    # Filter out clusters with hostnames containing "dev"
    filtered_clusters = [
        cluster for cluster in clusters if "dev" not in cluster.hostname
    ]
    if len(filtered_clusters) == 0:
        raise RuntimeError("No clusters found (excluding dev clusters).")
    cluster_id = filtered_clusters[0].id
    return cluster_id


@beartype
def get_statuses_and_progress(
    job_ids: list[str],
    *,
    client=None,
    org_key: Optional[str] = None,
) -> list:
    """get statuses and progress reports for multiple jobs in parallel

    Args:
        job_ids (list[str]): list of job IDs

    """
    results = []
    errors = []

    with concurrent.futures.ThreadPoolExecutor() as executor:
        # Submit all jobs and create a mapping from future to job_id
        future_to_job_id = {
            executor.submit(
                get_tool_execution,  # noqa: F821
                execution_id=job_id,
                client=client,
                org_key=org_key,
            ): job_id
            for job_id in job_ids
        }

        # As each future completes, store the result in the status dictionary
        for future in concurrent.futures.as_completed(future_to_job_id):
            job_id = future_to_job_id[future]
            try:
                results.append(future.result())
            except Exception as e:
                errors.append((job_id, e))

    if errors:
        error_msgs = "\n".join([f"Job {jid}: {str(err)}" for jid, err in errors])
        raise RuntimeError(
            f"Some jobs failed in get_status_and_progress:\n{error_msgs}"
        )

    return results


@beartype
def cancel(
    execution_id: str,
    *,
    client=None,
    org_key: Optional[str] = None,
) -> None:
    """cancel a run

    Args:
        execution_id (str): execution ID
    """

    data = get_tool_execution(  # noqa: F821
        execution_id=execution_id,
        client=client,
        org_key=org_key,
    )
    if data["status"] in TERMINAL_STATES:
        return

    action_tool_execution(  # noqa: F821
        execution_id=execution_id,
        action="cancel",
        client=client,
        org_key=org_key,
    )


@beartype
def confirm(
    execution_id: str,
    *,
    client=None,
    org_key: Optional[str] = None,
) -> None:
    """cancel a run

    Args:
        execution_id (str): execution ID
    """

    action_tool_execution(  # noqa: F821
        execution_id=execution_id,
        action="confirm",
        client=client,
        org_key=org_key,
    )


@beartype
def query_run_statuses(
    job_ids: list[str],
    *,
    client=None,
    org_key: Optional[str] = None,
) -> dict:
    """get statuses for multiple jobs in parallel

    Args:
        job_ids (list[str]): list of job IDs

    """
    status = {}

    with concurrent.futures.ThreadPoolExecutor() as executor:
        # Submit all jobs and create a mapping from future to job_id
        future_to_job_id = {
            executor.submit(
                query_run_status,
                job_id,
                client=client,
                org_key=org_key,
            ): job_id
            for job_id in job_ids
        }

        # As each future completes, store the result in the status dictionary
        for future in concurrent.futures.as_completed(future_to_job_id):
            job_id = future_to_job_id[future]
            try:
                status[job_id] = future.result()
            except Exception:
                status[job_id] = None

    return status


@beartype
def query_run_status(
    execution_id: str,
    *,
    client=None,
    org_key: Optional[str] = None,
) -> str:
    """Determine the status of a run, identified by execution_id ID

    Args:
        execution_id (str): execution_id ID

    Returns:
        One of "Created", "Queued", "Running", "Succeeded", or "Failed"

    """

    data = get_tool_execution(  # noqa: F821
        execution_id=execution_id,
        client=client,
        org_key=org_key,
    )

    return data.attributes.status


@beartype
def run_tool(
    *,
    data: dict,
    tool_key: str,
    tool_version: str,
    client=None,
    org_key: Optional[str] = None,
):
    """run any tool using provided data transfer object (DTO)

    Args:
        data (dict): data transfer object. This is typically generated by the `make_payload` function.
        tool_key (str): key of the tool to run
        client (Client): client to use to run the tool
        org_key (str): key of the organization to use to run the tool. If not provided, the org_key will be inferred from the client or the environment variable DEEPORIGIN_ORG_KEY, or the value in the config file.
    """

    if "clusterId" not in data.keys():
        data["clusterId"] = get_default_cluster_id(client=client, org_key=org_key)

    if "approveAmount" not in data.keys():
        data["approveAmount"] = 0

    try:
        response = execute_tool_with_version(  # noqa: F821
            tool_key=tool_key,
            execute_tool_schema_dto=data,
            tool_version=tool_version,
            client=client,
            org_key=org_key,
        )
    except Exception as e:
        print(f"Error running tool: {e}")
        import json

        print(f"Data: {json.dumps(data, indent=4)}")
        raise e

    return response
