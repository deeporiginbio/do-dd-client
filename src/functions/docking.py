"""This module implements a low level function to perform molecular docking using the Deep Origin API.

The main function `dock()` takes a Protein object, a list of ligand SMILES strings, and docking box parameters
to perform docking calculations. The docking box can be specified either by providing explicit coordinates for the
pocket center, or by passing a Pocket object which contains the pocket center information.

The module interfaces with the Deep Origin docking service to perform the actual docking calculations remotely.
"""

import os
from pathlib import Path
from typing import Optional
import zipfile

import requests

from deeporigin.drug_discovery.structures import Ligand, Pocket, Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.core import hash_dict


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
    protein: Protein,
    smiles_string: Optional[str] = None,
    ligand: Optional[Ligand] = None,
    box_size: tuple[float, float, float] = (20.0, 20.0, 20.0),
    pocket_center: Optional[tuple[int, int, int]] = None,
    pocket: Optional[Pocket] = None,
    use_cache: bool = True,
    client: DeepOriginClient | None = None,
) -> str:
    """
    Run molecular docking using the DeepOrigin API.

    Args:
        protein (Protein): Protein object representing the target protein
        smiles_string (Optional[str]): SMILES string for the ligand to dock
        ligand (Optional[Ligand]): Ligand object to dock
        box_size (tuple[float, float, float]): Size of the docking box (x, y, z)
        pocket_center (Optional[tuple[int, int, int]]): Center coordinates of the docking pocket (x, y, z)
        pocket (Optional[Pocket]): Pocket object defining the docking region
        use_cache (bool): Whether to use cached results. Defaults to True
        client (DeepOriginClient | None): DeepOrigin client instance. If None, creates a new client. Defaults to None

    Returns:
        str: path to the SDF file containing the docking results
    """

    CACHE_DIR = os.path.expanduser("~/.deeporigin/docking")

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

    # Prepare the request payload
    payload = {
        "protein_path": protein._remote_path,
        "ligand_smiles": smiles_string,
        "box_size": list(box_size),
        "pocket_center": list(pocket_center),
    }
    cache_hash = hash_dict(payload)
    sdf_file = str(Path(CACHE_DIR) / f"{cache_hash}.sdf")

    # Check if cached result exists
    if os.path.exists(sdf_file) and use_cache:
        return sdf_file

    protein.upload()

    if client is None:
        client = DeepOriginClient()

    response = client.functions.run(
        key="deeporigin.docking",
        version="0.2.4",
        params=payload,
    )

    sdf_file = client.files.download_file(
        remote_path=response["sdf_path"],
        local_path=sdf_file,
    )

    return sdf_file


def constrained_dock(
    *,
    protein: Protein,
    ligand: Ligand,
    constraints: list[dict],
    pocket: Optional[Pocket] = None,
    box_size: tuple[float, float, float] = (20.0, 20.0, 20.0),
    pocket_center: Optional[tuple[int, int, int]] = None,
    use_cache: bool = True,
) -> list[str]:
    """Perform constrained molecular docking using a reference ligand constraints.

    This function performs molecular docking with constraints based on a reference ligand
    and a maximum common substructure (MCS). The ligand is aligned to the reference ligand
    using the MCS, and docking is performed with these alignment constraints applied.

    Args:
        protein (Protein): The protein structure to dock against.
        ligand (Ligand): The ligand to be docked.
        constraints (list[dict]): List of constraints for the docking. Generate this using `align.compute_constraints`.
        pocket (Optional[Pocket]): Optional pocket object. If provided, its center will be used as pocket_center.
        box_size (tuple[float, float, float]): Size of the docking box in Angstroms (x, y, z). Defaults to (20.0, 20.0, 20.0).
        pocket_center (Optional[tuple[int, int, int]]): Optional center coordinates for the docking box. If None and pocket is provided,
                     uses the pocket center. If both are None, raises an error.
        use_cache (bool): Whether to use cached results if available. Defaults to True.

    Returns:
        list[str]: List of file paths to the docking result files (typically SDF files).


    Note:
        The function creates a cache directory at ~/.deeporigin/constrained_docking/ and
        stores results based on a SHA256 hash of all input parameters. This allows for
        efficient reuse of previous docking results.
    """
    URL = "http://constrained-docking.default.jobs.edge.deeporigin.io/dock"
    CACHE_DIR = os.path.expanduser("~/.deeporigin/constrained_docking")

    if pocket is None and pocket_center is None:
        raise DeepOriginException(
            "Either pocket or pocket_center must be provided"
        ) from None

    pocket_center_list = _get_pocket_center(pocket, pocket_center)

    payload = {
        "box_size": box_size,
        "constraints": constraints,
        "protein": {"pocket_center": pocket_center_list},
        "top_criteria": "score",
        "protein_b64": protein.to_base64(),
        "ligand_b64": ligand.to_base64(),
    }

    cache_hash = hash_dict(payload)
    zip_file = str(Path(CACHE_DIR) / f"{cache_hash}.zip")
    extract_dir = str(Path(CACHE_DIR) / cache_hash)

    if os.path.exists(extract_dir) and use_cache:
        return _extract_cached_files(extract_dir)

    # Send the POST request
    response = requests.post(
        URL,
        headers={"Content-Type": "application/json"},
        json=payload,
    )
    response.raise_for_status()

    # Write and extract zip file
    Path(zip_file).parent.mkdir(parents=True, exist_ok=True)
    with open(zip_file, "wb") as f:
        f.write(response.content)

    Path(extract_dir).mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_file, "r") as zip_ref:
        zip_ref.extractall(extract_dir)

    os.remove(zip_file)
    return _extract_cached_files(extract_dir)
