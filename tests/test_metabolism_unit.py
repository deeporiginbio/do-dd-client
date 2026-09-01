"""Unit tests for Metabolism helpers (no platform client)."""

from __future__ import annotations

import pytest

from deeporigin.drug_discovery.metabolism import (
    Metabolism,
    _backfill_smiles_from_ligands,
    _job_output_rows,
    _ligands_from_inputs,
    _metabolism_default_name,
    _normalize_ligands,
    _ordered_dataframe,
    _platform_ligand_ids,
    _rows_for_ligand_ids,
    _rows_from_result_explorer,
    _unique_preserve_order,
)
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.utils.constants import (
    METABOLISM_INLINE_LIGAND_CAP,
    METABOLISM_RESULT_EXPLORER_PAGE_SIZE,
    METABOLISM_WORKFLOW_LIGAND_THRESHOLD,
)


def test_normalize_ligands_accepts_ligand_list_and_set() -> None:
    """A Ligand, a list, or a LigandSet all become a list."""
    lig = Ligand.from_smiles("CCO")
    assert _normalize_ligands(lig) == [lig]
    assert _normalize_ligands([lig]) == [lig]
    assert _normalize_ligands(LigandSet(ligands=[lig])) == [lig]


def test_normalize_ligands_rejects_empty_list() -> None:
    """An empty list is not a valid Metabolism run."""
    with pytest.raises(ValueError, match="at least one ligand"):
        _normalize_ligands([])


def test_normalize_ligands_rejects_empty_ligandset() -> None:
    """An empty LigandSet is not a valid Metabolism run."""
    with pytest.raises(ValueError, match="at least one ligand"):
        _normalize_ligands(LigandSet(ligands=[]))


def test_metabolism_run_rejects_ge_threshold_ligands() -> None:
    """``run()`` rejects workflow-scale batches before create."""
    ligands = [Ligand.from_smiles("CCO")] * METABOLISM_WORKFLOW_LIGAND_THRESHOLD
    job = Metabolism(ligands=ligands)
    with pytest.raises(ValueError, match="start\\(\\) then wait\\(\\) or watch\\(\\)"):
        job.run()


def test_metabolism_construct_accepts_large_batch() -> None:
    """Constructor does not enforce a client-side ligand cap."""
    ligands = [Ligand.from_smiles("CCO")] * (METABOLISM_WORKFLOW_LIGAND_THRESHOLD + 50)
    job = Metabolism(ligands=ligands)
    assert len(job.ligands) == METABOLISM_WORKFLOW_LIGAND_THRESHOLD + 50


def test_metabolism_has_no_enzymes_attribute() -> None:
    """Enzyme selection is not part of the Metabolism API."""
    job = Metabolism(ligands=Ligand.from_smiles("CCO"))
    assert not hasattr(job, "enzymes")
    with pytest.raises(TypeError):
        Metabolism(  # ty:ignore[unexpected-keyword]
            ligands=Ligand.from_smiles("CCO"),
            enzymes=["CYP3A4"],
        )


def test_metabolism_default_name_helper() -> None:
    """Default name includes the ligand count."""
    assert _metabolism_default_name(1) == "Site of Metabolism for 1 ligand"
    assert _metabolism_default_name(12) == "Site of Metabolism for 12 ligands"


def test_metabolism_construct_sets_default_name() -> None:
    """Constructor sets ``name`` from the ligand count when omitted."""
    job = Metabolism(ligands=[Ligand.from_smiles("CCO"), Ligand.from_smiles("CCN")])
    assert job.name == "Site of Metabolism for 2 ligands"


def test_metabolism_construct_accepts_custom_name() -> None:
    """Constructor ``name=`` overrides the default label."""
    job = Metabolism(ligands=Ligand.from_smiles("CCO"), name="Custom SOM label")
    assert job.name == "Custom SOM label"


def test_metabolism_payload_includes_name() -> None:
    """Create payload carries the execution name."""
    job = Metabolism(ligands=Ligand.from_smiles("CCO"))
    payload = job._make_payload(approve_amount=None, sync=True)
    assert payload["name"] == "Site of Metabolism for 1 ligand"


def test_metabolism_make_payload_rejects_approve_amount() -> None:
    """Metabolism has no quote/billing path; approve_amount must be None."""
    job = Metabolism(ligands=Ligand.from_smiles("CCO"))
    with pytest.raises(ValueError, match="no quote/approve_amount support"):
        job._make_payload(approve_amount=0, sync=False)


