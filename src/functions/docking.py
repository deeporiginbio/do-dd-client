"""Low-level functions for molecular docking via the Deep Origin API.

The main function `dock()` takes a Protein, a Ligand, and a Pocket and
performs docking calculations remotely. Box size and pocket center are
derived from the Pocket object.
"""

import os
from pathlib import Path
from typing import Literal, Optional

from deeporigin.drug_discovery.structures import Ligand, Pocket, Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.functions.result import FunctionResult
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import (
    CONSTRAINED_DOCKING_FUNCTION_KEY,
    DOCKING_FUNCTION_KEY,
    DOCKING_FUNCTION_VERSION,
)
from deeporigin.utils.env import _ensure_do_folder
from deeporigin.utils.hashing import hash_dict


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


def _get_box_size(pocket: Pocket, axis: str) -> float:
    """Return box size for *axis* from *pocket*, defaulting to 20.0."""
    val = getattr(pocket, f"box_size_{axis}", None)
    if val is not None:
        return float(val)
    return 20.0


def dock(
    *,
    client: DeepOriginClient,
    protein: Protein,
    ligand: Ligand,
    pocket: Pocket,
    tool_version: str = DOCKING_FUNCTION_VERSION,
    effort: int = 3,
    quote: bool = False,
) -> FunctionResult:
    """Run molecular docking using the DeepOrigin API.

    Args:
        client: DeepOrigin client instance.
        protein: Protein object representing the target protein.
        ligand: Ligand object to dock.
        pocket: Pocket object defining the docking region. Box size
            and pocket center are derived from the pocket.
        tool_version: Function version for ``deeporigin.docking`` (defaults to
            :data:`~deeporigin.platform.constants.DOCKING_FUNCTION_VERSION`).
        effort: Docking effort level (1 = fastest, 5 = most thorough).
        quote: If True, request a cost estimate without executing.

    Returns:
        FunctionResult wrapping the full API response.
    """
    if not 1 <= effort <= 5:
        raise DeepOriginException(
            f"effort must be between 1 and 5 inclusive, got {effort}"
        ) from None

    protein.sync(lazy=True, client=client)
    ligand.sync(lazy=True, client=client)
    protein.ensure_remote_path(client=client, label="Protein")

    if pocket.center is not None:
        pocket_center = list(pocket.center)
    else:
        pocket_center = pocket.get_center().tolist()

    protein_data = {
        "id": protein.id,
        "file_path": protein.remote_path,
    }

    ligand_data = {
        "id": ligand.id,
        "smiles": ligand.smiles,
    }

    pocket_data: dict = {
        "center": pocket_center,
        "box_size_x": _get_box_size(pocket, "x"),
        "box_size_y": _get_box_size(pocket, "y"),
        "box_size_z": _get_box_size(pocket, "z"),
    }
    if pocket.id is not None:
        pocket_data["id"] = pocket.id

    payload = {
        "effort": effort,
        "protein": protein_data,
        "ligands": [ligand_data],
        "pocket": pocket_data,
    }

    response = client.functions.run(
        key=DOCKING_FUNCTION_KEY,
        version=tool_version,
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
) -> FunctionResult:
    """Perform constrained molecular docking using reference ligand constraints.

    Args:
        client: DeepOrigin client instance.
        protein: The protein structure to dock against.
        ligand: The ligand to be docked.
        constraints: List of constraints for the docking. Generate
            using ``align.compute_constraints``.
        pocket: Optional pocket object whose center is used as
            ``pocket_center``.
        box_size: Size of the docking box in Angstroms (x, y, z).
        pocket_center: Center coordinates for the docking box.
        top_criteria: Criteria for selecting top poses.
        use_cache: Whether to use cached results if available.
        quote: If True, request a cost estimate without executing.

    Returns:
        FunctionResult wrapping the full API response. When
        ``quote=False``, downloaded result file paths are available
        via ``result.downloaded_files``.
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
        "protein_path": protein.remote_path,
        "ligand_path": ligand.remote_path,
        "box_size": list(box_size),
        "constraints": constraints,
        "protein": {"pocket_center": pocket_center_list},
        "top_criteria": top_criteria,
    }

    cache_hash = hash_dict(payload)
    extract_dir = str(Path(CACHE_DIR) / cache_hash)

    if os.path.exists(extract_dir) and use_cache and not quote:
        result = FunctionResult([{"status": "Completed"}])
        result.downloaded_files = _extract_cached_files(extract_dir)
        return result

    response = client.functions.run(
        key=CONSTRAINED_DOCKING_FUNCTION_KEY,
        params=payload,
        quote=quote,
    )

    result = FunctionResult([response])

    if quote:
        result.downloaded_files = []
        return result

    outputs = response.get("functionOutputs", {})

    Path(extract_dir).mkdir(parents=True, exist_ok=True)
    downloaded_files = []

    output_files = outputs.get("output_files", {})
    for filename, remote_path in output_files.items():
        local_path = str(Path(extract_dir) / filename)
        client.files.download(
            remote_path=remote_path,
            local_path=local_path,
        )
        downloaded_files.append(local_path)

    result.downloaded_files = downloaded_files
    return result
