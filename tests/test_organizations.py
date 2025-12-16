"""Tests for the Organizations API wrapper."""

from deeporigin.platform.client import DeepOriginClient


def test_list_organizations_lv1():
    """Test listing organizations."""
    client = DeepOriginClient()
    orgs = client.organizations.list()

    assert isinstance(orgs, list), "Expected a list"
    assert len(orgs) > 0, "Expected at least one organization"
    org = orgs[0]
    for key in [
        "createdAt",
        "updatedAt",
        "orgKey",
        "name",
        "mfaEnabled",
        "threshold",
        "autoApproveMaxAmount",
        "status",
        "id",
        "invites",
        "roles",
    ]:
        assert key in org, f"Expected organization to have key {key}"


def test_list_organization_users_lv1():
    """Test listing organization users."""
    client = DeepOriginClient()
    users = client.organizations.users()

    assert isinstance(users, list), "Expected a list"
    assert len(users) > 0, "Expected at least one user"

    user = users[0]
    for key in [
        "id",
        "createdAt",
        "updatedAt",
        "firstName",
        "lastName",
        "email",
        "authId",
        "avatar",
        "title",
        "industries",
        "expertise",
        "company",
        "referralCode",
        "emailNotificationsDisabled",
        "notificationsDisabled",
        "appNotificationsDisabled",
    ]:
        assert key in user, f"Expected user to have key {key}"
