"""helper module to set up tests"""

import pytest

from deeporigin.platform.client import DeepOriginClient


@pytest.fixture(scope="session", autouse=True)
def client(pytestconfig):
    """Set up a client for testing.

    Uses DeepOriginClient.from_env() with the environment specified by --env.
    The --env option must be explicitly provided (e.g., --env local).
    When --env local is passed, the test_server fixture (autouse) ensures the mock server is running.

    Args:
        pytestconfig: Pytest configuration object.

    Yields:
        DeepOriginClient instance configured for testing.

    Raises:
        ValueError: If --env option is not provided.
    """
    env = pytestconfig.getoption("--env")

    if env is None:
        raise ValueError(
            "The --env option must be explicitly provided. Example: pytest --env local"
        )

    # Use the specified environment
    client_instance = DeepOriginClient.from_env(env=env)

    yield client_instance
