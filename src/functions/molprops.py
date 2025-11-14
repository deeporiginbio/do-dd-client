"""This module implements a low level function to perform molecular property predictions
using the DeepOrigin API.
"""

from collections import defaultdict
from copy import deepcopy
import json
import os
from pathlib import Path
from typing import Optional

from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.core import hash_dict

CACHE_DIR = os.path.expanduser("~/.deeporigin/molprops")

# Ensure cache directory exists
os.makedirs(CACHE_DIR, exist_ok=True)


def molprops(
    smiles_list: list[str],
    properties: Optional[set[str]] = None,
    *,
    client: DeepOriginClient,
    use_cache: bool = True,
) -> dict:
    """
    Run molecular property prediction using the DeepOrigin API.

    Args:
        smiles_string (str): SMILES string for the molecule
        use_cache (bool): Whether to use the cache

    Returns:
        str: Path to the cached SDF file containing the results
    """

    if properties is None:
        properties = {"logp", "logd", "logs", "ames", "pains", "herg", "cyp"}

    payload = {
        "smiles_list": smiles_list,
    }

    # Create hash of inputs
    response = []
    for prop in properties:
        this_response = get_single_property(
            payload=payload,
            prop=prop,
            use_cache=use_cache,
            client=client,
        )

        response.append(this_response)

    # Merge based on smiles
    response = merge_dict_lists(response)
    return response


def get_single_property(
    *,
    payload: dict,
    prop: str,
    client: DeepOriginClient,
    use_cache: bool = True,
) -> dict:
    """
    Get a single property for a molecule using the DeepOrigin API.
    """
    cache_hash = hash_dict({"property": prop, **payload})
    response_file = str(Path(CACHE_DIR) / f"{cache_hash}.json")

    # Check if cached result exists
    if os.path.exists(response_file) and use_cache:
        # Read cached response
        with open(response_file, "r") as file:
            response = json.load(file)

        return response

    # Prepare the request payload

    response = client.functions.run(
        key=f"deeporigin.mol-props-{prop}",
        version="0.1.3",
        params=payload,
    )

    # Write JSON response to cache
    # Ensure parent directory exists before writing
    Path(response_file).parent.mkdir(parents=True, exist_ok=True)
    with open(response_file, "w") as file:
        json.dump(response, file)

    return response


def merge_dict_lists(dict_lists, key="smiles"):
    """
    Merge N lists of dicts by a common key.

    Args:
        dict_lists: iterable of lists of dicts
        key: key to merge on (default: 'smiles')

    Returns:
        List of merged dicts, one per unique key value.
    """
    merged = defaultdict(dict)
    for lst in dict_lists:
        for d in lst:
            k = d[key]
            merged[k].update(d)  # merge keys into single dict
    # preserve insertion order of first list
    if dict_lists:
        order = [d[key] for d in dict_lists[0]]
        seen = set()
        result = []
        for k in order + [k for k in merged if k not in order]:
            if k not in seen:
                result.append(deepcopy(merged[k]))
                seen.add(k)
        return result
    return []
