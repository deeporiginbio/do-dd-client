"""Tests for the Billing API wrapper."""

from deeporigin.platform.client import DeepOriginClient


def test_get_usage_by_tag_lv1():
    """Test getting billing usage for a billing tag."""
    client = DeepOriginClient()
    response = client.billing.get_usage_by_tag(
        tag="foo14",
        start_date="2020-01-01",
        end_date="2030-01-01",
    )

    assert isinstance(response, dict), "Expected a dictionary"
    assert "status" in response, "Expected 'status' key"
    assert "org_id" in response, "Expected 'org_id' key"
    assert "items" in response, "Expected 'items' key"
    assert response["status"] == "OK", "Expected status to be 'OK'"
    assert isinstance(response["items"], list), "Expected 'items' to be a list"
    assert len(response["items"]) > 0, "Expected at least one item"

    # Check item structure
    item = response["items"][0]
    for key in [
        "entry_dt",
        "item_code",
        "description",
        "qty",
        "unit_cost",
        "total_cost",
        "notes",
        "billing_tag_transaction",
        "billing_tag",
    ]:
        assert key in item, f"Expected item to have key {key}"

    # Verify billing_tag matches
    assert item["billing_tag"] == "foo14", "Expected billing_tag to match input"


def test_get_usage_by_tag_with_defaults_lv1():
    """Test getting billing usage with default date values."""
    client = DeepOriginClient()
    response = client.billing.get_usage_by_tag(tag="foo14")

    assert isinstance(response, dict), "Expected a dictionary"
    assert "status" in response, "Expected 'status' key"
    assert "org_id" in response, "Expected 'org_id' key"
    assert "items" in response, "Expected 'items' key"
    assert response["status"] == "OK", "Expected status to be 'OK'"
