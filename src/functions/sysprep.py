"""This module contains the function to run system preparation on a protein-ligand complex."""

from beartype import beartype

from deeporigin.drug_discovery.structures import Ligand, Protein
from deeporigin.platform.client import DeepOriginClient


@beartype
def run_sysprep(
    *,
    protein: Protein,
    ligand: Ligand,
    padding: float = 1.0,
    retain_waters: bool = False,
    add_H_atoms: bool = True,  # NOSONAR
    protonate_protein: bool = True,
    use_cache: bool = True,
    client: DeepOriginClient | None = None,
) -> dict:
    """
    Run system preparation on a protein-ligand complex.

    Args:
        protein_path (str | Path): Path to the protein file.
        ligand_path (str | Path): Path to the ligand file.
        padding (float, optional): Padding to add around the system. Defaults to 1.0.
        keep_waters (bool, optional): Whether to keep water molecules. Defaults to False.
        is_lig_protonated (bool, optional): Whether the ligand is already protonated. Defaults to True.
        is_protein_protonated (bool, optional): Whether the protein is already protonated. Defaults to True.
        client (DeepOriginClient | None): DeepOrigin client instance. If None, creates a new client using the default credentials. Defaults to None

    Returns:
        Path to the output PDB file if successful, or raises RuntimeError if the server fails.
    """

    payload = {
        "protein_path": protein._remote_path,
        "ligand_path": ligand._remote_path,
        "add_H_atoms": add_H_atoms,
        "protonate_protein": protonate_protein,
        "retain_waters": retain_waters,
        "padding": padding,
        "use_cache": use_cache,
    }

    protein.upload()
    ligand.upload()

    if client is None:
        client = DeepOriginClient()

    response = client.functions.run(
        key="deeporigin.system-prep",
        version="0.3.3",
        params=payload,
    )

    return response
