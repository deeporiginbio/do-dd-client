"""Low-level molecular property predictions via the DeepOrigin functions API."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import json
import os
from pathlib import Path
from typing import Optional

from beartype import beartype

from deeporigin.functions.result import FunctionResult
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import (
    MOL_PROPS_FUNCTION_KEY_PREFIX,
    MOL_PROPS_FUNCTION_VERSION,
)
from deeporigin.utils.constants import MOLPROPS_DEFAULT_PROPERTIES
from deeporigin.utils.env import _ensure_do_folder
from deeporigin.utils.hashing import hash_dict

CACHE_DIR = str(_ensure_do_folder() / "molprops")

# Ensure cache directory exists
os.makedirs(CACHE_DIR, exist_ok=True)

# Merged molprops rows use ``ligand_id`` (toolbox molprops output schemas).
MOLPROPS_MERGE_KEY = "ligand_id"


@beartype
def molprops_ligands_payload(ligands: list[dict[str, str]]) -> list[dict[str, str]]:
    """Build ``ligands`` entries for molprops function requests.

    Each item must include ``smiles``. Optional ``id`` defaults to the zero-based
    index as a string so outputs can be merged by ``ligand_id``.

    Args:
        ligands: One dict per molecule, with ``smiles`` and optional ``id``.

    Returns:
        Normalized list suitable for the API ``ligands`` array.

    Raises:
        ValueError: If a row is missing ``smiles``.
    """
    out: list[dict[str, str]] = []
    for i, row in enumerate(ligands):
        smiles = row.get("smiles")
        if smiles is None or smiles == "":
            raise ValueError(f'ligands[{i}] must include a non-empty "smiles" string.')
        lid = row["id"] if "id" in row else str(i)
        out.append({"id": lid, "smiles": smiles})
    return out


@beartype
def molprops(
    ligands: list[dict[str, str]],
    properties: Optional[set[str]] = None,
    *,
    client: DeepOriginClient,
    use_cache: bool = True,
) -> list[dict]:
    """Run molecular property prediction using the DeepOrigin API.

    Args:
        ligands: One dict per molecule; each must have ``smiles`` and may include
            ``id`` (defaults to ``0``, ``1``, … by position as strings).
        properties: Subset of molprops keys; defaults to the full ADMET bundle.
        client: Deep Origin API client.
        use_cache: Whether to read/write disk cache for completed runs.

    Returns:
        Merged list of dicts, one per ligand, with keys from each property run.
    """

    merged, _raw = molprops_merged_with_raw_responses(
        ligands=ligands,
        properties=properties,
        client=client,
        use_cache=use_cache,
    )
    return merged


def molprops_merged_with_raw_responses(
    ligands: list[dict[str, str]],
    properties: Optional[set[str]] = None,
    *,
    client: DeepOriginClient,
    use_cache: bool = True,
) -> tuple[list[dict], list[dict]]:
    """Run molprops for each property, merge rows per ligand, and return raw API responses.

    Args:
        ligands: One dict per molecule; each must have ``smiles`` and may include ``id``.
        properties: Subset of molprops keys; ``None`` means :data:`~deeporigin.utils.constants.MOLPROPS_DEFAULT_PROPERTIES`.
        client: Deep Origin API client.
        use_cache: Whether to use disk cache for completed (non-quote) runs.

    Returns:
        Tuple of (merged list of dicts per ligand, list of one full API response dict per property).
    """

    if properties is None:
        properties_set: set[str] = set(MOLPROPS_DEFAULT_PROPERTIES)
    else:
        properties_set = set(properties)

    payload = {"ligands": molprops_ligands_payload(ligands)}
    outputs_per_prop: list[list[dict]] = []
    raw_responses: list[dict] = []

    for prop in sorted(properties_set):
        function_outputs, raw = get_single_property(
            payload=payload,
            prop=prop,
            use_cache=use_cache,
            client=client,
            quote=False,
        )
        outputs_per_prop.append(function_outputs)
        raw_responses.append(raw)

    merged = merge_dict_lists(outputs_per_prop, key=MOLPROPS_MERGE_KEY)
    return merged, raw_responses


@beartype
def molprops_quote(
    ligands: list[dict[str, str]],
    properties: set[str],
    *,
    client: DeepOriginClient,
) -> FunctionResult:
    """Request cost estimates for molprops runs (one API call per property, no cache).

    Args:
        ligands: One dict per molecule; each must have ``smiles`` and may include ``id``.
        properties: Non-empty subset of molprops property keys.
        client: Deep Origin API client.

    Returns:
        ``FunctionResult`` whose ``estimate`` sums quoted prices across property calls.
    """

    payload = {"ligands": molprops_ligands_payload(ligands)}
    raw_list: list[dict] = []
    for prop in sorted(properties):
        _fo, raw = get_single_property(
            payload=payload,
            prop=prop,
            use_cache=False,
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
    use_cache: bool = True,
    quote: bool = False,
) -> tuple[list[dict], dict]:
    """Fetch one molprops model's outputs and optionally the full API response.

    Args:
        payload: Request body (must include ``ligands``).
        prop: Property key suffix (e.g. ``logp``).
        client: Deep Origin API client.
        use_cache: Whether to use disk cache (ignored when ``quote=True``).
        quote: If True, request a quotation only; cache is not used.

    Returns:
        ``(function_outputs, raw_response)`` with the full API or cache payload.
    """

    cache_hash = hash_dict({"property": prop, **payload})
    response_file = str(Path(CACHE_DIR) / f"{cache_hash}.json")

    if not quote and os.path.exists(response_file) and use_cache:
        with open(response_file) as file:
            cached = json.load(file)
        if isinstance(cached, list):
            synthetic_raw = {
                "status": "Completed",
                "functionOutputs": cached,
                "quotationResult": {"successfulQuotations": []},
            }
            return cached, synthetic_raw
        function_outputs = cached.get("functionOutputs")
        if function_outputs is None:
            return [], cached
        if isinstance(function_outputs, dict):
            return [function_outputs], cached
        return function_outputs, cached

    raw = client.functions.run(
        key=f"{MOL_PROPS_FUNCTION_KEY_PREFIX}-{prop}",
        params=payload,
        version=MOL_PROPS_FUNCTION_VERSION,
        quote=quote,
    )

    fo = raw.get("functionOutputs")
    if fo is None:
        function_outputs: list[dict] = []
    elif isinstance(fo, dict):
        function_outputs = [fo]
    else:
        function_outputs = fo

    if not quote:
        Path(response_file).parent.mkdir(parents=True, exist_ok=True)
        with open(response_file, "w") as file:
            json.dump(raw, file)

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