def test_metabolism_get_results_classmethod_ligands_raises() -> None:
    """``Metabolism.get_results(ligands)`` points callers to ``fetch_results``."""
    lig = Ligand.from_smiles("CCO")
    with pytest.raises(TypeError, match="fetch_results"):
        Metabolism.get_results(lig)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="fetch_results"):
        Metabolism.get_results(LigandSet(ligands=[lig]))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="fetch_results"):
        Metabolism.get_results([lig])  # type: ignore[arg-type]


def test_metabolism_get_molecules_classmethod_ligands_raises() -> None:
    """``Metabolism.get_molecules(ligands)`` points callers to ``fetch_molecules``."""
    lig = Ligand.from_smiles("CCO")
    with pytest.raises(TypeError, match="fetch_molecules"):
        Metabolism.get_molecules(lig)  # type: ignore[arg-type]


def test_metabolism_start_quote_fails_fast_instead_of_running() -> None:
    """``start(quote=True)`` must not silently run for real."""
    job = Metabolism(ligands=Ligand.from_smiles("CCO"))
    with pytest.raises(ValueError, match="no quote/approve_amount support"):
        job.start(quote=True)
    assert job.status is None


def test_metabolism_start_rejects_explicit_approve_amount() -> None:
    """An explicit approve_amount also fails fast rather than running."""
    job = Metabolism(ligands=Ligand.from_smiles("CCO"))
    with pytest.raises(ValueError, match="no quote/approve_amount support"):
        job.start(approve_amount=100)
    assert job.status is None


def test_job_output_rows_reads_sites_and_molecules() -> None:
    """jobOutputs sites and molecules keys yield dict rows."""
    site = {"smiles": "CCO", "enzyme": "CYP3A4"}
    mol = {"smiles": "CCO", "confidence_tier": "high"}
    dto = {"jobOutputs": {"sites": [site], "molecules": [mol]}}
    assert _job_output_rows(dto, key="sites") == [site]
    assert _job_output_rows(dto, key="molecules") == [mol]


def test_job_output_rows_empty_when_missing() -> None:
    """Missing or malformed jobOutputs yields no rows."""
    assert _job_output_rows({}, key="sites") == []
    assert _job_output_rows({"jobOutputs": None}, key="sites") == []
    assert _job_output_rows({"jobOutputs": {"other": []}}, key="sites") == []


def test_rows_from_result_explorer_extracts_data_payloads() -> None:
    """Result-explorer records contribute their nested ``data`` dicts."""
    site = {"smiles": "CCO", "enzyme": "CYP3A4", "atom_index": 0}
    mol = {"smiles": "CCO", "confidence_tier": "high"}
    response = {
        "data": [
            {"id": "1", "result_type": "metabolismsite", "data": site},
            {"id": "2", "result_type": "metabolismmolecule", "data": mol},
            {"id": "3", "result_type": "metabolismsite", "data": "skip"},
            "not-a-dict",
        ]
    }
    assert _rows_from_result_explorer(response) == [site, mol]
    assert _rows_from_result_explorer({}) == []
    assert _rows_from_result_explorer(None) == []


def test_rows_from_result_explorer_expands_wrapped_payloads() -> None:
    """Whole-schema wrappers under metabolismmolecules/sites are flattened."""
    mol = {"ligand_id": "lig-1", "confidence_tier": "high"}
    site = {
        "ligand_id": "lig-1",
        "atom_index": 0,
        "enzyme": "CYP3A4",
        "confidence": 0.9,
    }
    response = {
        "data": [
            {"data": {"metabolismmolecules": [mol]}},
            {"data": {"metabolismsites": [site]}},
        ]
    }
    assert _rows_from_result_explorer(response) == [mol, site]


def test_ligands_from_inputs_builds_ligands() -> None:
    """Stored ligand SMILES and ids are restored; omitted id stays unset."""
    ligands = _ligands_from_inputs(
        {"ligands": [{"smiles": "CCO", "id": "lig-1"}, {"smiles": "CCN"}]}
    )
    assert [lig.smiles for lig in ligands] == ["CCO", "CCN"]
    assert ligands[0].id == "lig-1"
    assert ligands[1].id is None


def test_ligands_from_inputs_rejects_missing_rows() -> None:
    """Empty or malformed ligand rows fail rehydration."""
    with pytest.raises(ValueError, match="no ligands"):
        _ligands_from_inputs({})
    with pytest.raises(ValueError, match="not an object"):
        _ligands_from_inputs({"ligands": ["CCO"]})
    with pytest.raises(ValueError, match="no SMILES"):
        _ligands_from_inputs({"ligands": [{"id": "1"}]})


