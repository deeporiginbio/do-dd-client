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
    quote: bool = False,
    billing: str | None = None,
    app: str | None = None,
    session: str | None = None,
    project_id: str | None = None,
) -> FunctionResult:
    """Find protein binding pockets in a PDB structure.

    Sends a PDB file to the Deep Origin pocket finder service and returns
    a ``FunctionResult`` wrapping the raw API response.

    Args:
        protein: Protein to find pockets in.
        pocket_count: Maximum number of pockets to detect. Defaults to 5.
        pocket_min_size: Minimum size of pockets to consider. Defaults to 30.
        client: Authenticated Deep Origin client.
        quote: If True, request a cost estimate without executing.
        billing: Optional billing identifier for the execution.
        app: Optional app identifier. Defaults to "do-dd-client" if not set.
        session: Optional session identifier for the execution.
        project_id: Optional project ID for the execution.

    Returns:
        FunctionResult wrapping the full API response.
    """

    if pocket_count < 1:
        raise ValueError("pocket_count must be at least 1") from None
    if pocket_min_size < 1:
        raise ValueError("pocket_min_size must be at least 1") from None

    protein.sync(lazy=True, client=client)

    payload = {
        "protein": {"file_path": protein._remote_path},
        "pocket_count": pocket_count,
        "pocket_min_size": pocket_min_size,
    }

    payload["protein"]["id"] = protein.id

    response = client.functions.run(
        key=POCKET_FINDER_FUNCTION_KEY,
        version=POCKET_FINDER_FUNCTION_VERSION,
        params=payload,
        quote=quote,
        billing=billing,
        app=app,
        session=session,
        project_id=project_id,
    )

    return FunctionResult([response])
