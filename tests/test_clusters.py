"""Tests for Clusters API wrapper."""

from tests.utils import client  # noqa: F401


def test_get_default_cluster_id(client):  # noqa: F811
    """Test that get_default_cluster_id returns the first cluster."""
    cluster_id = client.clusters.get_default_cluster_id()
    assert cluster_id is not None
    assert isinstance(cluster_id, str)


def test_get_default_cluster_id_cached(client):  # noqa: F811
    """Test that get_default_cluster_id caches the result."""
    cluster_id_1 = client.clusters.get_default_cluster_id()
    cluster_id_2 = client.clusters.get_default_cluster_id()
    assert cluster_id_1 == cluster_id_2


def test_get_default_cluster_id_includes_dev(client):  # noqa: F811
    """Test that get_default_cluster_id includes dev clusters."""
    # The mock server returns dev cluster first, so we should get it
    cluster_id = client.clusters.get_default_cluster_id()
    # Verify it's the first cluster from the list
    clusters = client.clusters.list()
    first_cluster_id = clusters["data"][0]["id"]
    assert cluster_id == first_cluster_id
