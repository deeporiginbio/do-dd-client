"""Utility functions for the Drug Discovery module"""

import importlib.resources
import json
import os
from typing import Any

from beartype import beartype

from deeporigin.drug_discovery.constants import tool_mapper, valid_tools
from deeporigin.drug_discovery.utils.visualize import (
    render_smiles_in_dataframe,  # noqa: F401
)
from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.env import _ensure_do_folder

DATA_DIRS = {}

for tool in tool_mapper.keys():
    DATA_DIRS[tool] = str(_ensure_do_folder() / tool)
    os.makedirs(DATA_DIRS[tool], exist_ok=True)


@beartype
def _load_params(param_file: str) -> dict:
    """load params for various tools, reading from JSON files"""

    with importlib.resources.open_text("deeporigin.json", f"{param_file}.json") as f:
        return json.load(f)


@beartype
def _start_tool_run(
    *,
    params: dict,
    metadata: dict,
    tool: valid_tools,
    tool_version: str,
    client: DeepOriginClient,
    outputs: dict | None = None,
    approve_amount: int | None = None,
    name: str | None = None,
) -> dict:
    """Submit a tool execution to the platform.

    Args:
        params: Input parameters for the tool run.
        metadata: Metadata to log with the execution.
        tool: Tool identifier (e.g., ``'ABFE'``, ``'Docking'``).
        tool_version: Version of the tool to use.
        client: API client.
        outputs: Output file specification. Defaults to empty.
        approve_amount: Pre-approved spend amount.
        name: Optional execution label.

    Returns:
        The execution DTO from the API.
    """
    if is_test_run(params):
        print(
            "⚠️ Warning: test_run=1 in these parameters. Results and quoted prices will not be accurate."
        )

    payload = {
        "inputs": params,
        "outputs": outputs or {},
        "metadata": metadata,
    }

    if approve_amount is not None:
        payload["approveAmount"] = approve_amount

    if name is not None:
        payload["name"] = name

    proj_id = client.project_id
    if proj_id is not None:
        payload["projectId"] = proj_id

    response = client.executions.create(
        data=payload,
        tool_key=tool_mapper[tool],
        tool_version=tool_version,
    )

    return response


@beartype
def is_test_run(data: Any) -> bool:
    """check if test_run=1 in a dict"""

    if isinstance(data, dict):
        if data.get("test_run") == 1:
            return True
        for value in data.values():
            if is_test_run(value):
                return True
    elif isinstance(data, list):
        for item in data:
            if is_test_run(item):
                return True
    return False


@beartype
def _set_test_run(data, value: int = 1) -> None:
    """recursively iterate over a dict and set test_run=1 for all keys"""

    if isinstance(data, dict):
        for key, val in data.items():
            if key == "test_run":
                data[key] = value
            else:
                _set_test_run(val, value)
    elif isinstance(data, list):
        for item in data:
            _set_test_run(item, value)
