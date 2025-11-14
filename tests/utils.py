"""helper module to set up tests"""

import pytest

from deeporigin.platform.client import DeepOriginClient


@pytest.fixture(scope="session", autouse=True)
def client(pytestconfig, test_server_url):
    """Set up a client for testing.

    If --mock flag is passed, uses a local test server. Otherwise, uses
    default DeepOriginClient which reads credentials from config.

    Args:
        pytestconfig: Pytest configuration object.
        test_server_url: URL of the local test server (None if --mock not passed).

    Yields:
        DeepOriginClient instance configured for testing.
    """
    use_mock = pytestconfig.getoption("--mock", default=False)

    if use_mock:
        # Set up client pointing to local test server
        org_key = pytestconfig.getoption("org_key")
        # Use a dummy token for testing (the test server doesn't validate it)
        client_instance = DeepOriginClient(
            token="test-token",
            org_key=org_key,
            base_url=test_server_url,
            env="local",
        )
    else:
        # Use default client which reads from config/credentials
        # If org_key is explicitly provided (not default), use it; otherwise pass None to read from config
        org_key = pytestconfig.getoption("org_key")
        # If org_key is the default, pass None to let DeepOriginClient read from config
        org_key_arg = None if org_key == "deeporigin" else org_key
        client_instance = DeepOriginClient(org_key=org_key_arg)

    yield client_instance
