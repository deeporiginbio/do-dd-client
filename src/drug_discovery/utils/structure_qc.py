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

    threshold_sq = contact_distance * contact_distance
    ligand_chunk_size = 512
    protein_chunk_size = 2048
    for lig_start in range(0, len(ligand_coords), ligand_chunk_size):
        ligand_chunk = ligand_coords[lig_start : lig_start + ligand_chunk_size]
        for prot_start in range(0, len(protein_coords), protein_chunk_size):
            protein_chunk = protein_coords[prot_start : prot_start + protein_chunk_size]
            diff = ligand_chunk[:, np.newaxis, :] - protein_chunk[np.newaxis, :, :]
            dist_sq = np.sum(diff * diff, axis=2)
            if np.any(dist_sq < threshold_sq):
                return True
    return False
