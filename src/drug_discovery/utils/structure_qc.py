"""Structure quality-control utilities for drug discovery workflows."""

from beartype import beartype
import numpy as np


@beartype
def _any_ligand_protein_clashes(
    ligand_coords: np.ndarray,
    protein_coords: np.ndarray,
    *,
    contact_distance: float,
) -> bool:
    """Return True if any ligand atom is closer than ``contact_distance`` to a protein atom.

    Args:
        ligand_coords: Ligand atom coordinates with shape (n_lig, 3) in Å.
        protein_coords: Protein atom coordinates with shape (n_prot, 3) in Å.
        contact_distance: Distance threshold (Å) below which a pair is a clash.

    Returns:
        True when at least one atom pair is closer than ``contact_distance``.
    """
    if ligand_coords.size == 0 or protein_coords.size == 0:
        return False

    diff = ligand_coords[:, np.newaxis, :] - protein_coords[np.newaxis, :, :]
    distances = np.linalg.norm(diff, axis=2)
    return bool(np.any(distances < contact_distance))
