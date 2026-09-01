"""Unit tests for LigandSearch input validation and payload/result handling.

These exercise the client in isolation: no platform calls, and a stub client
that never dials out. End-to-end coverage against the mock server belongs in a
``test_ligand_search_local.py`` alongside the other ``*_local`` suites.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from deeporigin.drug_discovery import Ligand, LigandSearch
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.constants import (
    LIGAND_SEARCH_DEFAULT_THRESHOLD,
    LIGAND_SEARCH_MAX_LIMIT,
    LIGAND_SEARCH_MODE_LIBRARIES,
    LIGAND_SEARCH_RESULTS_CSV_COLUMNS,
)

_QUERY_SMILES = "CC(=O)Nc1ccc(O)cc1"
_CSV_PATH = "tool-runs/exec-123/results.csv"


@pytest.fixture
def stub_client() -> DeepOriginClient:
    """A client that satisfies the type check but is never dialled."""
    return DeepOriginClient.__new__(DeepOriginClient)


def _search(stub_client: DeepOriginClient, **kwargs: Any) -> LigandSearch:
    """Build a LigandSearch with sensible defaults for the mode under test."""
    kwargs.setdefault("query", _QUERY_SMILES)
    kwargs.setdefault("search_mode", "SIMILARITY_2D")
    kwargs.setdefault("libraries", ["enamine_hll"])
    return LigandSearch(client=stub_client, **kwargs)


# -- mode / library capability matrix -----------------------------------------


def test_every_mode_has_at_least_one_capable_library() -> None:
    """The capability matrix never leaves a mode unservable."""
    for mode, libraries in LIGAND_SEARCH_MODE_LIBRARIES.items():
        assert libraries, f"{mode} has no capable library"


@pytest.mark.parametrize("mode", ["EXACT", "SUBSTRUCTURE"])
def test_onepot_cannot_serve_exact_or_substructure(
    stub_client: DeepOriginClient, mode: str
) -> None:
    """Onepot has no bulk export and no InChIKey endpoint, so it serves neither."""
    kwargs: dict[str, Any] = {"search_mode": mode, "libraries": ["onepot"]}
    if mode == "SUBSTRUCTURE":
        kwargs["smarts"] = "c1ccccc1"
    else:
        kwargs["query"] = _QUERY_SMILES
    with pytest.raises(ValueError, match="No selected library can serve"):
        LigandSearch(client=stub_client, **kwargs)


def test_a_mixed_selection_is_allowed(stub_client: DeepOriginClient) -> None:
    """One capable library is enough; the rest warn and contribute zero hits."""
    search = _search(
        stub_client, search_mode="SIMILARITY_2D", libraries=["enamine_hll", "onepot"]
    )
    assert search.libraries == ["enamine_hll", "onepot"]


def test_synthon_accepts_onepot_alongside_real_synthons(
    stub_client: DeepOriginClient,
) -> None:
    """A SYNTHON query searches un-enumerated space and Onepot together."""
    search = _search(
        stub_client,
        search_mode="SYNTHON",
        libraries=["onepot", "enamine_real_synthons"],
    )
    assert set(search.libraries) == {"onepot", "enamine_real_synthons"}


def test_unknown_library_is_rejected(stub_client: DeepOriginClient) -> None:
    """A typo in a library id fails before any platform call."""
    with pytest.raises(ValueError, match="Unknown libraries"):
        _search(stub_client, libraries=["enamine_hll", "enamien_screening"])


def test_empty_libraries_is_rejected(stub_client: DeepOriginClient) -> None:
    """A search must name at least one library."""
    with pytest.raises(ValueError, match="at least one vendor library"):
        _search(stub_client, libraries=[])


# -- query validation ----------------------------------------------------------


def test_substructure_requires_a_pattern(stub_client: DeepOriginClient) -> None:
    """SUBSTRUCTURE with neither smarts nor a SMILES query is rejected."""
    with pytest.raises(ValueError, match="SUBSTRUCTURE requires a smarts pattern"):
        LigandSearch(
            client=stub_client, search_mode="SUBSTRUCTURE", libraries=["enamine_hll"]
        )


def test_smarts_is_rejected_outside_substructure(
    stub_client: DeepOriginClient,
) -> None:
    """smarts on a similarity search is a mistake, not a silently ignored field."""
    with pytest.raises(ValueError, match="smarts is only used by SUBSTRUCTURE"):
        _search(stub_client, smarts="c1ccccc1")


def test_query_accepts_a_smiles_string(stub_client: DeepOriginClient) -> None:
    """A bare SMILES string is promoted to a Ligand."""
    search = _search(stub_client, query=_QUERY_SMILES)
    assert isinstance(search.query, Ligand)
    assert search.query.smiles == _QUERY_SMILES


def test_missing_query_is_rejected(stub_client: DeepOriginClient) -> None:
    """Every mode but self_test needs something to search for."""
    with pytest.raises(ValueError, match="requires a query molecule"):
        LigandSearch(client=stub_client, search_mode="EXACT", libraries=["enamine_hll"])


def test_self_test_needs_no_query_or_libraries(
    stub_client: DeepOriginClient,
) -> None:
    """self_test searches an index baked into the image, ignoring both."""
    search = LigandSearch(client=stub_client, search_mode="EXACT", self_test=True)
    assert search._make_payload()["inputs"]["self_test"] is True


# -- numeric bounds ------------------------------------------------------------


@pytest.mark.parametrize("threshold", [-0.1, 1.1])
def test_threshold_must_be_a_similarity(
    stub_client: DeepOriginClient, threshold: float
) -> None:
    """Tanimoto similarity is bounded to [0, 1]."""
    with pytest.raises(ValueError, match="threshold must be between 0 and 1"):
        _search(stub_client, threshold=threshold)


@pytest.mark.parametrize("limit", [0, LIGAND_SEARCH_MAX_LIMIT + 1])
def test_limit_is_bounded_by_the_cap(stub_client: DeepOriginClient, limit: int) -> None:
    """The platform applies a hard result cap; asking for more is rejected."""
    with pytest.raises(ValueError, match="limit must be between"):
        _search(stub_client, limit=limit)


def test_threshold_defaults_to_the_measured_value(
    stub_client: DeepOriginClient,
) -> None:
    """0.4, not 0.7 -- at 0.7 a realistic query returns nothing at all."""
    assert _search(stub_client).threshold == LIGAND_SEARCH_DEFAULT_THRESHOLD


def test_unknown_fingerprint_is_rejected(stub_client: DeepOriginClient) -> None:
    """Only ECFP4 and ErG exist."""
    with pytest.raises(ValueError, match="Unknown fingerprint"):
        _search(stub_client, fingerprint="MACCS")


def test_unknown_search_mode_is_rejected(stub_client: DeepOriginClient) -> None:
    """An unknown mode fails before any platform call."""
    with pytest.raises(ValueError, match="Unknown search_mode"):
        _search(stub_client, search_mode="SIMILARITY_3D")


# -- payload shape -------------------------------------------------------------


def test_similarity_payload_carries_fingerprint_and_threshold(
    stub_client: DeepOriginClient,
) -> None:
    """SIMILARITY_2D sends the two levers it actually uses."""
    inputs = _search(stub_client)._make_payload(sync=True)["inputs"]
    assert inputs["search_mode"] == "SIMILARITY_2D"
    assert inputs["fingerprint"] == "ECFP4"
    assert inputs["threshold"] == LIGAND_SEARCH_DEFAULT_THRESHOLD
    assert inputs["query"] == {"smiles": _QUERY_SMILES}
    assert "synthon_prefilter_size" not in inputs


def test_synthon_payload_carries_the_synthon_levers(
    stub_client: DeepOriginClient,
) -> None:
    """SYNTHON sends prefilter size and reaction rules; nothing else does."""
    search = _search(
        stub_client, search_mode="SYNTHON", libraries=["enamine_real_synthons"]
    )
    inputs = search._make_payload(sync=False)["inputs"]
    assert inputs["synthon_prefilter_size"] == 100
    assert inputs["reaction_rules"] == "brics"
    assert "fingerprint" not in inputs


def test_substructure_payload_sends_the_pattern(
    stub_client: DeepOriginClient,
) -> None:
    """The SMARTS pattern travels inside the query object."""
    search = LigandSearch(
        client=stub_client,
        search_mode="SUBSTRUCTURE",
        libraries=["enamine_hll"],
        smarts="c1ccccc1Br",
    )
    assert search._make_payload()["inputs"]["query"] == {"smarts": "c1ccccc1Br"}


def test_payload_carries_the_ligand_id_when_set(
    stub_client: DeepOriginClient,
) -> None:
    """A platform ligand id is echoed back on the pointer row."""
    ligand = Ligand.from_smiles(_QUERY_SMILES)
    ligand.id = "lig-42"
    inputs = _search(stub_client, query=ligand)._make_payload()["inputs"]
    assert inputs["query"]["ligand_id"] == "lig-42"


# -- results -------------------------------------------------------------------


class _FakeFiles:
    """Writes a small results CSV instead of downloading one."""

    def __init__(self, rows: int) -> None:
        self.rows = rows
        self.requested: str | None = None

    def download(self, *, remote_path: str, local_path: str) -> None:
        self.requested = remote_path
        frame = pd.DataFrame(
            {column: [""] * self.rows for column in LIGAND_SEARCH_RESULTS_CSV_COLUMNS}
        )
        frame.to_csv(local_path, index=False)


class _FakeClient:
    """Minimal client surface used by get_results / download_results."""

    def __init__(self, dto: dict[str, Any], rows: int = 3) -> None:
        self._dto = dto
        self.files = _FakeFiles(rows)

    @property
    def executions(self) -> Any:
        outer = self

        class _Executions:
            def get(self, _id: str) -> dict[str, Any]:
                return outer._dto

        return _Executions()


def _pointer_dto(**overrides: Any) -> dict[str, Any]:
    """A completed execution DTO carrying one results pointer row."""
    row: dict[str, Any] = {
        "csv_file_path": _CSV_PATH,
        "cap_hit": False,
        "row_count": 3,
        "libraries": "enamine_hll",
        "search_mode": "SIMILARITY_2D",
    }
    row.update(overrides)
    return {"jobOutputs": {"similarity_search_results": [row]}}


def test_get_results_downloads_and_parses_the_csv(
    stub_client: DeepOriginClient,
) -> None:
    """The pointer row names a CSV; get_results returns it as a DataFrame."""
    search = _search(stub_client)
    search._id = "exec-123"
    search.client = _FakeClient(_pointer_dto())

    frame = search.get_results()

    assert list(frame.columns) == list(LIGAND_SEARCH_RESULTS_CSV_COLUMNS)
    assert len(frame) == 3
    assert search.results_csv_path == _CSV_PATH
    assert search.row_count == 3
    assert search.cap_hit is False


def test_get_results_records_a_truncated_run(
    stub_client: DeepOriginClient,
) -> None:
    """cap_hit tells the caller the CSV is not the whole answer."""
    search = _search(stub_client)
    search._id = "exec-123"
    search.client = _FakeClient(_pointer_dto(cap_hit=True, row_count=1000))

    search.get_results()

    assert search.cap_hit is True
    assert search.row_count == LIGAND_SEARCH_MAX_LIMIT


def test_get_results_without_a_pointer_row_raises(
    stub_client: DeepOriginClient,
) -> None:
    """An execution that published nothing is an error, not an empty frame."""
    search = _search(stub_client)
    search._id = "exec-123"
    search.client = _FakeClient({"jobOutputs": {}})

    with pytest.raises(DeepOriginException, match="No search results"):
        search.get_results()


def test_get_results_without_a_csv_path_raises(
    stub_client: DeepOriginClient,
) -> None:
    """A pointer row that names no CSV is a malformed result."""
    search = _search(stub_client)
    search._id = "exec-123"
    dto = {"jobOutputs": {"similarity_search_results": [{"cap_hit": False}]}}
    search.client = _FakeClient(dto)

    with pytest.raises(DeepOriginException, match="No results CSV"):
        search.get_results()


def test_download_results_writes_the_raw_csv(
    stub_client: DeepOriginClient, tmp_path: Path
) -> None:
    """download_results hands back the file for the import-dataset step."""
    search = _search(stub_client)
    search._id = "exec-123"
    fake = _FakeClient(_pointer_dto())
    search.client = fake

    target = str(tmp_path / "hits.csv")
    assert search.download_results(target) == target
    assert fake.files.requested == _CSV_PATH
    assert pd.read_csv(target).shape[0] == 3


# -- rehydration ---------------------------------------------------------------


def test_from_dto_rejects_an_unknown_mode() -> None:
    """A stored payload with a mode this SDK does not know fails loudly."""
    dto = {
        "executionId": "exec-1",
        "userInputs": {"search_mode": "SIMILARITY_4D"},
        "tool": {"key": "deeporigin.ligand-search", "version": "latest"},
    }
    with pytest.raises(ValueError, match="unknown search_mode"):
        LigandSearch.from_dto(dto)
