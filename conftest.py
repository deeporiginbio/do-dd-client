"""pytest configuration file

This governs the arguments we can pass pytest and sets up the local test server.

The test server runs locally and mimics the DeepOrigin Platform API endpoints.
All tests use this local server instead of making real API calls.
"""

import pytest

from tests.test_server import MockServer


@pytest.fixture(scope="session")
def test_server(pytestconfig):
    """Start a local test server for the duration of the test session.

    Only starts if --mock flag is passed. Otherwise yields None.

    Args:
        pytestconfig: Pytest configuration object.

    Yields:
        MockServer instance that is running, or None if --mock is not passed.
    """
    use_mock = pytestconfig.getoption("--mock", default=False)
    if not use_mock:
        yield None
        return

    server = MockServer(port=0)
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def test_server_url(test_server):
    """Get the URL of the test server.

    Args:
        test_server: The test server fixture.

    Yields:
        Base URL of the test server (e.g., "http://127.0.0.1:12345"), or None if --mock is not passed.
    """
    if test_server is None:
        yield None
        return

    host = test_server.host
    port = test_server.port
    yield f"http://{host}:{port}"


def pytest_addoption(parser):
    parser.addoption(
        "--org_key",
        action="store",
        default="deeporigin",
        help="Organization key to use for the client",
    )
    parser.addoption(
        "--mock",
        action="store_true",
        default=False,
        help="Use local mock server instead of real API",
    )


def pytest_generate_tests(metafunc):
    option_value = getattr(metafunc.config.option, "org_key", None)
    if "org_key" in metafunc.fixturenames and option_value is not None:
        metafunc.parametrize("org_key", [option_value])
