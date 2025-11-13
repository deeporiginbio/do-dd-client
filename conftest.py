"""pytest configuration file

This governs the arguments we can pass pytest and sets up the local test server.

The test server runs locally and mimics the DeepOrigin Platform API endpoints.
All tests use this local server instead of making real API calls.
"""

import pytest

from tests.test_server import TestServer


@pytest.fixture(scope="session")
def test_server():
    """Start a local test server for the duration of the test session.

    Yields:
        TestServer instance that is running.
    """
    server = TestServer(port=0)
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def test_server_url(test_server):
    """Get the URL of the test server.

    Args:
        test_server: The test server fixture.

    Yields:
        Base URL of the test server (e.g., "http://127.0.0.1:12345").
    """
    host, port = test_server.server.server_address
    yield f"http://{host}:{port}"


def pytest_addoption(parser):
    parser.addoption(
        "--org_key",
        action="store",
        default="deeporigin",
        help="Organization key to use for the client",
    )


def pytest_generate_tests(metafunc):
    option_value = getattr(metafunc.config.option, "org_key", None)
    if "org_key" in metafunc.fixturenames and option_value is not None:
        metafunc.parametrize("org_key", [option_value])
