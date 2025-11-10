"""This module contains the function to run system preparation on a protein-ligand complex."""

from beartype import beartype

from deeporigin.drug_discovery.structures import Ligand, Protein


@beartype
def run_sysprep(
    *,
    protein: Protein,
    ligand: Ligand,
    padding: float = 1.0,
    retain_waters: bool = False,
    add_H_atoms: bool = True,
    protonate_protein: bool = True,
    use_cache: bool = True,
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

    # If no cached results, proceed with server call
    from deeporigin.platform import tools_api

    body = {"params": payload, "clusterId": tools_api.get_default_cluster_id()}

    # Send the request to the server
    try:
        response = tools_api.run_function(
            key="deeporigin.system-prep",
            version="0.3.3",
            function_execution_params_schema_dto=body,
        )
    except Exception as e:
        print(f"Error running sysprep: {e}")

        import json

        print(f"Body: {json.dumps(body, indent=4)}")

        raise e

    return response
