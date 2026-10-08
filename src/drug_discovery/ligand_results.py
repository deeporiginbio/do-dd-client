"""Look up tool results stored on the data platform for ligands.

Tools skip ligands that already have results, so a ligand's results can come
from any past execution. Tool ``fetch_*`` classmethods (for example
:meth:`~deeporigin.drug_discovery.admet.Admet.fetch_results`) query here by
platform ``ligand_id`` instead of by execution, then parse their own result
payloads.
"""

from __future__ import annotations

from typing import Any

from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.constants import LIGAND_ID_QUERY_BATCH_SIZE


def normalize_ligands(ligands: Ligand | list[Ligand] | LigandSet) -> list[Ligand]:
    """Return a new list from a ligand, list, or :class:`LigandSet`.

    Empty input returns an empty list; callers that require ligands raise with
    their own message.

    Args:
        ligands: A single ligand, a list, or a :class:`LigandSet`.

    Returns:
        A new list of the ligands.
    """

    if isinstance(ligands, LigandSet):
        return list(ligands.ligands)
    if isinstance(ligands, Ligand):
        return [ligands]
    return list(ligands)


def resolve_client(client: DeepOriginClient | None) -> DeepOriginClient:
    """Return *client* or construct the default :class:`DeepOriginClient`.

    Args:
        client: Optional API client.

    Returns:
        A usable :class:`DeepOriginClient`.
    """

    return client if client is not None else DeepOriginClient()


def platform_ligand_ids(ligands: list[Ligand]) -> list[str]:
    """Return non-empty platform ligand ids in input order (duplicates kept).

    Args:
        ligands: Ligands that may or may not have ``id`` set.

    Returns:
        Stripped id strings for ligands that have a platform id.
    """

    ids: list[str] = []
    for lig in ligands:
        raw = lig.id
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            ids.append(text)
    return ids


def unique_preserve_order(values: list[str]) -> list[str]:
    """Return unique strings preserving first-seen order.

    Args:
        values: Possibly duplicated strings.

    Returns:
        Deduplicated list.
    """

    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def fetch_result_records(
    client: DeepOriginClient,
    *,
    ligand_ids: list[str],
    tool_key: str,
    result_type: str,
    page_size: int,
    select: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Load stored result-explorer records for *ligand_ids* from any execution.

    Queries in batches of
    :data:`~deeporigin.utils.constants.LIGAND_ID_QUERY_BATCH_SIZE` ids. Project
    scope follows :meth:`deeporigin.platform.results.Results.get`.

    Args:
        client: Platform API client.
        ligand_ids: Platform ligand ids to query (may be empty or repeated).
        tool_key: Tool whose results to return.
        result_type: Catalog base entity (e.g. ``admetproperty``).
        page_size: Records requested per HTTP page.
        select: Record fields to return; ``None`` uses the
            :meth:`~deeporigin.platform.results.Results.get` default.

    Returns:
        Raw records (with ``data`` payloads) across all batches.
    """

    unique_ids = unique_preserve_order(ligand_ids)
    records: list[dict[str, Any]] = []
    for start in range(0, len(unique_ids), LIGAND_ID_QUERY_BATCH_SIZE):
        response = client.results.get(
            filter_dict={
                "ligand_id": {
                    "in": unique_ids[start : start + LIGAND_ID_QUERY_BATCH_SIZE]
                },
                "tool_key": {"eq": tool_key},
            },
            result_type=result_type,
            limit=None,
            page_size=page_size,
            select=select,
        )
        data = response.get("data") if isinstance(response, dict) else None
        if isinstance(data, list):
            records.extend(r for r in data if isinstance(r, dict))
    return records


def _smiles_by_ligand_id(ligands: list[Ligand]) -> dict[str, str]:
    """Map platform ligand id → Caller SMILES from *ligands*.

    When multiple ligands share an id, the first non-empty SMILES wins.

    Args:
        ligands: Ligands that may carry platform ids and SMILES.

    Returns:
        Mapping of stripped ligand id to SMILES string.
    """

    out: dict[str, str] = {}
    for lig in ligands:
        raw_id = lig.id
        if raw_id is None:
            continue
        ligand_id = str(raw_id).strip()
        if not ligand_id or ligand_id in out:
            continue
        smiles = lig.smiles
        if isinstance(smiles, str) and smiles:
            out[ligand_id] = smiles
    return out


def backfill_smiles_from_ligands(
    rows: list[dict[str, Any]],
    *,
    ligands: list[Ligand],
) -> list[dict[str, Any]]:
    """Fill missing ``smiles`` on result rows from input ligands by ``ligand_id``.

    Indexed MQ rows omit Caller SMILES; HTTP ``jobOutputs`` keep them. Fetch
    APIs restore SMILES from the caller's ligand objects when the index row
    has no SMILES.

    Args:
        rows: Result-explorer or similar row dicts (not mutated).
        ligands: Ligands passed to ``fetch_*``.

    Returns:
        New list of row dicts with ``smiles`` filled when possible.
    """

    smiles_by_id = _smiles_by_ligand_id(ligands)
    if not smiles_by_id:
        return list(rows)

    filled: list[dict[str, Any]] = []
    for row in rows:
        ligand_id = row.get("ligand_id")
        existing = row.get("smiles")
        has_smiles = isinstance(existing, str) and bool(existing)
        if (
            has_smiles
            or not isinstance(ligand_id, str)
            or ligand_id not in smiles_by_id
        ):
            filled.append(row)
            continue
        filled.append({**row, "smiles": smiles_by_id[ligand_id]})
    return filled
