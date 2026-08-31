"""Tests for :class:`~deeporigin.drug_discovery.uniprot_discovery.UniprotDiscovery`."""

from __future__ import annotations

import pytest

from deeporigin.drug_discovery import (
    BRD_DATA_DIR,
    Protein,
    UniprotDiscovery,
    UniprotDiscoveryCandidate,
)
from deeporigin.drug_discovery.uniprot_discovery import (
    UniprotDiscoveryCandidate as UniprotDiscoveryCandidateCls,
)
from deeporigin.drug_discovery.uniprot_discovery import (
    _candidates_from_dto,
)
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from tests.mock_server.routers.data_platform import MOCK_DEFAULT_PROJECT_ID


def _stub_from_pdb_id(pdb_id: str, struct_ind: int = 0) -> Protein:
    """Return a local BRD protein stamped with ``pdb_id`` (no RCSB network)."""
    del struct_ind
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.pdb_id = pdb_id.upper()
    protein.name = pdb_id.upper()
    return protein


def test_uniprot_discovery_rejects_malformed_accession(
    client: DeepOriginClient,
) -> None:
    """Constructor validates UniProtKB accession shape."""
    with pytest.raises(ValueError, match="UniProtKB"):
        UniprotDiscovery(uniprot_accession="EGFR", client=client)


def test_uniprot_discovery_normalizes_accession(client: DeepOriginClient) -> None:
    """Accessions are uppercased after validation."""
    job = UniprotDiscovery(uniprot_accession="p00533", client=client)
    assert job.uniprot_accession == "P00533"
    assert job.tool_version == "latest"
    assert job.tool_key == TOOL_KEYS_AND_VERSIONS["uniprot_discovery"]["tool_key"]


def test_uniprot_discovery_make_payload(client: DeepOriginClient) -> None:
    """Payload sends only ``uniprot_accession``."""
    job = UniprotDiscovery(
        uniprot_accession="P00533",
        client=client,
        name="ud-test",
    )
    payload = job._make_payload(approve_amount=None, sync=True)

    assert payload["sync"] is True
    assert payload["name"] == "ud-test"
    assert payload["inputs"] == {"uniprot_accession": "P00533"}


def test_uniprot_discovery_candidate_from_json_round_trip() -> None:
    """``from_json`` maps required and optional tool fields."""
    raw = {
        "coverage_score": 0.9,
        "field_status": {
            "coverage": "value",
            "inhibitor": "value",
            "method": "value",
            "organism": "value",
            "resolution": "value",
            "rfree": "value",
        },
        "grade": "A",
        "inhibitor_score": 1.0,
        "method_score": 0.95,
        "organism_score": 1.0,
        "pdb_id": "1m17",
        "recommended": True,
        "resolution_score": 0.75,
        "rfree_score": 0.8,
        "weighted_score": 0.9,
        "resolution": 1.5,
    }
    row = UniprotDiscoveryCandidateCls.from_json(raw)
    assert isinstance(row, UniprotDiscoveryCandidate)
    assert row.pdb_id == "1M17"
    assert row.recommended is True
    assert row.coverage is None


def test_uniprot_discovery_candidate_from_json_rejects_non_numeric_score() -> None:
    """A mistyped required numeric field raises ``DeepOriginException``, not a bare ``ValueError``."""
    raw = {
        "coverage_score": "not-a-number",
        "field_status": {},
        "grade": "A",
        "inhibitor_score": 1.0,
        "method_score": 0.95,
        "organism_score": 1.0,
        "pdb_id": "1m17",
        "recommended": True,
        "resolution_score": 0.75,
        "rfree_score": 0.8,
        "weighted_score": 0.9,
    }
    with pytest.raises(DeepOriginException, match="coverage_score"):
        UniprotDiscoveryCandidateCls.from_json(raw)


def test_uniprot_discovery_candidate_from_json_rejects_malformed_pdb_id() -> None:
    """A malformed ``pdb_id`` raises ``DeepOriginException``, not a bare ``ValueError``."""
    raw = {
        "coverage_score": 0.9,
        "field_status": {},
        "grade": "A",
        "inhibitor_score": 1.0,
        "method_score": 0.95,
        "organism_score": 1.0,
        "pdb_id": "not-a-valid-pdb-id",
        "recommended": True,
        "resolution_score": 0.75,
        "rfree_score": 0.8,
        "weighted_score": 0.9,
    }
    with pytest.raises(DeepOriginException, match="pdb_id"):
        UniprotDiscoveryCandidateCls.from_json(raw)


def test_candidates_from_dto_allows_empty() -> None:
    """Empty ``candidates`` is valid tool output."""
    assert _candidates_from_dto({"jobOutputs": {"candidates": []}}) == []


def test_candidates_from_dto_rejects_missing_key() -> None:
    """Missing ``candidates`` key raises."""
    with pytest.raises(DeepOriginException, match="candidates"):
        _candidates_from_dto({"jobOutputs": {}})


def test_uniprot_discovery_run(client: DeepOriginClient) -> None:
    """``run()`` returns ranked mock candidates with one recommended."""
    job = UniprotDiscovery(uniprot_accession="P00533", client=client)
    rows = job.run()

    assert rows is not None
    assert len(rows) == 2
    assert rows[0].recommended is True
    assert rows[0].pdb_id == "1M17"
    assert rows[0].grade == "A"
    assert rows[1].pdb_id == "4WR2"
    assert job.candidates is not None
    assert job.id is not None
    assert job.status in {"Completed", "Succeeded"}


def test_uniprot_discovery_run_empty_candidates(client: DeepOriginClient) -> None:
    """Mock accession ``P99999`` returns an empty candidate list."""
    job = UniprotDiscovery(uniprot_accession="P99999", client=client)
    rows = job.run()
    assert rows == []


