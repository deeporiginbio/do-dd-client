"""Utility functions for the Drug Discovery module"""

import importlib.resources
import json
import os
from typing import Any, Optional

from beartype import beartype

from deeporigin.drug_discovery.constants import tool_mapper, valid_tools
from deeporigin.drug_discovery.utils.visualize import (
    render_smiles_in_dataframe,  # noqa: F401
)
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import PROVIDER
from deeporigin.utils.core import _ensure_do_folder

PROVIDER_KEY = "$provider"
RESULTS_CSV = "results.csv"

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
    output_dir_path: str,
    tool_version: str,
    provider: PROVIDER = "ufa",
    client: Optional[DeepOriginClient] = None,
    approve_amount: Optional[int] = None,
) -> dict:
    """
    Starts a single run of an end-to-end tool (such as ABFE) and logs it in the ABFE database.

    This is an internal function that prepares input and output file parameters, sets up the job metadata,
    and submits the job to the platform's tools API. Only ABFE is currently supported.

    Args:
        params (dict): Parameters for the tool run, including input and configuration options.
        metadata (dict): Metadata to be logged with the job.
        protein_path (str): Remote path to the protein file to be used in the run.
        ligand1_path (str): Remnote path to the first ligand file.
        ligand2_path (Optional[str]): Remote path to the second ligand file (required for RBFE).
        tool (valid_tools): The tool to run (e.g., 'ABFE', 'RBFE').
        tool_version (str): Version of the tool to use.
        provider (tools_api.PROVIDER, optional): File provider for input/output files. Defaults to 'ufa'.
        client (Client): Client to use for the job.
        _output_dir_path (Optional[str]): Custom output directory path (on remote storage). If None, a default is constructed.

    Returns:
        dict: The full execution description (DTO) from the API, containing executionId, status, and other fields.

    Raises:
        NotImplementedError: If a tool other than ABFE is specified.
    """

    # output files
    if tool == "RBFE":
        raise NotImplementedError("RBFE is not implemented yet")
    elif tool == "ABFE":
        outputs = {
            "output_file": {
                PROVIDER_KEY: provider,
                "key": output_dir_path + "output/",
            },
            "abfe_results_summary": {
                PROVIDER_KEY: provider,
                "key": output_dir_path + RESULTS_CSV,
            },
        }
    elif tool == "Docking":
        outputs = {}

    if is_test_run(params):
        print(
            "⚠️ Warning: test_run=1 in these parameters. Results and quoted prices will not be accurate."
        )

    payload = {
        "inputs": params,
        "outputs": outputs,
        "metadata": metadata,
    }

    if approve_amount is not None:
        payload["approveAmount"] = approve_amount

    response = client.tools.run(
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
