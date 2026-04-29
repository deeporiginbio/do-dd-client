# Mock Server for Local Development

The mock server is a local test server that mimics the DeepOrigin Platform API. It's useful for local development and testing without making real API calls to the platform.

## Overview

The mock server (`tests/mock_server/`) provides mock responses for all API endpoints used by the DeepOriginClient. It runs locally using FastAPI and uvicorn, and serves responses based on fixture data stored in `tests/fixtures/`.

### Architecture

The mock server is organized into routers, each handling a group of related endpoints:

| Router | File | Responsibilities |
|---|---|---|
| **data_platform** | `routers/data_platform.py` | Entity CRUD (proteins, ligands), result-explorer search |
| **tools** | `routers/tools.py` | Function runs, executions, clusters |
| **files** | `routers/files.py` | File upload/download |
| **entities** | `routers/entities.py` | Entity management |
| **billing** | `routers/billing.py` | Billing endpoints |

All routers share in-memory stores (dicts/lists) that are created in `MockServer.__init__` and passed into the router factory functions. This lets data flow between routers — for example, a function run in the tools router can inject records that are later visible via the data-platform router's result-explorer search.

**Proteins (local only):** `Protein.sync()` / `Protein.register()` are wired to a single canonical row (`MOCK_CANONICAL_PROTEIN_ID`, `tests/brd.pdb` fixture) so IDs stay stable under `--env local`. There is no separate test module for the mock server; that behavior is exercised indirectly by any local test that syncs a protein (e.g. the `registered_protein` fixture).

## Running the Mock Server

### Using in Tests

Pass `--env local` to pytest:

```bash
uv run pytest --env local
```

This starts a `MockServer` on port 4931 for the duration of the test session (see `conftest.py`). With `DO_ENV=local`, `DeepOriginClient` defaults to `http://127.0.0.1:4931` (same as the mock).

**Full platform locally (gateway on 6010):** set `DO_BASE_URL=http://127.0.0.1:6010` (and keep or set `DO_ENV=local` if inferred from URL). See `LOCAL_ENDPOINT_GATEWAY` in `src/utils/constants.py`.

The same tests can also run against a real environment:

```bash
uv run pytest --env dev
```

When `--env dev` is used, the mock server is **not** started and all requests go to the real platform API. This dual-mode design means the mock server must produce responses that are structurally identical to the real API — it is not a shortcut that skips validation.

### Standalone Script

To run the mock server standalone for local development:

```bash
python tests/run_mock_server.py [PORT]
```

Where `PORT` is the port number to run the server on (default: 8000).

## How Function Runs Work

This is the most complex part of the mock server. When client code calls a function (e.g., `protein.dock()` or `PocketFinder(protein).run()`), the following happens end-to-end:

### 1. Request hashing and fixture lookup

The tools router's `_handle_function_run` handler receives the request body, normalizes it (stripping volatile fields like IDs), and hashes it. The hash is used to look up a pre-recorded fixture file:

```
tests/fixtures/function-runs/{function_key}/{body_hash}.json
```

This means the mock server returns realistic, pre-recorded responses without needing to actually run the function.

### 2. ID replacement in function outputs

The fixture was recorded with whatever protein/ligand IDs existed at recording time. But in tests, entities are freshly registered and get new IDs on every run. To handle this, `_replace_ids_in_function_outputs` recursively walks the fixture's `functionOutputs` and replaces any `protein_id` / `ligand_id` values with the IDs from the current request's `userInputs`.

This is why fixture lookup uses a *normalized* hash (IDs stripped) — different IDs hash to the same fixture, and the IDs are patched in afterward.

### 3. Result-explorer injection

In production, when a function completes, a message-queue flow writes structured outputs (pockets, poses, etc.) into a **result-explorer** table. Client code later queries this table to retrieve results — for example, `LigandSet.from_docking_result(protein_id=...)` calls `client.results.get_poses(protein_id=...)`, which searches the result-explorer.

The mock server emulates this with `_inject_result_explorer_records`. After a function run returns, it checks the `output_key_map`:

```{.python notest}
output_key_map = {
    "deeporigin.pocketfinder": "pockets",
    "deeporigin.pocket-finder": "pockets",
    "deeporigin.docking": "poses",
    "deeporigin.system-prep": "system",
}
```