def test_uniprot_discovery_run_quote_returns_none(
    client: DeepOriginClient,
) -> None:
    """Quote-only ``run`` returns ``None`` and leaves status Quoted."""
    job = UniprotDiscovery(uniprot_accession="P00533", client=client)
    assert job.run(quote=True) is None
    assert job.status == "Quoted"
    assert job.id is not None


def test_uniprot_discovery_from_dto_restores_accession(
    client: DeepOriginClient,
) -> None:
    """``from_dto`` restores accession and cached candidates."""
    job = UniprotDiscovery(uniprot_accession="P00533", client=client)
    rows = job.run()
    assert rows is not None

    dto = client.executions.get(job.id)
    restored = UniprotDiscovery.from_dto(dto, client=client)
    assert restored.uniprot_accession == "P00533"
    assert restored.id == job.id
    assert restored.candidates is not None
    assert len(restored.candidates) == 2


def test_import_proteins_requires_project(client: DeepOriginClient) -> None:
    """Import fails closed when no project id can be resolved."""
    assert client.project_id is None
    job = UniprotDiscovery(uniprot_accession="P00533", client=client)
    job.run()
    with pytest.raises(DeepOriginException, match="[Pp]roject"):
        job.import_proteins()


def test_import_proteins_rejects_unknown_pdb_ids(
    client: DeepOriginClient,
) -> None:
    """Selected PDB IDs must appear in this accession's candidates."""
    client.project_id = MOCK_DEFAULT_PROJECT_ID
    job = UniprotDiscovery(uniprot_accession="P00533", client=client)
    job.run()
    with pytest.raises(DeepOriginException, match="not in UniProt discovery"):
        job.import_proteins(["1ABC"])


def test_import_proteins_rejects_empty_candidates(
    client: DeepOriginClient,
) -> None:
    """Cannot import when discovery returns no candidates."""
    client.project_id = MOCK_DEFAULT_PROJECT_ID
    job = UniprotDiscovery(uniprot_accession="P99999", client=client)
    with pytest.raises(DeepOriginException, match="No experimental PDB"):
        job.import_proteins()


def test_import_proteins_recommended(
    client: DeepOriginClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default import syncs the recommended PDB with accession set."""
    client.project_id = MOCK_DEFAULT_PROJECT_ID
    monkeypatch.setattr(Protein, "from_pdb_id", staticmethod(_stub_from_pdb_id))

    job = UniprotDiscovery(uniprot_accession="P00533", client=client)
    proteins = job.import_proteins()

    assert len(proteins) == 1
    protein = proteins[0]
    assert protein.pdb_id == "1M17"
    assert protein.uniprot_accession == "P00533"
    assert protein.project_id == MOCK_DEFAULT_PROJECT_ID
    assert protein.id is not None

    fetched = client.entities.get_protein(id=protein.id)
    assert fetched.get("uniprot_accession") == "P00533"
    assert fetched.get("pdb_id") == "1M17"


def test_import_proteins_selected_list(
    client: DeepOriginClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit ``pdb_ids`` imports multiple candidate rows."""
    client.project_id = MOCK_DEFAULT_PROJECT_ID
    monkeypatch.setattr(Protein, "from_pdb_id", staticmethod(_stub_from_pdb_id))

    job = UniprotDiscovery(uniprot_accession="P00533", client=client)
    proteins = job.import_proteins(["4wr2", "1M17"])

    assert [p.pdb_id for p in proteins] == ["4WR2", "1M17"]
    assert all(p.uniprot_accession == "P00533" for p in proteins)


def test_protein_from_uniprot_sugar(
    client: DeepOriginClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Protein.from_uniprot`` returns the recommended synced protein."""
    client.project_id = MOCK_DEFAULT_PROJECT_ID
    monkeypatch.setattr(Protein, "from_pdb_id", staticmethod(_stub_from_pdb_id))

    protein = Protein.from_uniprot("P00533", client=client)
    assert protein.pdb_id == "1M17"
    assert protein.uniprot_accession == "P00533"
    assert protein.id is not None


def test_protein_register_persists_uniprot_accession(
    client: DeepOriginClient,
) -> None:
    """``register`` writes ``uniprot_accession`` through create_protein."""
    client.project_id = MOCK_DEFAULT_PROJECT_ID
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.pdb_id = "1M17"
    protein.uniprot_accession = "P00533"
    protein.project_id = MOCK_DEFAULT_PROJECT_ID
    protein.register(client=client)

    fetched = client.entities.get_protein(id=protein.id)
    assert fetched.get("uniprot_accession") == "P00533"


def test_protein_sync_updates_uniprot_accession_on_existing(
    client: DeepOriginClient,
) -> None:
    """``sync`` updates accession when reusing an existing file_path row."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.pdb_id = "1M17"
    # Unscoped sync so the mock remaps any uploaded path to the canonical row.
    protein.sync(client=client)
    assert protein.id is not None

    protein.uniprot_accession = "P00533"
    protein.sync(client=client)

    fetched = client.entities.get_protein(id=protein.id)
    assert fetched.get("uniprot_accession") == "P00533"


def test_protein_from_id_hydrates_uniprot_accession(
    client: DeepOriginClient,
) -> None:
    """``from_id`` restores ``uniprot_accession`` from the platform row."""
    client.project_id = MOCK_DEFAULT_PROJECT_ID
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.uniprot_accession = "P00533"
    protein.project_id = MOCK_DEFAULT_PROJECT_ID
    protein.register(client=client)

    restored = Protein.from_id(protein.id, client=client, download=False)
    assert restored.uniprot_accession == "P00533"
