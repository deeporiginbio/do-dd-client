"""Unit tests for shared ligand result lookup helpers (no platform client)."""

from __future__ import annotations

from deeporigin.drug_discovery.ligand_results import (
    backfill_smiles_from_ligands,
    fetch_result_records,
    normalize_ligands,
    platform_ligand_ids,
    unique_preserve_order,
)
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.utils.constants import LIGAND_ID_QUERY_BATCH_SIZE


def test_normalize_ligands_accepts_ligand_list_set_and_empty() -> None:
    """A Ligand, a list, or a LigandSet all become a list; empty stays empty."""
    lig = Ligand.from_smiles("CCO")
    assert normalize_ligands(lig) == [lig]
    assert normalize_ligands([lig]) == [lig]
    assert normalize_ligands(LigandSet(ligands=[lig])) == [lig]
    assert normalize_ligands([]) == []


def test_platform_ligand_ids_skips_missing_and_blank() -> None:
    """Only non-empty platform ids are collected."""
    with_id = Ligand.from_smiles("CCO")
    with_id.id = "lig-1"
    blank = Ligand.from_smiles("CCN")
    blank.id = "  "
    no_id = Ligand.from_smiles("CCC")
    assert platform_ligand_ids([with_id, blank, no_id]) == ["lig-1"]


def testunique_preserve_order() -> None:
    """Duplicates are dropped while keeping first-seen order."""
    assert unique_preserve_order(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_backfill_smiles_from_ligands_fills_missing() -> None:
    """MQ-style rows without SMILES pick up Caller SMILES from ligands."""
    lig = Ligand.from_smiles("CCO")
    lig.id = "lig-1"
    other = Ligand.from_smiles("CCN")
    other.id = "lig-2"
    rows = [
        {"ligand_id": "lig-1", "confidence_tier": "high"},
        {"ligand_id": "lig-2", "smiles": "CCN", "confidence_tier": "low"},
        {"ligand_id": "lig-missing", "confidence_tier": "medium"},
    ]
    filled = backfill_smiles_from_ligands(rows, ligands=[lig, other])
    assert filled[0]["smiles"] == "CCO"
    assert filled[1]["smiles"] == "CCN"
    assert "smiles" not in filled[2]


class _RecordingResults:
    """Record every ``Results.get`` call and return one record per call."""

    def __init__(self) -> None:
        """Initialize with an empty call log."""
        self.calls: list[dict] = []

    def get(self, **kwargs: object) -> dict:
        """Store kwargs and return a single-record payload."""
        self.calls.append(kwargs)
        return {"data": [{"data": {"ligand_id": "x"}}, "junk"]}


class _RecordingClient:
    """Minimal client exposing ``results.get``."""

    def __init__(self) -> None:
        """Attach a recording Results stand-in."""
        self.results = _RecordingResults()


def test_fetch_result_records_batches_unique_ids_by_tool() -> None:
    """Ids are deduplicated, batched, and filtered by tool key, not execution."""
    client = _RecordingClient()
    ids = [f"lig-{i}" for i in range(LIGAND_ID_QUERY_BATCH_SIZE + 1)] + ["lig-0"]

    records = fetch_result_records(
        client,  # type: ignore[arg-type]
        ligand_ids=ids,
        tool_key="deeporigin.admet-properties",
        result_type="admetproperty",
        page_size=1000,
    )

    assert len(client.results.calls) == 2
    first, second = client.results.calls
    assert len(first["filter_dict"]["ligand_id"]["in"]) == LIGAND_ID_QUERY_BATCH_SIZE
    assert second["filter_dict"]["ligand_id"]["in"] == [
        f"lig-{LIGAND_ID_QUERY_BATCH_SIZE}"
    ]
    assert first["filter_dict"]["tool_key"] == {"eq": "deeporigin.admet-properties"}
    assert "compute_job_id" not in first
    assert records == [{"data": {"ligand_id": "x"}}] * 2


def test_fetch_result_records_skips_query_without_ids() -> None:
    """No ligand ids means no request."""
    client = _RecordingClient()
    assert (
        fetch_result_records(
            client,  # type: ignore[arg-type]
            ligand_ids=[],
            tool_key="t",
            result_type="r",
            page_size=1,
        )
        == []
    )
    assert client.results.calls == []
