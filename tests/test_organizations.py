"""Tests for the Organizations API wrapper."""

from tests.utils import client  # noqa: F401


def test_list_organization_users(client):  # noqa: F811
    """Test listing organization users."""
    users = client.organizations.users()

    assert isinstance(users, list), "Expected a list"
    assert len(users) > 0, "Expected at least one user"
    assert "id" in users[0], "Expected user to have an id"
    assert "email" in users[0], "Expected user to have an email"
    assert "firstName" in users[0], "Expected user to have a firstName"
    assert "lastName" in users[0], "Expected user to have a lastName"
    assert "authId" in users[0], "Expected user to have an authId"
    assert "createdAt" in users[0], "Expected user to have a createdAt"


def test_list_organization_users_with_pagination(client):  # noqa: F811
    """Test listing organization users with pagination parameters."""
    users = client.organizations.users(page=0, page_size=10)

    assert isinstance(users, list), "Expected a list"
    assert len(users) > 0, "Expected at least one user"


def test_list_organization_users_with_filter(client):  # noqa: F811
    """Test listing organization users with filter parameter."""
    users = client.organizations.users(filter='{"email": "user1@example.com"}')

    assert isinstance(users, list), "Expected a list"
