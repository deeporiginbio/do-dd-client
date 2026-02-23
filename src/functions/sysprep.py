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
    box_size: list[float] | None = None,
    client: DeepOriginClient,
    quote: bool = False,
) -> dict:
    """Run system preparation on a protein-ligand complex.

    Args:
        protein: Protein structure for system preparation.
        ligand: Ligand structure for system preparation.
        padding: Padding distance in nm to use around the system.
        retain_waters: Whether to keep water molecules in the system.
        add_H_atoms: Whether to add hydrogen atoms to the ligand.
        protonate_protein: Whether to protonate the protein.
        use_cache: Whether to use cached output files if available.
        box_size: Simulation box dimensions (X, Y, Z) in nm. Must have
            exactly 3 elements if provided.
        client: DeepOrigin client instance.
        quote: If True, return a cost estimate instead of running.

    Returns:
        Dictionary containing the prepared system outputs, including
        paths to solvation XML, system PDB, and binding XML files.
    """

    # ensure the protein and ligand are synced to the data platform
    protein.sync(lazy=True, client=client)
    ligand.sync(lazy=True, client=client)

    protein_input = {
        "id": protein.id,
        "file_path": protein._remote_path,
    }

    ligand_input = {
        "id": ligand.id,
        "file_path": ligand._remote_path,
    }

    payload = {
        "protein": protein_input,
        "ligand": ligand_input,
        "add_H_atoms": add_H_atoms,
        "protonate_protein": protonate_protein,
        "retain_waters": retain_waters,
        "padding": padding,
    }

    if box_size is not None:
        payload["box_size"] = box_size

    protein.upload(client=client)
    ligand.upload(client=client)

    response = client.functions.run(
        key="deeporigin.system-prep",
        version="0.6.2",
        params=payload,
        quote=quote,
    )

    return response["functionOutputs"]
