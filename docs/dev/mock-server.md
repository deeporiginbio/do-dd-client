# Mock Server for Local Development

The mock server is a local test server that mimics the DeepOrigin Platform API. It's useful for local development and testing without making real API calls to the platform.

## Overview

The mock server (`tests/mock_server/`) provides mock responses for all API endpoints used by the DeepOriginClient. It runs locally using FastAPI and uvicorn, and serves responses based on fixture data stored in `tests/fixtures/`.

### Architecture

The mock server is organized into routers, each handling a group of related endpoints:

| Router | File | Responsibilities |
|---|---|---|
| **data_platform** | `routers/data_platform.py` | Entity CRUD (proteins, ligands), result-explorer search |
| **tools** | `routers/tools.py` | Tool executions (list/get/cancel/confirm/run), clusters |
| **files** | `routers/files.py` | File upload/download |
| **entities** | `routers/entities.py` | Entity management |
| **billing** | `routers/billing.py` | Billing endpoints |

All routers share in-memory stores (dicts/lists) that are created in `MockServer.__init__` and passed into the router factory functions. This lets data flow between routers — for example, a tool execution in the tools router can inject records that are later visible via the data-platform router's result-explorer search.

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

## How Tool Executions Work

This is the most complex part of the mock server. When client code runs a tool (e.g., `protein.dock()`, `PocketFinder(protein).run()`, or `Molprops(...).run()`), the following happens end-to-end. All runnable work goes through `client.executions.create()` and the mock's `POST /tools/{org}/tools/{tool_key}/{tool_version}/executions` route (`run_tool` in `routers/tools.py`).

### 1. Building the execution DTO

`run_tool` inspects the request body and the URL's `tool_key` and produces a tool execution DTO with `executionId`, `status`, `userInputs`, `jobOutputs`, `quotationResult`, `tool: {key, version}`, and `type: "ToolExecution"`. Several tool keys are special-cased:

- `deeporigin.docking` (single ligand, `sync=True`), `deeporigin.pocket-finder`, `deeporigin.system-prep` complete in one POST via `_create_blocking_run_dto` and inject their fixture-backed `jobOutputs` into the result-explorer pool.
- `deeporigin.mol-props-protonation` returns deterministic `protonation_states` from the request inputs (`_build_protonation_execution`).
- `deeporigin.mol-props-*` (logd, logp, ames, …) hash the normalized request body and look up the recorded outputs at `tests/fixtures/tool-runs/{tool_key}/{body_hash}.json` (`_build_molprops_execution`). The fixture's per-ligand `jobOutputs` rows are re-keyed by the request's ligand IDs.
- `deeporigin.mol-props-combined` (`Molprops`) synthesizes per-ligand rows and a matching `quotationResult` (`_build_combined_molprops_execution`). When the request body includes `approveAmount: 0` (quote-only), the mock clears `jobOutputs` and sets `status` to `Quoted`.
- `deeporigin.bulk-docking` (`approveAmount=0`) loads `tests/fixtures/tool-runs/deeporigin.bulk-docking/quote.json` and scales the quotation by ligand count.
- All other tool keys fall back to a generic `Quoted` execution DTO via `_create_execution_dto`.

### 2. Request hashing for molprops fixtures

For `deeporigin.mol-props-*`, `_build_molprops_execution` normalizes the request body with `normalize_tool_execution_body` (strips IDs, `clusterId`, `tag`, `app`, `session`) and hashes it to find a fixture:

```
tests/fixtures/tool-runs/{tool_key}/{body_hash}.json
```

Because IDs are stripped before hashing, the same fixture handles different ligand IDs; the per-row `ligand_id` is patched in afterwards from the request's ligand inputs.

### 3. ID replacement in tool outputs

Some fixtures (docking, pocket-finder, system-prep) were recorded with whatever protein/ligand IDs existed at recording time, but in tests entities get fresh IDs every run. `_replace_ids_in_outputs` recursively walks the fixture's `jobOutputs` (or the legacy `functionOutputs` field on older fixtures) and rewrites any `protein_id` / `ligand_id` / `ligand1_id` value to match the IDs from the current request's `userInputs`.

