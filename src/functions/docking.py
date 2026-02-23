"""This module implements a low level function to perform molecular docking using the Deep Origin API.

The main function `dock()` takes a Protein object, a list of ligand SMILES strings, and docking box parameters
to perform docking calculations. The docking box can be specified either by providing explicit coordinates for the
pocket center, or by passing a Pocket object which contains the pocket center information.

The module interfaces with the Deep Origin docking service to perform the actual docking calculations remotely.
"""

import os
from pathlib import Path
from typing import Literal, Optional

from deeporigin.drug_discovery.structures import Ligand, Pocket, Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.functions.result import FunctionResult
from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.core import _ensure_do_folder, hash_dict


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
    ligand: Ligand,
    box_size: tuple[float, float, float] = (20.0, 20.0, 20.0),
    pocket_center: Optional[tuple[int, int, int]] = None,
    pocket: Optional[Pocket] = None,
    quote: bool = False,
) -> FunctionResult:
    """Run molecular docking using the DeepOrigin API.

    Args:
        client: DeepOrigin client instance.
        protein: Protein object representing the target protein.
        ligand: Ligand object to dock.
        box_size: Size of the docking box (x, y, z).
        pocket_center: Center coordinates of the docking pocket (x, y, z).
        pocket: Pocket object defining the docking region.
        quote: If True, request a cost estimate without executing.

    Returns:
        FunctionResult wrapping the full API response.
    """

    protein.sync(lazy=True, client=client)
    ligand.sync(lazy=True, client=client)

    if pocket is not None or pocket_center is not None:
        pocket_center = _get_pocket_center(pocket, pocket_center)
    else:
        raise DeepOriginException("Pocket center is required") from None

    protein_data = {
        "id": protein.id,
        "file_path": protein._remote_path,
    }

    ligand_data = {
        "id": ligand.id,
        "smiles": ligand.smiles,
    }

    payload = {
        "protein": protein_data,
        "ligand": ligand_data,
        "pocket_center": list(pocket_center),
        "box_size": list(box_size),
    }
    if pocket is not None and pocket.name is not None:
        payload["pocket_id"] = pocket.name

    response = client.functions.run(
        key="deeporigin.docking",
        version="0.4.0",
        params=payload,
        quote=quote,
    )

    return FunctionResult([response])


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
) -> list[str]:
    """Perform constrained molecular docking using a reference ligand constraints.

    This function performs molecular docking with constraints based on a reference ligand
    and a maximum common substructure (MCS). The ligand is aligned to the reference ligand
    using the MCS, and docking is performed with these alignment constraints applied.

    Args:
        client (DeepOriginClient): DeepOrigin client instance.
        protein (Protein): The protein structure to dock against.
        ligand (Ligand): The ligand to be docked.
        constraints (list[dict]): List of constraints for the docking. Generate this using `align.compute_constraints`.
        pocket (Optional[Pocket]): Optional pocket object. If provided, its center will be used as pocket_center.
        box_size (tuple[float, float, float]): Size of the docking box in Angstroms (x, y, z). Defaults to (20.0, 20.0, 20.0).
        pocket_center (Optional[tuple[int, int, int]]): Optional center coordinates for the docking box. If None and pocket is provided,
                     uses the pocket center. If both are None, raises an error.
        top_criteria (Literal["energy_score", "rmsd"]): Criteria for selecting top poses. Defaults to "energy_score".
        use_cache (bool): Whether to use cached results if available. Defaults to True.
        quote (bool): Whether to quote the function run without executing it. Defaults to False.

    Returns:
        list[str]: List of file paths to the docking result files (typically SDF files).


    Note:
        The function creates a cache directory in the DeepOrigin home directory
        (typically ~/.deeporigin/constrained_docking/) and stores results based on
        a SHA256 hash of all input parameters. This allows for efficient reuse of
        previous docking results.
    """
    CACHE_DIR = str(_ensure_do_folder() / "constrained_docking")

    if pocket is None and pocket_center is None:
        raise DeepOriginException(
            "Either pocket or pocket_center must be provided"
        ) from None

    pocket_center_list = _get_pocket_center(pocket, pocket_center)

    # Upload files first
    protein.upload(client=client)
    ligand.upload(client=client)

    # Prepare the request payload
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

    if os.path.exists(extract_dir) and use_cache:
        return _extract_cached_files(extract_dir)

    response = client.functions.run(
        key="deeporigin.constrained-docking",
        params=payload,
        quote=quote,
    )

    response = response["functionOutputs"]

    # Download individual files from output_files
    Path(extract_dir).mkdir(parents=True, exist_ok=True)
    downloaded_files = []

    output_files = response.get("output_files", {})
    for filename, remote_path in output_files.items():
        local_path = str(Path(extract_dir) / filename)
        client.files.download_file(
            remote_path=remote_path,
            local_path=local_path,
        )
        downloaded_files.append(local_path)

    return downloaded_files
