"""This module contains functions to protonate molecules using DeepOrigin Functions."""

import json
import os
from pathlib import Path

from beartype import beartype

from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.constants import number
from deeporigin.utils.core import _ensure_do_folder, hash_dict

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
    client: DeepOriginClient,
    quote: bool = False,
) -> dict:
    """
    Run ligand protonation using the DeepOrigin API.

    Args:
        smiles (str): SMILES string for the molecule
        ph (number): pH value
        filter_percentage (number): Percentage of the most abundant species to retain
        use_cache (bool): Whether to use the cache
        client (DeepOriginClient): DeepOrigin client instance
        quote (bool): Whether to request a quote instead of running the function

    Returns:
        dict: Dictionary containing the protonation states of the molecules
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
        # Make the API request using client.functions.run()
        response = client.functions.run(
            key="deeporigin.mol-props-protonation",
            params=payload,
            quote=quote,
        )

        print(json.dumps(response, indent=4))

        # TODO -- remove this patch once API is updated
        if "functionOutputs" in response:
            response = response["functionOutputs"]

        # check response pH
        if response["pH"] != ph:
            raise ValueError(
                f"Protonation failed. Expected pH {ph}, got {response['pH']}"
            )
        # Write JSON response to cache
        # Ensure parent directory exists before writing
        Path(response_file).parent.mkdir(parents=True, exist_ok=True)
        with open(response_file, "w") as file:
            json.dump(response, file)

    return response
