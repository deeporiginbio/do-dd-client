"""This module contains functions to help with RBFE like network mapping and visualization."""

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin

from beartype import beartype
import httpx

from deeporigin.utils.core import _ensure_do_folder

URL = "http://rbfe-tools.default.jobs.edge.deeporigin.io"
CACHE_DIR = str(_ensure_do_folder() / "konnektor")


@beartype
def map_network(
    *,
    sdf_file: str,
    operation: Literal["mapping", "network", "full"] = "network",
    network_type: Literal["star", "mst", "cyclic"] = "mst",
    use_cache: bool = True,
) -> dict:
    """
    Map a network of ligands from an SDF file using the DeepOrigin API.

    Args:
        sdf_file (str): Path to the SDF file containing ligands.
        operation (Literal["mapping", "network", "full"]): Type of operation to perform. Defaults to "network".
        network_type (Literal["star", "mst", "cyclic"]): Type of network to generate. Defaults to "mst".
        use_cache (bool): Whether to use cached results if available. Defaults to True.

    Returns:
        dict: The result of the network mapping operation.
    """

    # Create hash of inputs
    hasher = hashlib.sha256()

    # Read and encode the ligand file
    with open(sdf_file, "rb") as f:
        encoded_file = base64.b64encode(f.read()).decode("utf-8")

    # Prepare the request payload
    payload = {
        "operation": operation,
        "file_b64": encoded_file,
        "network_type": network_type,
    }

    # Hash inputs
    hasher.update(json.dumps(payload).encode())

    cache_hash = hasher.hexdigest()
    results_json = str(Path(CACHE_DIR) / f"{cache_hash}.json")

    # Check if cached result exists
    if os.path.exists(results_json) and use_cache:
        with open(results_json, "r") as f:
            response = json.load(f)

    else:
        # Make the API request
        response = httpx.post(
            urljoin(URL, "konnektor"),
            json=payload,
            headers={"Content-Type": "application/json"},
        )

        # Raise an exception for bad status codes
        response.raise_for_status()

        response = response.json()

        # Write SDF file to cache
        Path(results_json).parent.mkdir(parents=True, exist_ok=True)
        with open(results_json, "w") as f:
            json.dump(response, f)

    return response
