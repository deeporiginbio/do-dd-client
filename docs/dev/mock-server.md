# Mock Server for Local Development

The mock server is a local test server that mimics the DeepOrigin Platform API. It's useful for local development and testing without making real API calls to the platform.

## Overview

The mock server (`tests/mock_server.py`) provides mock responses for all API endpoints used by the DeepOriginClient. It runs locally using FastAPI and uvicorn, and serves responses based on fixture data stored in `tests/fixtures/`.

## Running the Mock Server

### Standalone Script

To run the mock server standalone for local development:

```bash
python scripts/run_mock_server.py [PORT]
```

Where `PORT` is the port number to run the server on (default: 8000).

Example:

```bash
python scripts/run_mock_server.py 8000
```

The server will start and display:

```bash
Mock server running at http://127.0.0.1:8000
Press Ctrl+C to stop...
```

Press `Ctrl+C` to stop the server.

### Using in Tests

The mock server is automatically started when running tests with the `--mock` flag:

```bash
pytest --mock
```

This starts the server for the duration of the test session and automatically stops it when tests complete.

## Configuring Your Client

To use the mock server with your code, configure the `DeepOriginClient` to point to the mock server URL:

```python
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient(
    token="test-token",  # Any token works with the mock server
    org_key="deeporigin",  # Use any org_key
    base_url="http://127.0.0.1:8000",  # Mock server URL
    env="local",
)
```

## Available Endpoints

The mock server implements the following endpoints:

- **Files API**: List, upload, download, and delete files
- **Tools API**: List tools and tool definitions
- **Functions API**: List functions and run function executions
- **Executions API**: List executions, get execution details, cancel/confirm executions
- **Clusters API**: List available clusters
- **Organizations API**: List organization users
- **Health Check**: `/health` endpoint

## Fixtures

The mock server uses fixture files from `tests/fixtures/` to provide realistic responses. Key fixtures include:

- `execution_example.json`: Template for execution responses
- `molprops_serotonin.json`: Molecular properties data for testing
- `abfe/progress-reports.json`: ABFE progress report data

## Extending the Mock Server

To add new endpoints or modify existing ones, edit `tests/mock_server.py`:

1. Add a new route handler in the `_setup_routes()` method
2. Optionally add fixture files in `tests/fixtures/` if you need realistic data
3. Use `_load_fixture()` to load JSON fixtures

Example:

```{.python notest}
@self.app.get("/tools/{org_key}/custom-endpoint")
def custom_endpoint(org_key: str) -> dict[str, Any]:
    """Custom endpoint handler."""
    fixture_data = self._load_fixture("custom_fixture")
    return fixture_data
```

## Limitations

The mock server is designed for testing and development purposes. It has some limitations:

- Authentication is not validated (any token works)
- File storage is in-memory and lost when the server stops
- Some complex API behaviors may not be fully replicated
- Rate limiting and other production features are not implemented

For production use, always use the real DeepOrigin Platform API.