Each entry maps a function or **tool** manifest key to the field in `functionOutputs` that should be mirrored into the shared result-explorer store. Tool executions (`POST .../tools/{tool_key}/.../executions`) use helpers such as `_inject_pocketfinder_tool_execution_results` to load the same fixture shapes and call `_inject_result_explorer_records` with the tool key.

**When adding a new function or tool**, extend `output_key_map` (and any tool-specific injectors in `tools.py`) so downstream queries (e.g., `Pocket.from_result`, `LigandSet.from_docking_result`) can find the records.

### 4. Result-explorer queries

When client code queries results (e.g., `client.results.get_poses(protein_id=...)`), it hits the data-platform router's `result-explorer/search` endpoint. This applies `_apply_eq_filters`, which checks filter values against both top-level record fields **and** nested `data` fields. Since the injected records store function outputs under `data`, a filter like `protein_id: {eq: "abc123"}` matches `record["data"]["protein_id"]`.

### End-to-end example: docking

Here's the full flow for `test_docking_with_data_platform_lv2`:

```
1. registered_protein fixture
   → POST /data-platform/{org}/proteins  (creates protein, gets fresh ID)

2. registered_ligand fixture
   → POST /data-platform/{org}/ligands   (creates or syncs ligand)

3. protein.dock(ligand=..., pocket=...)
   → POST /tools/{org}/functions/deeporigin.docking
   → _handle_function_run:
       a. normalize body, hash → load fixture
       b. replace protein_id/ligand_id in functionOutputs
       c. _inject_result_explorer_records → "poses" array → result-explorer store

4. LigandSet.from_docking_result(protein_id=...)
   → POST /data-platform/{org}/result-explorer/search
       filter: {protein_id: {eq: "<fresh ID>"}, tool_id: {in: [...]}}
   → _apply_eq_filters matches record["data"]["protein_id"]
   → returns the poses injected in step 3c
```

## Entity Stores and Fixtures

### In-memory stores

The mock server maintains in-memory dicts for proteins and ligands. These start empty for proteins (fresh registration every test run) and pre-populated for ligands (from SDF files and JSON fixtures).

### Ligand pre-population

`_load_ligand_fixtures` scans multiple sources on startup:

1. `src/data/brd/*.sdf` — package-data ligands
2. `tests/fixtures/ligands-brd-all.sdf`, `42-ligands.sdf`, `brd-7.sdf`
3. `tests/fixtures/ligand_*.json`

Ligand IDs are **deterministic** — derived from a SHA-256 hash of the canonical SMILES. This means the same ligand always gets the same ID across test runs, which is important for fixture matching.

### Result-explorer pre-population

`_load_result_explorer_fixtures` loads any `tests/fixtures/result-explorer-*.json` files into the shared results store at startup. Function runs then append to this same store at runtime.

## Configuring Your Client

To use the mock server with your code, configure the `DeepOriginClient` to point to the mock server URL:

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient(
    token="test-token",  # Any token works with the mock server
    org_key="deeporigin",  # Use any org_key
    base_url="http://127.0.0.1:4931",  # Mock server URL (port 4931 for tests)
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
- **Entities API**: Entity management (delete)
- **Data Platform API**: Entity CRUD (proteins, ligands), result-explorer search
- **Billing API**: Billing endpoints
- **Health Check**: `/health` endpoint

## Extending the Mock Server

### Adding a new function type

1. Record a fixture by running the function against `--env dev` and saving the response as `tests/fixtures/function-runs/{function_key}/{body_hash}.json`
2. If the function produces structured outputs that need to be queryable via result-explorer, add an entry to `output_key_map` in `_inject_result_explorer_records` (`tests/mock_server/routers/tools.py`)
3. Run the test with `--env local` to verify

### Adding a new entity endpoint

1. Add a route handler to the appropriate router in `tests/mock_server/routers/`
2. Optionally add fixture files in `tests/fixtures/` if you need realistic data
3. Use `load_fixture()` to load JSON fixtures

### Adding a new router

1. Create a new file in `tests/mock_server/routers/`
2. Define a `create_*_router()` factory function that accepts shared state
3. Include the router in `MockServer._setup_routes()` in `server.py`

## Limitations

- Authentication is not validated (any token works)
- File storage is in-memory and lost when the server stops
- Function runs return pre-recorded fixtures, not computed results
- Rate limiting and other production features are not implemented

For production use, always use the real DeepOrigin Platform API.
