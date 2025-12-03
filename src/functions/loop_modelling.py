"""This module contains the function to run loop modelling on a protein identified by a PDB ID."""

import os

from deeporigin.utils.core import _ensure_do_folder, hash_dict

URL = "http://loop-modelling.default.jobs.edge.deeporigin.io/model_loops"
CACHE_DIR = str(_ensure_do_folder() / "model_loops")


def model_loops(
    *,
    pdb_id: str,
    use_cache: bool = True,
) -> str:
    """
    Run system preparation on a protein-ligand complex.

    Args:
        pdb_id: PDB ID of the protein to model loops for.

    Returns:
        Path to the output PDB file if successful, or raises RuntimeError if the server fails.
    """

    # If no cached results, proceed with server call
    payload = {
        "pdb_id": pdb_id,
    }

    cache_hash = hash_dict(payload)
    cache_path = os.path.join(CACHE_DIR, cache_hash)
    output_pdb_path = os.path.join(cache_path, "loops_modelled.pdb")

    # Check if cached results exist
    if use_cache and os.path.exists(output_pdb_path):
        return output_pdb_path

    from deeporigin.platform import tools_api

    body = {"params": payload, "clusterId": tools_api.get_default_cluster_id()}

    response = tools_api.run_function(
        key="deeporigin.loop-modelling",
        version="0.1.0",
        function_execution_params_schema_dto=body,
    )

    # Create cache directory if it doesn't exist
    os.makedirs(cache_path, exist_ok=True)
    # Save the result to the cache

    if response.status >= 200 and response.status < 300:
        with open(output_pdb_path, "wb") as f:
            f.write(response.data)
            return output_pdb_path

    else:
        # If the server request fails, raise an error
        raise RuntimeError(
            f"Server returned status code {response.status}: {response.text}"
        ) from None
