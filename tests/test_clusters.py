"""Tests for Clusters API wrapper."""

from deeporigin.platform.client import DeepOriginClient


def test_get_default_cluster_id_lv1(client: DeepOriginClient):
    """Test that get_default_cluster_id returns the first cluster."""
    cluster_id = client.clusters.get_default_cluster_id()
    assert cluster_id is not None
    assert isinstance(cluster_id, str)


def test_get_default_cluster_id_cached_lv1(client: DeepOriginClient):
    """Test that get_default_cluster_id caches the result."""
    cluster_id_1 = client.clusters.get_default_cluster_id()
    cluster_id_2 = client.clusters.get_default_cluster_id()
    assert cluster_id_1 == cluster_id_2
