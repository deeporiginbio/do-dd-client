"""Tests for the Entities API wrapper."""

import time
import uuid

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform import DeepOriginClient

_BRD_PDB_LOCAL = BRD_DATA_DIR / "brd.pdb"
_BRD_PDB_REMOTE = "testing/brd.pdb"
_GET_LIGAND_POLL_SECONDS = 15.0
_GET_LIGAND_POLL_INTERVAL = 0.5


def _expected_entity_tags(
    client: DeepOriginClient,
    user_tags: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build expected tags including client provenance."""
    expected: dict[str, str] = dict(user_tags or {})
    expected.setdefault("app", client._app)
    expected.setdefault("session", client._session)
    return expected


def _unique_test_smiles(*, suffix: str = "O") -> str:
    """Build a one-off aliphatic SMILES unlikely to collide with existing ligands.

    Common short SMILES (``CCO``, ``CCC``, …) often resolve to soft-deleted
    historical rows whose versioned GET still 404s. A long unique carbon chain
    forces a fresh insert.

    Args:
        suffix: Terminal heteroatom / group appended after the carbon chain.

    Returns:
        SMILES string unique for this process invocation.
    """
    n = (int(uuid.uuid4().hex[:8], 16) % 40) + 12
    return ("C" * n) + suffix


def _wait_for_ligand(client: DeepOriginClient, lig_id: str) -> dict:
    """Poll until a ligand row is readable via GET or search-by-id.

    Args:
        client: Platform client.
        lig_id: Ligand entity id returned from create/register/sync.

    Returns:
        Ligand row dict.

    Raises:
        DeepOriginException: If the row is still missing after
            ``_GET_LIGAND_POLL_SECONDS``.
    """
    deadline = time.monotonic() + _GET_LIGAND_POLL_SECONDS
    last_error: DeepOriginException | None = None
    while time.monotonic() < deadline:
        try:
            return client.entities.get_ligand(lig_id)
        except DeepOriginException as exc:
            if "404" not in str(exc):
                raise
            last_error = exc
        rows = client.entities.get_ligands([lig_id])
        if rows:
            return rows[0]
        time.sleep(_GET_LIGAND_POLL_INTERVAL)
    raise DeepOriginException(
        title="Ligand not readable after create",
        message=(
            f"get_ligand/get_ligands still missing {lig_id!r} after "
            f"{_GET_LIGAND_POLL_SECONDS:.0f}s"
            + (f": {last_error}" if last_error is not None else ".")
        ),
    ) from last_error


def test_search_entity_lv1(client: DeepOriginClient):
    """Test searching an entity."""
    response = client.entities.search("ligands")

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_entity_invalid_entity(client: DeepOriginClient):
    """Test searching with an invalid entity raises ValueError."""
    with pytest.raises(ValueError, match="Invalid entity 'invalid_table'"):
        client.entities.search("invalid_table")


def test_search_ligands_lv1(client: DeepOriginClient):
    """Test searching ligands using convenience method."""
    response = client.entities.search_ligands(limit=10)

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_ligands_molecular_weight_lv1(client: DeepOriginClient):
    """Test searching ligands with molecular weight filters."""
    response = client.entities.search_ligands(
        min_molecular_weight=250,
        max_molecular_weight=550,
        limit=10,
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_ligands_limit_caps_total_results(client: DeepOriginClient):
    """Test that limit caps the total number of results returned."""

    all_results = client.entities.search_ligands()
    total = len(all_results["data"])
    if total < 2:
        pytest.skip("Need at least 2 ligands to test limit capping")

    for cap in [1, 2]:
        response = client.entities.search_ligands(limit=cap)
        assert len(response["data"]) == cap, (
            f"Expected exactly {cap} results with limit={cap}, got {len(response['data'])}"
        )


def test_search_ligands_smiles_list_lv1(client: DeepOriginClient):
    """Test searching ligands by a list of SMILES strings."""

    existing = client.entities.search_ligands(limit=3)
    assert len(existing["data"]) >= 2, "Need at least 2 existing ligands for this test"

    known_smiles = [lig["canonical_smiles"] for lig in existing["data"][:2]]

    response = client.entities.search_ligands(smiles_list=known_smiles)

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"
    assert len(response["data"]) >= 2, "Expected at least 2 results"

    returned_smiles = {lig["canonical_smiles"] for lig in response["data"]}
    for s in known_smiles:
        assert s in returned_smiles, f"Expected {s} in results"


def test_search_ligands_smiles_list_mutually_exclusive(client: DeepOriginClient):
    """Test that smiles_list cannot be used with smiles or canonical_smiles."""

    with pytest.raises(ValueError, match="mutually exclusive"):
        client.entities.search_ligands(smiles_list=["C"], smiles="C")

    with pytest.raises(ValueError, match="mutually exclusive"):
        client.entities.search_ligands(smiles_list=["C"], canonical_smiles="C")


def test_search_ligands_empty_smiles_list(client: DeepOriginClient):
    """Test that an empty smiles_list returns an empty result immediately."""
    response = client.entities.search_ligands(smiles_list=[])

    assert response == {"data": [], "count": 0}


def test_search_proteins_lv1(client: DeepOriginClient):
    """Test searching proteins using convenience method."""
    response = client.entities.search_proteins()

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_proteins_molecular_weight_lv1(client: DeepOriginClient):
    """Test searching proteins with molecular weight filters."""
    response = client.entities.search_proteins(
        min_molecular_weight=250,
        max_molecular_weight=550,
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_search_proteins_sequence_lv1(client: DeepOriginClient):
    """Test searching proteins with sequence filter."""
    response = client.entities.search_proteins(
        sequence="MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHSLAKWKRQTLGQHDFSAGEGLYTHMKALRPDEDRLSPLHSVYVDQWDWERVMGDGERQFSTLKSTVEAIWAGIKATEAAVSEEFGLAPFLPDQIHFVHSQELLSRYPDLDAKGRERAIAKDLGAVFLVGIGGKLSDGHRHDVRAPDYDDWSTPSELGHAGLNGDILVWNPVLEDAFELSSMGIRVDADTLKHQLALTGDEDRLELEWHQALLRGEMPQTIGGGIGQSRLTMLLLQLPHIGQVQAGVWPAAVRESVPSLL"
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"


def test_list_models_lv1(client: DeepOriginClient):
    """Test listing models."""
    response = client.entities.list_models()

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "models" in response, "Expected 'models' key in response"
    assert isinstance(response["models"], list), "Expected 'models' to be a list"
    assert len(response["models"]) > 0, "Expected at least one model"
    model = response["models"][0]
    assert "tableName" in model, "Expected 'tableName' key in model"
    assert "visibility" in model, "Expected 'visibility' key in model"
    assert model["visibility"] == "public", "Expected visibility to be 'public'"


def test_create_ligand_lv1(client: DeepOriginClient):
    """Test creating a ligand; 409 (already exists) is also a pass."""
    smiles = "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12"
    try:
        response = client.entities.create_ligand(
            smiles=smiles,
            name="Compound-12345",
        )
    except DeepOriginException as e:
        if "409" in str(e):
            return
        raise

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    data = response["data"]
    assert "id" in data, "Expected 'id' key in data"
    assert "canonical_smiles" in data, "Expected 'canonical_smiles' key in data"


def test_create_protein_lv1(client: DeepOriginClient):
    """Test creating a protein; 409 (already exists) is also a pass."""
    client.files.upload(_BRD_PDB_LOCAL, _BRD_PDB_REMOTE)

    try:
        response = client.entities.create_protein(file_path=_BRD_PDB_REMOTE)
    except DeepOriginException as e:
        if "409" in str(e):
            return
        raise

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    data = response["data"]
    assert "id" in data, "Expected 'id' key in data"
    assert "file_path" in data, "Expected 'file_path' key in data"


def test_batch_create_entity_lv1(client: DeepOriginClient):
    """Test batch create via generic entity endpoint."""
    response = client.entities.batch_create(
        "ligands",
        rows=[
            {
                "smiles": "C",
                "variant_name_tag": f"test-batch-create-{uuid.uuid4()}",
            }
        ],
        returning=["id"],
    )

    assert isinstance(response, dict), "Expected a dictionary response"
    assert "data" in response, "Expected 'data' key in response"
    assert isinstance(response["data"], list), "Expected 'data' to be a list"
    assert len(response["data"]) == 1, "Expected exactly one created row"
    assert "id" in response["data"][0], "Expected 'id' in created row"
    inserted = response.get("inserted")
    if inserted is None and isinstance(response.get("meta"), dict):
        inserted = response["meta"].get("inserted")
    assert inserted == 1, "Expected exactly one inserted row"


def test_get_ligand_lv1(client: DeepOriginClient):
    """Test getting a ligand by ID."""
    smiles = "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12"
    lig = Ligand.from_smiles(smiles, name="GetLigandTest")
    lig.sync(client=client)
    assert lig.id is not None, "Expected ligand to have an id after sync"

    response = client.entities.get_ligand(id=lig.id)

    assert isinstance(response, dict), "Expected a dictionary response"
    assert response["id"] == lig.id, "Expected id to match"
    assert "smiles" in response, "Expected 'smiles' key in response"


def test_get_ligands_lv1(client: DeepOriginClient):
    """Test getting multiple ligands by IDs."""
    existing = client.entities.search_ligands()
    assert len(existing["data"]) >= 2, "Expected at least 2 existing ligands"
    ids = [record["id"] for record in existing["data"][:2]]

    data = client.entities.get_ligands(ids=ids)

    assert isinstance(data, list), "Expected a list response"
    assert len(data) == 2, f"Expected 2 ligands, got {len(data)}"
    returned_ids = {record["id"] for record in data}
    assert returned_ids == set(ids), "Expected both IDs in response"


def test_get_ligands_empty_ids(client: DeepOriginClient):
    """Test that get_ligands returns immediately for empty input."""
    data = client.entities.get_ligands(ids=[])
    assert data == []


def test_get_protein_lv1(client: DeepOriginClient):
    """Test getting a protein by ID."""
    client.files.upload(_BRD_PDB_LOCAL, _BRD_PDB_REMOTE)

    results = client.entities.search_proteins(file_path=_BRD_PDB_REMOTE)
    if not results["data"]:
        response = client.entities.create_protein(file_path=_BRD_PDB_REMOTE)
        protein_id = response["data"]["id"]
    else:
        protein_id = results["data"][0]["id"]

    response = client.entities.get_protein(id=protein_id)

    assert isinstance(response, dict), "Expected a dictionary response"
    assert response["id"] == protein_id, "Expected id to match"
    assert response["file_path"] == _BRD_PDB_REMOTE, "Expected file_path to match"
    assert response["subtable_name"] == "proteins", "Expected subtable_name to match"


def test_update_ligand_lv1(client: DeepOriginClient):
    """Test updating a ligand mol_file and name bumps version."""
    tag = f"upd-{uuid.uuid4().hex[:12]}"
    create = client.entities.create_ligand(
        smiles="CC(C)O",
        name=f"update-ligand-{tag}",
        variant_name_tag=tag,
    )
    lig_id = create["data"]["id"]
    version_before = create["data"]["version"]

    try:
        response = client.entities.update_ligand(
            lig_id,
            mol_file="testing/brd-2.sdf",
            name="renamed-ligand",
        )

        assert "data" in response
        row = response["data"][0]
        assert row["mol_file"] == "testing/brd-2.sdf"
        assert row["name"] == "renamed-ligand"
        assert row["version"] == version_before + 1
    finally:
        client.entities.delete(entity="ligands", entity_id=lig_id)


def test_update_protein_lv1(client: DeepOriginClient):
    """Test updating a protein file_path bumps version."""
    client.files.upload(_BRD_PDB_LOCAL, _BRD_PDB_REMOTE)
    create = client.entities.create_protein(file_path=_BRD_PDB_REMOTE)
    protein_id = create["data"]["id"]
    version_before = create["data"]["version"]
    new_path = f"testing/updated-{uuid.uuid4().hex[:8]}.pdb"

    try:
        response = client.entities.update_protein(protein_id, file_path=new_path)

        row = response["data"][0]
        assert row["file_path"] == new_path
        assert row["version"] == version_before + 1
    finally:
        client.entities.update_protein(protein_id, file_path=_BRD_PDB_REMOTE)


def test_batch_update_ligands_lv1(client: DeepOriginClient):
    """Test batch updating multiple ligands."""
    ids: list[str] = []
    try:
        for i in range(2):
            tag = f"batch-upd-{uuid.uuid4().hex[:12]}-{i}"
            create = client.entities.create_ligand(  # ty:ignore[unresolved-attribute]
                smiles=f"C{'C' * i}O",
                variant_name_tag=tag,
            )
            ids.append(create["data"]["id"])

        response = client.entities.batch_update(  # ty:ignore[unresolved-attribute]
            "ligands",
            updates=[
                {"id": ids[0], "set": {"name": "batch-a"}},
                {"id": ids[1], "set": {"name": "batch-b"}},
            ],
            returning=["id", "name", "version"],
        )

        assert len(response["data"]) == 2
        names = {row["name"] for row in response["data"]}
        assert names == {"batch-a", "batch-b"}
        assert response["meta"]["affected"] == 2
    finally:
        for lig_id in ids:
            client.entities.delete(entity="ligands", entity_id=lig_id)


def test_update_empty_set_dict_raises(client: DeepOriginClient):
    """Test that update with empty set_dict raises ValueError."""
    with pytest.raises(ValueError, match="at least one field"):
        client.entities.update("ligands", "08FAKEID00000", set_dict={})


def test_update_ligand_not_found_lv1(client: DeepOriginClient):
    """Test that updating a non-existent ligand raises DeepOriginException."""
    # Soft-deleted ligands remain addressable on the platform (immutable versioning),
    # so use a fabricated ID that was never created.
    missing_id = f"08{uuid.uuid4().hex[:11].upper()}"

    with pytest.raises(DeepOriginException):
        client.entities.update_ligand(missing_id, name="missing")  # ty:ignore[unresolved-attribute]


def test_create_ligand_with_tags_lv1(client: DeepOriginClient):
    """Create ligand returns tags (incl. provenance) on the write response."""
    tag = f"tags-{uuid.uuid4().hex[:12]}"
    entity_tags = {"campaign": tag}
    smiles = _unique_test_smiles(suffix="O")
    create = client.entities.create_ligand(
        smiles=smiles,
        name=f"tagged-ligand-{tag}",
        tags=entity_tags,
    )
    lig_id = create["data"]["id"]
    expected = _expected_entity_tags(client, entity_tags)
    try:
        assert create["data"].get("tags") == expected
    finally:
        try:
            client.entities.delete(entity="ligands", entity_id=lig_id)
        except DeepOriginException as _e:
            if "404" not in str(_e):
                raise


def test_update_ligand_with_tags_lv1(client: DeepOriginClient):
    """Update ligand can set tags (jsonb object)."""
    tag = f"upd-tags-{uuid.uuid4().hex[:12]}"
    smiles = _unique_test_smiles(suffix="N")
    create = client.entities.create_ligand(smiles=smiles, name=f"tag-upd-{tag}")
    lig_id = create["data"]["id"]
    entity_tags = {"batch": tag}
    expected = _expected_entity_tags(client, entity_tags)
    try:
        updated = client.entities.update_ligand(lig_id, tags=entity_tags)
        updated_data = updated.get("data") if isinstance(updated, dict) else None
        if isinstance(updated_data, list):
            updated_row = updated_data[0] if updated_data else None
        else:
            updated_row = updated_data
        assert isinstance(updated_row, dict)
        assert updated_row.get("tags") == expected
    finally:
        try:
            client.entities.delete(entity="ligands", entity_id=lig_id)
        except DeepOriginException as _e:
            if "404" not in str(_e):
                raise


def test_create_ligand_stamps_provenance_without_tags_lv1(client: DeepOriginClient):
    """Create ligand without tags still writes app/session provenance."""
    tag = f"prov-{uuid.uuid4().hex[:12]}"
    smiles = _unique_test_smiles(suffix="F")
    create = client.entities.create_ligand(smiles=smiles, name=f"prov-lig-{tag}")
    lig_id = create["data"]["id"]
    expected = _expected_entity_tags(client)
    try:
        assert create["data"].get("tags") == expected
    finally:
        try:
            client.entities.delete(entity="ligands", entity_id=lig_id)
        except DeepOriginException as _e:
            if "404" not in str(_e):
                raise


def test_ligand_register_passes_tags_lv1(client: DeepOriginClient):
    """Ligand.register forwards Entity.tags to create_ligand."""
    tag = f"reg-{uuid.uuid4().hex[:12]}"
    entity_tags = {"origin": tag}
    smiles = _unique_test_smiles(suffix="Cl")
    ligand = Ligand.from_smiles(smiles, tags=entity_tags)
    ligand.register(client=client)
    assert ligand.id is not None
    expected = _expected_entity_tags(client, entity_tags)
    try:
        row = _wait_for_ligand(client, ligand.id)
        assert row["tags"] == expected
    finally:
        try:
            client.entities.delete(entity="ligands", entity_id=ligand.id)
        except DeepOriginException as _e:
            if "404" not in str(_e):
                raise


def test_ligand_sync_applies_tags_to_existing_row_lv1(client: DeepOriginClient):
    """When sync finds an existing ligand, ``Entity.tags`` are patched on."""
    tag = f"sync-tags-{uuid.uuid4().hex[:12]}"
    smiles = _unique_test_smiles(suffix="Br")
    create = client.entities.create_ligand(smiles=smiles, name=f"sync-tag-{tag}")
    lig_id = create["data"]["id"]
    entity_tags = {"patched": tag}
    expected = _expected_entity_tags(client, entity_tags)
    try:
        ligand = Ligand.from_smiles(smiles, tags=entity_tags)
        ligand.sync(client=client)
        row = _wait_for_ligand(client, lig_id)
        assert row["tags"] == expected
    finally:
        try:
            client.entities.delete(entity="ligands", entity_id=lig_id)
        except DeepOriginException as _e:
            if "404" not in str(_e):
                raise
