"""Low-level function to find pockets in a protein using the Deep Origin API."""

from deeporigin.drug_discovery.structures import Protein
from deeporigin.functions.result import FunctionResult
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import (
    POCKET_FINDER_FUNCTION_KEY,
    POCKET_FINDER_FUNCTION_VERSION,
)


def find_pockets(
    *,
    protein: Protein,
    pocket_count: int = 5,
    pocket_min_size: int = 30,
    client: DeepOriginClient,
    tool_version: str = POCKET_FINDER_FUNCTION_VERSION,
    quote: bool = False,
) -> FunctionResult:
    """Find protein binding pockets in a PDB structure.

    Sends a PDB file to the Deep Origin pocket finder service and returns
    a ``FunctionResult`` wrapping the raw API response.

    Args:
        protein: Protein to find pockets in.
        pocket_count: Maximum number of pockets to detect. Defaults to 5.
        pocket_min_size: Minimum size of pockets to consider. Defaults to 30.
        client: Authenticated Deep Origin client.
        tool_version: Function version for ``deeporigin.pocketfinder`` (defaults to
            :data:`~deeporigin.platform.constants.POCKET_FINDER_FUNCTION_VERSION`).
        quote: If True, request a cost estimate without executing.

    Returns:
        FunctionResult wrapping the full API response.
    """

    if pocket_count < 1:
        raise ValueError("pocket_count must be at least 1") from None
    if pocket_min_size < 1:
        raise ValueError("pocket_min_size must be at least 1") from None

    protein.sync(lazy=True, client=client)
    protein.ensure_remote_path(client=client, label="Protein")

    payload = {
        "protein": {"file_path": protein.remote_path},
        "pocket_count": pocket_count,
        "pocket_min_size": pocket_min_size,
    }

    payload["protein"]["id"] = protein.id

    response = client.functions.run(
        key=POCKET_FINDER_FUNCTION_KEY,
        version=tool_version,
        params=payload,
        quote=quote,
    )

    return FunctionResult([response])
