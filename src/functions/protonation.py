"""This module contains functions to protonate molecules using DeepOrigin Functions."""

import json
import os
from pathlib import Path

from beartype import beartype
import httpx

from deeporigin.utils.constants import number
from deeporigin.utils.core import _ensure_do_folder, hash_dict

URL = "http://molprops.default.jobs.edge.deeporigin.io/protonation"
CACHE_DIR = str(_ensure_do_folder() / "protonation")

# Ensure cache directory exists
os.makedirs(CACHE_DIR, exist_ok=True)


@beartype
def protonate(
    *,
    smiles: str,
    ph: number = 7.4,
    filter_percentage: number = 1.0,
    use_cache: bool = True,
) -> dict:
    """
    Run ligand protonation using the DeepOrigin API.

    Args:
        smiles (str): SMILES string for the molecule
        ph (number): pH value
        filter_percentage (number): Percentage of the most abundant species to retain
        use_cache (bool): Whether to use the cache

    Returns:
        dict: Dictionary containing the protonation states of the molecule
    """

    payload = {
        "smiles": smiles,
        "pH": ph,
        "filter_percentage": float(filter_percentage),
    }

    # Create hash of inputs
    cache_hash = hash_dict(payload)
    response_file = str(Path(CACHE_DIR) / f"{cache_hash}.json")

    # Check if cached result exists
    if os.path.exists(response_file) and use_cache:
        # Read cached response
        with open(response_file, "r") as file:
            response = json.load(file)

    else:
        # Make the API request
        response = httpx.post(
            URL,
            json=payload,
            headers={"Content-Type": "application/json"},
        )

        # Raise an exception for bad status codes
        response.raise_for_status()

        response = response.json()

        # check response pH
        if response["pH"] != ph:
            raise ValueError(
                f"Protonation failed. Expected pH {ph}, got {response['pH']}"
            )
        # Write JSON response to cache
        with open(response_file, "w") as file:
            json.dump(response, file)

    return response
