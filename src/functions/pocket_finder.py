"""Low-level function to find pockets in a protein determined by a PDB file."""

import os
from typing import Optional

from deeporigin.drug_discovery.structures import Protein
from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.core import _ensure_do_folder, hash_dict
from deeporigin.utils.cost import Cost

CACHE_DIR = str(_ensure_do_folder() / "pocket-finder")


def find_pockets(
    *,
    protein: Protein,
    pocket_count: int = 5,
    pocket_min_size: int = 30,
    use_cache: bool = True,
    client: DeepOriginClient,
    quote: bool = False,
    max_cost: Optional[Cost] = None,
) -> dict:
    """Find protein binding pockets in a PDB structure and save the results.

    Args:
        protein: Protein to find pockets in.
        pocket_count: Maximum number of pockets to detect. Defaults to 5.
        pocket_min_size: Minimum size of pockets to consider. Defaults to 30.
        use_cache: Whether to use cached results if available.
        client: DeepOrigin client instance.
        quote: Whether to request a price quote without running.
        max_cost: Optional cost limit for the operation.

    Returns:
        Dict with keys:
            - ``results_dir``: path to the results cache directory, or None when quoting.
            - ``response``: raw API response dict.
    """

    if pocket_count < 1:
        raise ValueError("pocket_count must be at least 1") from None
    if pocket_min_size < 1:
        raise ValueError("pocket_min_size must be at least 1") from None

    payload = {
        "protein_path": protein._remote_path,
        "pocket_count": pocket_count,
        "pocket_min_size": pocket_min_size,
    }

    cache_key = hash_dict(payload)
    cache_path = os.path.join(CACHE_DIR, cache_key)

    if use_cache and os.path.exists(cache_path) and not quote:
        return {"results_dir": cache_path, "response": {}}

    protein.upload(client=client)

    approve_amount = max_cost.approve_amount if max_cost is not None else None

    response = client.functions.run(
        key="deeporigin.pocketfinder",
        version="0.2.2",
        params=payload,
        quote=quote,
        approve_amount=approve_amount,
    )

    if quote:
        return {"results_dir": None, "response": response}

    # TODO -- remove this patch once API is updated
    if "functionOutputs" in response:
        fn_outputs = response["functionOutputs"]
    else:
        fn_outputs = response

    os.makedirs(cache_path, exist_ok=True)

    for file in fn_outputs["files"]:
        client.files.download_file(
            remote_path=file,
            local_path=os.path.join(cache_path, file.split("/")[-1]),
        )

    return {"results_dir": cache_path, "response": response}
