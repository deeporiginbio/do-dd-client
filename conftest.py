"""pytest configuration file

This governs the arguments we can pass pytest and sets up the local test server.

The test server runs locally and mimics the DeepOrigin Platform API endpoints.
All tests use this local server instead of making real API calls.
"""

import os

import pytest

from deeporigin.auth import get_token
from deeporigin.config import get_value
from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.constants import ENV_VARIABLES
from tests.mock_server import MockServer


@pytest.fixture(scope="session", autouse=True)
def set_test_env_vars(pytestconfig):
    """Set up environment variables for testing.

    Sets DEEPORIGIN_ENV based on the --env flag. For local environment, the client
    automatically generates a token and sets org_key. For other environments, sets
    DEEPORIGIN_TOKEN and DEEPORIGIN_ORG_KEY if not already set.

    This ensures code that creates clients implicitly (e.g., Complex.from_dir()) will
    automatically use the test configuration.

    The --env option must be explicitly provided (e.g., --env local).
    When --env local is passed, the test_server fixture (autouse) ensures the mock server is running.

    Args:
        pytestconfig: Pytest configuration object.

    Yields:
        None

    Raises:
        ValueError: If --env option is not provided.
    """
    env = pytestconfig.getoption("--env")

    if env is None:
        raise ValueError(
            "The --env option must be explicitly provided. Example: pytest --env local"
        )

    # Save original env vars to restore later
    original_env_vars = {key: os.environ.get(key) for key in ENV_VARIABLES.values()}

    try:
        # Set environment variables based on the specified environment
        if env == "local":
            # Client automatically handles local environment (generates token, sets org_key)
            # We only need to set DEEPORIGIN_ENV=local
            os.environ[ENV_VARIABLES["env"]] = "local"

            # Clear any cached clients so they use the new env vars
            DeepOriginClient.close_all()
        else:
            # For non-local environments, only set env vars if they're not already set
            # If not set, get_token and get_value will read from disk
            if ENV_VARIABLES["access_token"] not in os.environ:
                os.environ[ENV_VARIABLES["access_token"]] = get_token(env=env)
            if ENV_VARIABLES["org_key"] not in os.environ:
                os.environ[ENV_VARIABLES["org_key"]] = get_value()["org_key"]
            os.environ[ENV_VARIABLES["env"]] = env

            # Clear any cached clients so they use the new env vars
            DeepOriginClient.close_all()

        yield
    finally:
        # Restore original env vars
        for key, value in original_env_vars.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture(scope="session", autouse=True)
def test_server(pytestconfig):
    """Start a local test server for the duration of the test session.

    Only starts if --env local is passed. Otherwise yields None.
    This fixture is autouse so it always runs, but only starts the server when needed.

    Args:
        pytestconfig: Pytest configuration object.

    Yields:
        MockServer instance that is running, or None if --env local is not passed.
    """
    env = pytestconfig.getoption("--env", default=None)

    if env != "local":
        yield None
        return

    server = MockServer(port=4931)  # Fixed port for test server
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def test_server_url(test_server):
    """Get the URL of the test server.

    Args:
        test_server: The test server fixture.

    Yields:
        Base URL of the test server (e.g., "http://127.0.0.1:4931"), or None if --env local is not passed.
    """
    if test_server is None:
        yield None
        return

    host = test_server.host
    port = test_server.port
    yield f"http://{host}:{port}"


def pytest_addoption(parser):
    parser.addoption(
        "--runslow", action="store_true", default=False, help="run slow tests"
    )
    parser.addoption(
        "--org_key",
        action="store",
        default="deeporigin",
        help="Organization key to use for the client",
    )
    parser.addoption(
        "--env",
        action="store",
        default=None,
        choices=["local", "dev", "staging", "prod"],
        help="Environment to use for the client (local, dev, staging, prod)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        # --runslow given in cli: do not skip slow tests
        return
    skip_slow = pytest.mark.skip(reason="need --runslow option to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


def pytest_generate_tests(metafunc):
    option_value = getattr(metafunc.config.option, "org_key", None)
    if "org_key" in metafunc.fixturenames and option_value is not None:
        metafunc.parametrize("org_key", [option_value])
