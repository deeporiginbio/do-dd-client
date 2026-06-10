"""Tests for the Organizations API wrapper."""

from deeporigin.platform.client import DeepOriginClient


def test_list_organizations_lv1(client: DeepOriginClient):
    """Test listing organizations."""
    orgs = client.organizations.list()

    assert isinstance(orgs, list), "Expected a list"
    assert len(orgs) > 0, "Expected at least one organization"
    org = orgs[0]
    for key in [
        "orgKey",
        "name",
        "mfaEnabled",
        "threshold",
        "autoApproveMaxAmount",
        "status",
        "id",
        "roles",
    ]:
        assert key in org, f"Expected organization to have key {key}"


def test_list_organization_users_lv1(client: DeepOriginClient):
    """Test listing organization users."""
    users = client.organizations.users()  # ty:ignore[unresolved-attribute]

    assert isinstance(users, list), "Expected a list"
    assert len(users) > 0, "Expected at least one user"