def test_ligands_from_inputs_requires_client_for_ligands_file() -> None:
    """``ligands_file`` rehydration without a files client raises."""
    with pytest.raises(ValueError, match="client with files"):
        _ligands_from_inputs({"ligands_file": "metabolism/ligand-lists/x.json"})


def test_ligands_from_list_file_bytes_parses_array() -> None:
    """Bare JSON ligand arrays rehydrate into Ligand objects."""
    from deeporigin.drug_discovery.metabolism import _ligands_from_list_file_bytes

    raw = b'[{"smiles":"CCO","id":"lig-1"},{"smiles":"CCN"}]'
    ligands = _ligands_from_list_file_bytes(raw)
    assert [lig.smiles for lig in ligands] == ["CCO", "CCN"]
    assert ligands[0].id == "lig-1"
    assert ligands[1].id is None


def test_ligands_from_list_file_bytes_rejects_bad_json() -> None:
    """Invalid UTF-8 or JSON fails with ValueError."""
    from deeporigin.drug_discovery.metabolism import _ligands_from_list_file_bytes

    with pytest.raises(ValueError, match="not valid UTF-8"):
        _ligands_from_list_file_bytes(b"\xff\xfe")
    with pytest.raises(ValueError, match="not valid JSON"):
        _ligands_from_list_file_bytes(b"{not-json")
    with pytest.raises(ValueError, match="non-empty JSON array"):
        _ligands_from_list_file_bytes(b"{}")


def test_make_inputs_stays_inline_at_cap() -> None:
    """Exactly the inline cap still sends ``ligands[]``."""
    n = METABOLISM_INLINE_LIGAND_CAP
    job = Metabolism(ligands=[Ligand.from_smiles("CCO")] * n)
    inputs = job._make_inputs()
    assert "ligands_file" not in inputs
    assert len(inputs["ligands"]) == n


def test_platform_ligand_ids_skips_missing_and_blank() -> None:
    """Only non-empty platform ids are collected."""
    with_id = Ligand.from_smiles("CCO")
    with_id.id = "lig-1"
    blank = Ligand.from_smiles("CCN")
    blank.id = "  "
    no_id = Ligand.from_smiles("CCC")
    assert _platform_ligand_ids([with_id, blank, no_id]) == ["lig-1"]


def test_unique_preserve_order() -> None:
    """Duplicates are dropped while keeping first-seen order."""
    assert _unique_preserve_order(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_ordered_dataframe_empty_keeps_columns() -> None:
    """An empty fetch returns preferred columns with no rows."""
    df = _ordered_dataframe([], columns=("ligand_id", "smiles"))
    assert list(df.columns) == ["ligand_id", "smiles"]
    assert len(df) == 0


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
    filled = _backfill_smiles_from_ligands(rows, ligands=[lig, other])
    assert filled[0]["smiles"] == "CCO"
    assert filled[1]["smiles"] == "CCN"
    assert "smiles" not in filled[2]


class _RecordingMetabolismResults:
    """Record ``Results.get`` kwargs for Metabolism query helpers."""

    def __init__(self) -> None:
        """Initialize with an empty kwargs capture."""
        self.kwargs: dict | None = None

    def get(self, **kwargs: object) -> dict:
        """Store kwargs and return an empty result-explorer payload."""
        self.kwargs = kwargs
        return {"data": []}


class _RecordingMetabolismClient:
    """Minimal client exposing ``results.get`` for unit tests."""

    def __init__(self) -> None:
        """Attach a recording Results stand-in."""
        self.results = _RecordingMetabolismResults()


def test_rows_for_ligand_ids_uses_metabolism_page_size() -> None:
    """Metabolism result-explorer queries request page_size 1000."""
    client = _RecordingMetabolismClient()
    rows = _rows_for_ligand_ids(
        client,  # type: ignore[arg-type]
        ligand_ids=["lig-1"],
        result_type="metabolismsite",
    )
    assert rows == []
    assert client.results.kwargs is not None
    assert client.results.kwargs["limit"] is None
    assert client.results.kwargs["page_size"] == METABOLISM_RESULT_EXPLORER_PAGE_SIZE
    assert METABOLISM_RESULT_EXPLORER_PAGE_SIZE == 1000
