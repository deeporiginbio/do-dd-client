"""Low-level function to protonate molecules using DeepOrigin Functions."""

import json
import os
from pathlib import Path

from beartype import beartype

from deeporigin.functions.result import FunctionResult
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import PROTONATION_FUNCTION_KEY
from deeporigin.utils.constants import number
from deeporigin.utils.env import _ensure_do_folder
from deeporigin.utils.hashing import hash_dict

CACHE_DIR = str(_ensure_do_folder() / "protonation")

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
) -> FunctionResult:
    """Run ligand protonation using the DeepOrigin API.

    Args:
        smiles: SMILES string for the molecule.
        ph: pH value.
        filter_percentage: Percentage of the most abundant species to retain.
        use_cache: Whether to use the cache.
        client: DeepOrigin client instance.
        quote: If True, request a cost estimate without executing.

    Returns:
        FunctionResult wrapping the full API response.
    """

    payload = {
        "smiles": smiles,
        "pH": ph,
        "filter_percentage": float(filter_percentage),
    }

    cache_hash = hash_dict(payload)
    response_file = str(Path(CACHE_DIR) / f"{cache_hash}.json")

    if os.path.exists(response_file) and use_cache and not quote:
        with open(response_file, "r") as file:
            response = json.load(file)

        if "functionOutputs" not in response:
            response = {"functionOutputs": response, "status": "Completed"}
    else:
        response = client.functions.run(
            key=PROTONATION_FUNCTION_KEY,
            params=payload,
            quote=quote,
        )

        if not quote:
            outputs = response.get("functionOutputs", {})
            if outputs.get("pH") != ph:
                raise ValueError(
                    f"Protonation failed. Expected pH {ph}, got {outputs.get('pH')}"
                )

            Path(response_file).parent.mkdir(parents=True, exist_ok=True)
            with open(response_file, "w") as file:
                json.dump(response, file)

    return FunctionResult([response])
