"""Ligand list files: inline ``ligands`` up to a cap, a UFA JSON upload above it.

Admet, Metabolism, Docking and SecondaryPharmacology tools reject more than
:data:`~deeporigin.utils.constants.INLINE_LIGAND_CAP` inline ligands; larger
batches upload a Ligand list file (a bare JSON array of ligand rows) and pass
``ligands_file`` instead.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any
import uuid

from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.constants import INLINE_LIGAND_CAP


def upload_ligand_list(
    rows: list[dict[str, Any]],
    *,
    client: DeepOriginClient,
    prefix: str,
) -> str:
    """Upload *rows* as a Ligand list file and return its UFA path.

    Args:
        rows: Ligand rows in the tool's inline ``ligands`` shape.
        client: Client whose ``files`` API does the upload.
        prefix: UFA path prefix (e.g. ``"docking/ligand-lists/"``).

    Returns:
        ``<prefix><uuid>.json``.
    """
    if client.files is None:
        raise ValueError(
            "Cannot upload Ligand list file: client.files is not available."
        )
    remote_path = f"{prefix}{uuid.uuid4().hex}.json"
    fd, tmp_name = tempfile.mkstemp(suffix=".json", prefix="ligand-list-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, allow_nan=False)
        client.files.upload(tmp_name, remote_path)
    finally:
        Path(tmp_name).unlink(missing_ok=True)
    return remote_path


def ligands_input(
    rows: list[dict[str, Any]],
    *,
    client: DeepOriginClient,
    prefix: str,
) -> dict[str, Any]:
    """Return ``{"ligands": rows}``, or upload *rows* and reference the file.

    Returns:
        Tool inputs to merge: ``ligands``, or ``ligands_file`` + ``ligands_count``.
    """
    if len(rows) <= INLINE_LIGAND_CAP:
        return {"ligands": rows}
    return {
        "ligands_file": upload_ligand_list(rows, client=client, prefix=prefix),
        "ligands_count": len(rows),
    }


def parse_ligand_list(payload: bytes, *, label: str) -> list[dict[str, Any]]:
    """Parse a Ligand list file body into rows.

    Raises:
        ValueError: If the body is not UTF-8 JSON holding a non-empty array.
    """
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Cannot rehydrate {label}: ligands_file is not valid UTF-8: {exc}"
        ) from exc
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Cannot rehydrate {label}: ligands_file is not valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(parsed, list) or not parsed:
        raise ValueError(
            f"Cannot rehydrate {label}: ligands_file must be a non-empty JSON array."
        )
    return parsed


def ligand_rows_from_inputs(
    inputs: dict[str, Any],
    *,
    client: DeepOriginClient | None,
    label: str,
) -> list[Any]:
    """Return stored ligand rows from inline ``ligands`` or ``ligands_file``.

    Returns ``[]`` when neither is present; callers decide whether that is an
    error.

    Raises:
        ValueError: If ``ligands_file`` cannot be downloaded or parsed.
    """
    raw = inputs.get("ligands")
    if isinstance(raw, list) and raw:
        return raw
    remote = inputs.get("ligands_file")
    if not isinstance(remote, str) or not remote.strip():
        return []
    if client is None or client.files is None:
        raise ValueError(
            f"Cannot rehydrate {label}: client with files is required "
            "to download ligands_file."
        )
    try:
        local_path = client.files.download(remote.strip(), direct=True)
        payload = Path(local_path).read_bytes()
    except Exception as exc:
        raise ValueError(
            f"Cannot rehydrate {label}: failed to download ligands_file "
            f"{remote!r}: {exc}"
        ) from exc
    return parse_ligand_list(payload, label=label)


def ligands_from_rows(raw: list[Any], *, label: str) -> list[Ligand]:
    """Rebuild ligands from ``{smiles, id?}`` rows.

    Raises:
        ValueError: If a row is not an object or has no SMILES.
    """
    ligands: list[Ligand] = []
    for idx, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(
                f"Cannot rehydrate {label}: ligands[{idx}] is not an object."
            )
        smiles = row.get("smiles")
        if not smiles or not isinstance(smiles, str):
            raise ValueError(f"Cannot rehydrate {label}: ligands[{idx}] has no SMILES.")
        ligand = Ligand.from_smiles(smiles)
        if row.get("id") is not None:
            ligand.id = str(row["id"])
        ligands.append(ligand)
    return ligands