### 4. Result-explorer injection

In production, when a tool execution completes, a message-queue flow writes structured outputs (pockets, poses, system, …) into a **result-explorer** table. Client code later queries this table to retrieve results — for example, `LigandSet.from_result(protein_id=...)` calls `client.results.get_poses(protein_id=...)`, which searches the result-explorer.

The mock server emulates this with `_inject_result_explorer_records_from_outputs`. After a tool execution returns, it checks the `output_key_map`:

```{.python notest}
output_key_map = {
    "deeporigin.pocketfinder": ("pockets", "pocket"),
    "deeporigin.pocket-finder": ("pockets", "pocket"),
    "deeporigin.docking": ("poses", "pose"),
    "deeporigin.system-prep": ("system", "preparedsystem"),
}
```

Each entry maps a tool manifest key to the `jobOutputs` field that should be mirrored into the shared result-explorer store and the `result_type` to tag those records with. Tool-specific helpers (`_inject_docking_tool_execution_results`, `_inject_pocketfinder_tool_execution_results`, `_inject_sysprep_tool_execution_results`) load the same fixture shapes and call this generic injector.

**When adding a new tool**, extend `output_key_map` and any tool-specific injectors in `routers/tools.py` so downstream queries (e.g., `Pocket.from_result`, `LigandSet.from_result`) can find the records.

### 5. Result-explorer queries

When client code queries results (e.g., `client.results.get_poses(protein_id=...)`), it hits the data-platform router's `result-explorer/search` endpoint. This applies `_apply_eq_filters`, which checks filter values against both top-level record fields **and** nested `data` fields. Since the injected records store tool outputs under `data`, a filter like `protein_id: {eq: "abc123"}` matches `record["data"]["protein_id"]`.

### End-to-end example: docking

Here's the full flow for `test_docking_with_data_platform_lv2`:

```
1. registered_protein fixture
   → POST /data-platform/{org}/proteins  (creates protein, gets fresh ID)

2. registered_ligand fixture
   → POST /data-platform/{org}/ligands   (creates or syncs ligand)

3. protein.dock(ligand=..., pocket=...)
   → POST /tools/{org}/tools/deeporigin.docking/{version}/executions
   → run_tool:
       a. build a Completed execution DTO via _create_blocking_run_dto
       b. _inject_docking_tool_execution_results loads the docking fixture,
          replaces protein_id/ligand_id, and pushes the "poses" rows into
          the result-explorer store

4. LigandSet.from_result(protein_id=...)
   → POST /data-platform/{org}/result-explorer/search
       filter: {protein_id: {eq: "<fresh ID>"}, tool_id: {in: [...]}}
   → _apply_eq_filters matches record["data"]["protein_id"]
   → returns the poses injected in step 3b
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

`_load_result_explorer_fixtures` loads any `tests/fixtures/result-explorer-*.json` files into the shared results store at startup. Tool executions then append to this same store at runtime.

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
- **Executions API**: List, get, cancel, confirm, and create tool executions
- **Clusters API**: List available clusters
- **Entities API**: Entity management (delete)
- **Data Platform API**: Entity CRUD (proteins, ligands), result-explorer search
- **Billing API**: Billing endpoints
- **Health Check**: `/health` endpoint

## Extending the Mock Server

### Adding a new tool

1. Record a fixture by running the tool against `--env dev` and saving the response as `tests/fixtures/tool-runs/{tool_key}/{body_hash}.json` (or `run.json` / `quote.json` for tools that don't hash by request body).
2. If the tool produces structured outputs that need to be queryable via result-explorer, add an entry to `output_key_map` in `_inject_result_explorer_records_from_outputs` (`tests/mock_server/routers/tools.py`) and a small injector helper for that tool.
3. Run the test with `--env local` to verify.

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
- Tool executions return pre-recorded fixtures, not computed results
- Rate limiting and other production features are not implemented

For production use, always use the real DeepOrigin Platform API.
