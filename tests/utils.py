"""helper module to set up tests"""

import pytest

from deeporigin.platform.client import DeepOriginClient


@pytest.fixture(scope="session", autouse=True)
def client(pytestconfig, test_server_url):
    """Set up a client pointing to the local test server.

    Args:
        pytestconfig: Pytest configuration object.
        test_server_url: URL of the local test server.

    Yields:
        DeepOriginClient instance configured to use the test server.
    """
    # Set up client pointing to local test server
    org_key = pytestconfig.getoption("org_key")
    # Use a dummy token for testing (the test server doesn't validate it)
    client_instance = DeepOriginClient(
        token="test-token",
        org_key=org_key,
        base_url=test_server_url,
    )

    yield client_instance
