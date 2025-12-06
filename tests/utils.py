"""helper module to set up tests"""

import pytest

from deeporigin.platform.client import DeepOriginClient


@pytest.fixture(scope="session", autouse=True)
def client(pytestconfig, test_server_url):
    """Set up a client for testing.

    Uses DeepOriginClient.from_env() with the environment specified by --env.
    If --env local is passed, uses the default local base URL (http://127.0.0.1:4931).

    Args:
        pytestconfig: Pytest configuration object.
        test_server_url: URL of the local test server (None if --env local not passed).

    Yields:
        DeepOriginClient instance configured for testing.
    """
    env = pytestconfig.getoption("--env", default=None)

    if env is None:
        # No env specified, use from_env() which reads from DEEPORIGIN_ENV or config
        client_instance = DeepOriginClient.from_env()
        yield client_instance
        return

    # Use the specified environment
    client_instance = DeepOriginClient.from_env(env=env)

    yield client_instance
