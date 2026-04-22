"""Tests for the Datasets API wrapper."""

from deeporigin.platform import DeepOriginClient


def test_create_dataset(client: DeepOriginClient):
    """Create a dataset and verify the response shape."""
    result = client.datasets.create(
        name="Test Dataset",
        file_path="/datasets/test/data.csv",
        dataset_key="test.dataset",
        dataset_version="1.0.0",
        summary="A test dataset",
        tags=["HTS", "FBDD"],
    )
    assert "data" in result
    assert result["data"]["name"] == "Test Dataset"
    assert result["data"]["dataset_key"] == "test.dataset"
    assert result["data"]["tags"] == ["HTS", "FBDD"]


def test_search_datasets(client: DeepOriginClient):
    """Search datasets returns results."""
    client.datasets.create(
        name="Search Target",
        file_path="/datasets/search/data.csv",
        dataset_key="test.searchable",
        dataset_version="1.0.0",
    )
    result = client.datasets.search()
    assert "data" in result
    assert isinstance(result["data"], list)
    assert len(result["data"]) > 0


def test_search_datasets_with_text_search(client: DeepOriginClient):
    """Search datasets using the fulltext search parameter."""
    client.datasets.create(
        name="Kinase Inhibitors",
        file_path="/datasets/kinase/data.csv",
        dataset_key="test.kinase",
        dataset_version="1.0.0",
        summary="EGFR kinase inhibitor screening data",
    )
    result = client.datasets.search(search="kinase")
    assert "data" in result
    assert len(result["data"]) > 0
    names = [d["name"] for d in result["data"]]
    assert any("Kinase" in n for n in names)


def test_search_datasets_with_total_count(client: DeepOriginClient):
    """with_total_count returns meta.total_count and no data rows."""
    client.datasets.create(
        name="Count Target",
        file_path="/datasets/count/data.csv",
        dataset_key="test.countable",
        dataset_version="1.0.0",
    )
    result = client.datasets.search(with_total_count=True)
    assert result["data"] == []
    assert "total_count" in result["meta"]
    assert result["meta"]["total_count"] > 0


def test_search_datasets_with_tag_filter(client: DeepOriginClient):
    """Search datasets filtered by tags (AND semantics)."""
    client.datasets.create(
        name="Tagged Dataset",
        file_path="/datasets/tagged/data.csv",
        dataset_key="test.tagged",
        dataset_version="1.0.0",
        tags=["HTS", "FBDD", "Kinase"],
    )
    result = client.datasets.search(filter_dict={"tags": {"in": ["HTS", "FBDD"]}})
    assert "data" in result
    assert len(result["data"]) > 0
    for ds in result["data"]:
        if ds.get("tags"):
            assert "HTS" in ds["tags"]
            assert "FBDD" in ds["tags"]


def test_get_dataset(client: DeepOriginClient):
    """Get a dataset by ID."""
    created = client.datasets.create(
        name="Get Target",
        file_path="/datasets/get/data.csv",
        dataset_key="test.gettable",
        dataset_version="1.0.0",
    )
    dataset_id = created["data"]["id"]
    result = client.datasets.get(dataset_id)
    assert "data" in result
    assert result["data"]["id"] == dataset_id
    assert result["data"]["name"] == "Get Target"


def test_update_dataset(client: DeepOriginClient):
    """Update a dataset record."""
    created = client.datasets.create(
        name="Update Target",
        file_path="/datasets/update/data.csv",
        dataset_key="test.updatable",
        dataset_version="1.0.0",
    )
    dataset_id = created["data"]["id"]
    result = client.datasets.update(dataset_id, set_dict={"description": "Updated"})
    assert "data" in result
    assert result["data"]["description"] == "Updated"


def test_trigger_import(client: DeepOriginClient):
    """Trigger an import and verify executionId is returned."""
    created = client.datasets.create(
        name="Import Target",
        file_path="/datasets/import/data.csv",
        dataset_key="test.importable",
        dataset_version="1.0.0",
        dataset_schema={"type": "object", "properties": {}},
    )
    dataset_id = created["data"]["id"]
    result = client.datasets.trigger_import(
        dataset_id,
        org_key="test-org",
        cluster_id="cluster-1",
        batch_size=500,
    )
    assert "executionId" in result
    assert result["executionId"].startswith("exec-")
