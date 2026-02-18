"""Low-level functions for molecular docking using the Deep Origin API.

The main function ``dock()`` takes a Protein object, a list of ligand SMILES strings,
and docking box parameters to perform docking calculations. The docking box can be
specified either by providing explicit coordinates for the pocket center, or by passing
a Pocket object which contains the pocket center information.

Both ``dock()`` and ``constrained_dock()`` return a dict containing:

- ``sdf_path``/``sdf_paths``: path(s) to downloaded SDF result files (None when quoting)
- ``response``: the raw API response dict (always present, contains quotationResult)
"""

import os
from pathlib import Path
from typing import Literal, Optional

from deeporigin.drug_discovery.structures import Ligand, Pocket, Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.core import _ensure_do_folder, hash_dict
from deeporigin.utils.cost import Cost


def _extract_cached_files(extract_dir: str) -> list[str]:
    """Extract and return paths to cached files."""

    extracted_files = []
    for file_path in Path(extract_dir).glob("*"):
        if file_path.is_file():
            extracted_files.append(str(file_path))
    return extracted_files


def _get_pocket_center(
    pocket: Optional[Pocket],
    pocket_center: Optional[tuple[int, int, int]],
) -> list:
    """Extract pocket center coordinates."""
    if pocket_center is None:
        return pocket.get_center().tolist()
    return list(pocket_center)


def dock(
    *,
    client: DeepOriginClient,
    protein: Protein,
    smiles_string: Optional[str] = None,
    ligand: Optional[Ligand] = None,
    box_size: tuple[float, float, float] = (20.0, 20.0, 20.0),
    pocket_center: Optional[tuple[int, int, int]] = None,
    pocket: Optional[Pocket] = None,
    use_cache: bool = True,
    quote: bool = False,
    max_cost: Optional[Cost] = None,
) -> dict:
    """Run molecular docking using the DeepOrigin API.

    Args:
        client: DeepOrigin client instance.
        protein: Protein object representing the target protein.
        smiles_string: SMILES string for the ligand to dock.
        ligand: Ligand object to dock.
        box_size: Size of the docking box (x, y, z).
        pocket_center: Center coordinates of the docking pocket (x, y, z).
        pocket: Pocket object defining the docking region.
        use_cache: Whether to use cached results. Defaults to True.
        quote: Whether to request a price quote without running the docking.
        max_cost: Optional cost limit for the operation.

    Returns:
        Dict with keys:
            - ``sdf_path``: path to the SDF result file, or None when quoting.
            - ``response``: raw API response dict.
    """

    CACHE_DIR = str(_ensure_do_folder() / "docking")

    if pocket is not None or pocket_center is not None:
        pocket_center = _get_pocket_center(pocket, pocket_center)
    else:
        raise DeepOriginException("Pocket center is required") from None

    if ligand is not None:
        smiles_string = ligand.smiles

    if smiles_string is None:
        raise DeepOriginException(
            "Either smiles_string or ligand must be provided"
        ) from None

    payload = {
        "protein_path": protein._remote_path,
        "ligand_smiles": smiles_string,
        "box_size": list(box_size),
        "pocket_center": list(pocket_center),
    }
    cache_hash = hash_dict(payload)
    sdf_file = str(Path(CACHE_DIR) / f"{cache_hash}.sdf")

    if os.path.exists(sdf_file) and use_cache and not quote:
        return {"sdf_path": sdf_file, "response": {}}

    protein.upload(client=client)

    approve_amount = max_cost.approve_amount if max_cost is not None else None

    response = client.functions.run(
        key="deeporigin.docking",
        version="0.2.6",
        params=payload,
        quote=quote,
        approve_amount=approve_amount,
    )

    if quote:
        return {"sdf_path": None, "response": response}

    # TODO -- remove this patch once API is updated
    if "functionOutputs" in response:
        fn_outputs = response["functionOutputs"]
    else:
        fn_outputs = response

    sdf_file = client.files.download_file(
        remote_path=fn_outputs["sdf_path"],
        local_path=sdf_file,
    )

    return {"sdf_path": sdf_file, "response": response}


def constrained_dock(
    *,
    client: DeepOriginClient,
    protein: Protein,
    ligand: Ligand,
    constraints: list[dict],
    pocket: Optional[Pocket] = None,
    box_size: tuple[float, float, float] = (20.0, 20.0, 20.0),
    pocket_center: Optional[tuple[int, int, int]] = None,
    top_criteria: Literal["energy_score", "rmsd"] = "energy_score",
    use_cache: bool = True,
    quote: bool = False,
    max_cost: Optional[Cost] = None,
) -> dict:
    """Perform constrained molecular docking using reference ligand constraints.

    This function performs molecular docking with constraints based on a reference
    ligand and a maximum common substructure (MCS). The ligand is aligned to the
    reference ligand using the MCS, and docking is performed with these alignment
    constraints applied.

    Args:
        client: DeepOrigin client instance.
        protein: The protein structure to dock against.
        ligand: The ligand to be docked.
        constraints: List of constraints for the docking. Generate this using
            ``align.compute_constraints``.
        pocket: Optional pocket object. If provided, its center will be used
            as pocket_center.
        box_size: Size of the docking box in Angstroms (x, y, z).
        pocket_center: Optional center coordinates for the docking box.
        top_criteria: Criteria for selecting top poses.
        use_cache: Whether to use cached results if available.
        quote: Whether to request a price quote without running the docking.
        max_cost: Optional cost limit for the operation.

    Returns:
        Dict with keys:
            - ``sdf_paths``: list of paths to result SDF files, or None when quoting.
            - ``response``: raw API response dict.

    Note:
        The function creates a cache directory in the DeepOrigin home directory
        (typically ~/.deeporigin/constrained_docking/) and stores results based on
        a SHA256 hash of all input parameters.
    """
    CACHE_DIR = str(_ensure_do_folder() / "constrained_docking")

    if pocket is None and pocket_center is None:
        raise DeepOriginException(
            "Either pocket or pocket_center must be provided"
        ) from None

    pocket_center_list = _get_pocket_center(pocket, pocket_center)

    protein.upload(client=client)
    ligand.upload(client=client)

    payload = {
        "protein_path": protein._remote_path,
        "ligand_path": ligand._remote_path,
        "box_size": list(box_size),
        "constraints": constraints,
        "protein": {"pocket_center": pocket_center_list},
        "top_criteria": top_criteria,
    }

    cache_hash = hash_dict(payload)
    extract_dir = str(Path(CACHE_DIR) / cache_hash)

    if os.path.exists(extract_dir) and use_cache and not quote:
        return {"sdf_paths": _extract_cached_files(extract_dir), "response": {}}

    approve_amount = max_cost.approve_amount if max_cost is not None else None

    response = client.functions.run(
        key="deeporigin.constrained-docking",
        params=payload,
        quote=quote,
        approve_amount=approve_amount,
    )

    if quote:
        return {"sdf_paths": None, "response": response}

    # TODO -- remove this patch once API is updated
    if "functionOutputs" in response:
        fn_outputs = response["functionOutputs"]
    else:
        fn_outputs = response

    Path(extract_dir).mkdir(parents=True, exist_ok=True)
    downloaded_files = []

    output_files = fn_outputs.get("output_files", {})
    for filename, remote_path in output_files.items():
        local_path = str(Path(extract_dir) / filename)
        client.files.download_file(
            remote_path=remote_path,
            local_path=local_path,
        )
        downloaded_files.append(local_path)

    return {"sdf_paths": downloaded_files, "response": response}
