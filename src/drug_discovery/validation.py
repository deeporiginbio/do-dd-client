"""validation functions for drug discovery workflows"""

from beartype import beartype
from rdkit import Chem


@beartype
def validate_fragments(mol: Chem.Mol) -> Chem.Mol:
    """validate a molecule by checking if it has multiple, non-identical fragments

    Args:
        mol (Chem.Mol): The molecule to validate.

    Returns:
        Chem.Mol: The validated molecule.

    Raises:
        ValueError: If the molecule has multiple, non-identical fragments.
    """
    frags = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=False)
    if len(frags) > 1:
        unique_frags = {Chem.MolToSmiles(frag, canonical=True) for frag in frags}
        if len(unique_frags) > 1:
            raise ValueError("Molecule has multiple, non-identical fragments.")

        mol = frags[0]

    return mol
