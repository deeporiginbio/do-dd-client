"""this module implements a low level function to find pockets in a protein determined by a PDB file"""

import json
import os
from typing import Any

from deeporigin.drug_discovery.structures import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.core import _ensure_do_folder, hash_dict

CACHE_DIR = str(_ensure_do_folder() / "pocket-finder")
CACHE_FILE = "pockets.json"


# @beartype
def find_pockets(
    *,
    protein: Protein,
    pocket_count: int = 5,
    pocket_min_size: int = 30,
    use_cache: bool = True,
    client: DeepOriginClient,
    quote: bool = False,
) -> list[dict[str, Any]]:
    """Find protein binding pockets in a PDB structure and return pocket data.

    This function sends a PDB file to a remote server for pocket detection,
    downloads the resulting PDB files locally, and returns the pocket metadata
    with ``file_path`` values updated to point to the local files.

    Results are cached on disk; subsequent calls with the same inputs return
    the cached data without re-running the remote function.

    Args:
        protein (Protein): protein to find pockets in
        pocket_count (int, optional): Maximum number of pockets to detect. Defaults to 5.
        pocket_min_size (int, optional): Minimum size of pockets to consider. Defaults to 30.
        use_cache (bool, optional): Whether to use cached results. Defaults to True.
        client (DeepOriginClient): authenticated Deep Origin client.
        quote (bool, optional): Whether to quote the function call. Defaults to False.

    Returns:
        list[dict[str, Any]]: List of pocket dicts with local ``file_path`` values,
            suitable for passing directly to ``Pocket.from_json``.
    """

    if pocket_count < 1:
        raise ValueError("pocket_count must be at least 1") from None
    if pocket_min_size < 1:
        raise ValueError("pocket_min_size must be at least 1") from None

    # ensure the protein is synced to the data platform
    protein.sync(lazy=True, client=client)

    # Prepare the request payload
    payload = {
        "protein": {"file_path": protein._remote_path},
        "pocket_count": pocket_count,
        "pocket_min_size": pocket_min_size,
    }

    cache_key = hash_dict(payload)

    # add protein ID after hashing so it doesn't affect the cache key
    payload["protein"]["id"] = protein.id
    cache_path = os.path.join(CACHE_DIR, cache_key)
    cache_file = os.path.join(cache_path, CACHE_FILE)

    if use_cache and os.path.exists(cache_file):
        with open(cache_file) as f:
            return json.load(f)

    protein.upload(client=client)
    os.makedirs(cache_path, exist_ok=True)

    response = client.functions.run(
        key="deeporigin.pocketfinder",
        version="0.3.0",
        params=payload,
        quote=quote,
    )

    try:
        pockets = response["functionOutputs"]["pockets"]
    except KeyError:
        raise DeepOriginException(
            "Pocket finder returned an unexpected response. Expected 'pockets' key in response['functionOutputs']"
        ) from None

    for pocket in pockets:
        remote_path = pocket["file_path"]
        local_path = os.path.join(cache_path, remote_path.split("/")[-1])
        client.files.download_file(
            remote_path=remote_path,
            local_path=local_path,
        )
        pocket["file_path"] = local_path

    with open(cache_file, "w") as f:
        json.dump(pockets, f, indent=2)

    return pockets
