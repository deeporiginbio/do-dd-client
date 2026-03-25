"""Low-level functions to run system preparation on a protein-ligand complex."""

from beartype import beartype

from deeporigin.drug_discovery.structures import Ligand, Protein
from deeporigin.functions.result import FunctionResult
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import SYSPREP_FUNCTION_KEY, SYSPREP_FUNCTION_VERSION


def _build_sysprep_payload(
    *,
    protein: Protein,
    ligand1: Ligand,
    ligand2: Ligand | None,
    padding: float,
    retain_waters: bool,
    add_H_atoms: bool,  # NOSONAR
    protonate_protein: bool,
    box_size: list[float] | None,
    client: DeepOriginClient,
) -> dict:
    """Build and upload inputs, returning the payload dict for a sysprep call.

    Args:
        protein: Protein structure for system preparation.
        ligand1: First ligand structure for system preparation.
        ligand2: Optional second ligand for RBFE preparation.
        padding: Padding distance in nm to use around the system.
        retain_waters: Whether to keep water molecules in the system.
        add_H_atoms: Whether to add hydrogen atoms to the ligand.
        protonate_protein: Whether to protonate the protein.
        box_size: Simulation box dimensions (X, Y, Z) in nm.
        client: DeepOrigin client instance.

    Returns:
        Payload dict ready to pass to the functions API.
    """
    protein.sync(lazy=True, client=client)
    ligand1.sync(lazy=True, client=client)
    if ligand2 is not None:
        ligand2.sync(lazy=True, client=client)

    payload = {
        "protein": {"id": protein.id, "file_path": protein.remote_path},
        "ligand1": {"id": ligand1.id, "file_path": ligand1.remote_path},
        "add_H_atoms": add_H_atoms,
        "protonate_protein": protonate_protein,
        "retain_waters": retain_waters,
        "padding": padding,
    }

    if box_size is not None:
        payload["box_size"] = box_size

    if ligand2 is not None:
        payload["ligand2"] = {"id": ligand2.id, "file_path": ligand2.remote_path}

    return payload


@beartype
def for_abfe(
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
) -> FunctionResult:
    """Run ABFE system preparation on a protein with a single ligand.

    Args:
        protein: Protein structure for system preparation.
        ligand: Ligand structure for system preparation.
        padding: Padding distance in nm to use around the system.
        retain_waters: Whether to keep water molecules in the system.
        add_H_atoms: Whether to add hydrogen atoms to the ligand.
        protonate_protein: Whether to protonate the protein.
        box_size: Simulation box dimensions (X, Y, Z) in nm. Must have
            exactly 3 elements if provided.
        client: DeepOrigin client instance.
        quote: If True, request a cost estimate without executing.

    Returns:
        FunctionResult wrapping the full API response.
    """
    payload = _build_sysprep_payload(
        protein=protein,
        ligand1=ligand,
        ligand2=None,
        padding=padding,
        retain_waters=retain_waters,
        add_H_atoms=add_H_atoms,
        protonate_protein=protonate_protein,
        box_size=box_size,
        client=client,
    )

    response = client.functions.run(
        key=SYSPREP_FUNCTION_KEY,
        version=SYSPREP_FUNCTION_VERSION,
        params=payload,
        quote=quote,
    )

    return FunctionResult([response])


@beartype
def for_rbfe(
    *,
    protein: Protein,
    ligand1: Ligand,
    ligand2: Ligand,
    padding: float = 1.0,
    retain_waters: bool = False,
    add_H_atoms: bool = True,  # NOSONAR
    protonate_protein: bool = True,
    box_size: list[float] | None = None,
    client: DeepOriginClient,
    quote: bool = False,
) -> FunctionResult:
    """Run RBFE system preparation on a protein with two ligands.

    Args:
        protein: Protein structure for system preparation.
        ligand1: First ligand structure for system preparation.
        ligand2: Second ligand structure for system preparation.
        padding: Padding distance in nm to use around the system.
        retain_waters: Whether to keep water molecules in the system.
        add_H_atoms: Whether to add hydrogen atoms to the ligands.
        protonate_protein: Whether to protonate the protein.
        box_size: Simulation box dimensions (X, Y, Z) in nm. Must have
            exactly 3 elements if provided.
        client: DeepOrigin client instance.
        quote: If True, request a cost estimate without executing.

    Returns:
        FunctionResult wrapping the full API response.
    """
    payload = _build_sysprep_payload(
        protein=protein,
        ligand1=ligand1,
        ligand2=ligand2,
        padding=padding,
        retain_waters=retain_waters,
        add_H_atoms=add_H_atoms,
        protonate_protein=protonate_protein,
        box_size=box_size,
        client=client,
    )

    response = client.functions.run(
        key=SYSPREP_FUNCTION_KEY,
        version=SYSPREP_FUNCTION_VERSION,
        params=payload,
        quote=quote,
    )

    return FunctionResult([response])
