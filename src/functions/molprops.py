"""Low-level molecular property predictions via the DeepOrigin functions API."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

from beartype import beartype

from deeporigin.drug_discovery.structures.ligand import LigandSet
from deeporigin.functions.result import FunctionResult
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import MOLPROPS_DEFAULT_PROPERTIES

# Merged molprops rows use ``ligand_id`` (toolbox molprops output schemas).
MOLPROPS_MERGE_KEY = "ligand_id"


@beartype
def molprops(
    ligand_set: LigandSet,
    properties: set[str] | None = None,
    *,
    client: DeepOriginClient,
) -> list[dict]:
    """Run molecular property prediction using the DeepOrigin API.

    Args:
        ligand_set: Molecules to predict (each needs ``smiles`` set).
        properties: Subset of molprops keys; defaults to the full ADMET bundle.
        client: Deep Origin API client.

    Returns:
        Merged list of dicts, one per ligand, with keys from each property run.
    """

    merged, _raw = molprops_merged_with_raw_responses(
        ligand_set=ligand_set,
        properties=properties,
        client=client,
    )
    return merged


def molprops_merged_with_raw_responses(
    ligand_set: LigandSet,
    properties: set[str] | None = None,
    *,
    client: DeepOriginClient,
) -> tuple[list[dict], list[dict]]:
    """Run molprops for each property, merge rows per ligand, and return raw API responses.

    Args:
        ligand_set: Molecules to run (each needs ``smiles`` set).
        properties: Subset of molprops keys; ``None`` means :data:`~deeporigin.utils.constants.MOLPROPS_DEFAULT_PROPERTIES`.
        client: Deep Origin API client.

    Returns:
        Tuple of (merged list of dicts per ligand, list of one full API response dict per property).
    """

    if properties is None:
        properties_set: set[str] = set(MOLPROPS_DEFAULT_PROPERTIES)
    else:
        properties_set = set(properties)

    payload = {"ligands": ligand_set.to_dict()}
    outputs_per_prop: list[list[dict]] = []
    raw_responses: list[dict] = []

    for prop in sorted(properties_set):
        function_outputs, raw = get_single_property(
            payload=payload,
            prop=prop,
            client=client,
            quote=False,
        )
        outputs_per_prop.append(function_outputs)
        raw_responses.append(raw)

    merged = merge_dict_lists(outputs_per_prop, key=MOLPROPS_MERGE_KEY)
    return merged, raw_responses


@beartype
def molprops_quote(
    ligand_set: LigandSet,
    properties: set[str],
    *,
    client: DeepOriginClient,
) -> FunctionResult:
    """Request cost estimates for molprops runs (one API call per property).

    Args:
        ligand_set: Molecules to quote (each needs ``smiles`` set).
        properties: Non-empty subset of molprops property keys.
        client: Deep Origin API client.

    Returns:
        ``FunctionResult`` whose ``estimate`` sums quoted prices across property calls.
    """

    payload = {"ligands": ligand_set.to_dict()}
    raw_list: list[dict] = []
    for prop in sorted(properties):
        _fo, raw = get_single_property(
            payload=payload,
            prop=prop,
            client=client,
            quote=True,
        )
        raw_list.append(raw)
    return FunctionResult(raw_list)


def get_single_property(
    *,
    payload: dict,
    prop: str,
    client: DeepOriginClient,
    quote: bool = False,
) -> tuple[list[dict], dict]:
    """Fetch one molprops model's outputs and the full API response.

    Args:
        payload: Request body (must include ``ligands``).
        prop: Property key suffix (e.g. ``logp``).
        client: Deep Origin API client.
        quote: If True, request a quotation only.

    Returns:
        ``(function_outputs, raw_response)`` with the full API payload.
    """

    raw = client.functions.run(
        key=f"{TOOL_KEYS_AND_VERSIONS['mol_props']['function_key_prefix']}-{prop}",
        params=payload,
        version=TOOL_KEYS_AND_VERSIONS["mol_props"]["function_version"],
        quote=quote,
    )

    fo = raw.get("functionOutputs")
    if fo is None:
        function_outputs: list[dict] = []
    elif isinstance(fo, dict):
        function_outputs = [fo]
    else:
        function_outputs = fo

    return function_outputs, raw


def merge_dict_lists(dict_lists, key="ligand_id"):
    """
    Merge N lists of dicts by a common key.

    Args:
        dict_lists: iterable of lists of dicts
        key: key to merge on (default: ``ligand_id`` for molprops)

    Returns:
        List of merged dicts, one per unique key value.
    """

    merged = defaultdict(dict)
    for lst in dict_lists:
        for d in lst:
            k = d[key]
            merged[k].update(d)  # merge keys into single dict
    # preserve insertion order of first list
    if dict_lists:
        order = [d[key] for d in dict_lists[0]]
        seen = set()
        result = []
        for k in order + [k for k in merged if k not in order]:
            if k not in seen:
                result.append(deepcopy(merged[k]))
                seen.add(k)
        return result
    return []
