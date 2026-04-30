
---
name: fix failing tests
description: Fix tests that fail on --env local due to missing/incorrect fixtures
---

# Fix Failing tests on --env local

## When to use

If you find a test is failing on `--env local`, but passes on `--env dev`, use this skill.

## What's happening

Tests on `--env local` work by running a mock server (at `tests/mock_server/`) that responds to API requests identically to how the real server does (without doing any computation).

For **tool executions** (pocket finder, docking, sysprep, molprops, protonation, etc.), the mock server handles `POST /tools/{org}/tools/{tool_key}/{tool_version}/executions` in `tests/mock_server/routers/tools.py`. Molprops fixtures are looked up under `tests/fixtures/tool-runs/{tool_key}/{hash}.json`. The hash is computed from the normalized request body using `normalize_tool_execution_body()` in `src/utils/hashing.py`.

For **file downloads**, the mock server serves files from `tests/fixtures/files/`. Execution responses reference remote file paths (e.g. `tool-runs/{execution_id}/pocket_1.pdb`), and those files must exist at `tests/fixtures/files/{remote_path}`.

## Why it breaks

1. **Missing fixture JSON**: Tool inputs changed (new params, different version), so the hash no longer matches any existing fixture file.
2. **Missing fixture files**: The fixture JSON references remote file paths (PDBs, SDFs, XMLs) that don't exist in `tests/fixtures/files/`.
3. **Stale fixture content**: The response format changed on the server side, making the old fixture invalid.

## How to fix

### Step 1: Verify tests pass on dev

```bash
uv run ruff format . && uv run ruff check --select I . --fix
uv run pytest tests/test_drug_discovery_tools.py -x --env dev -v
```

### Step 2: Capture fixtures using `record=True`

Write a throwaway script that runs the failing test operations against dev with `record=True` on the client. This automatically saves responses as fixture files with the correct hash.

```python
"""Throwaway script to capture fixtures from dev."""
import os
os.environ["DO_ENV"] = "dev"

from deeporigin.drug_discovery import BRD_DATA_DIR, PocketFinder, Protein
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient.get(record=True, replace=True)

# Run the same operations as the failing test
protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
protein.remove_water()
pf = PocketFinder(protein, pocket_count=1, client=client)
pockets = pf.run()
```

Key points:

- Pass `record=True, replace=True` to `DeepOriginClient.get()` so the singleton client records responses.
- Use `use_cache=False` to force fresh API calls.
- Pass `client=client` explicitly to ensure the recording client is used.
- **Each test must be independent.** If a test needs output from another tool (e.g. docking needs a pocket), load it from a fixture file rather than calling the upstream tool. For example, load a pocket PDB from `tests/fixtures/files/` using `Pocket.from_pdb_file()` instead of running `PocketFinder` or other remote calls just to obtain a pocket.

### Step 3: Save referenced files to `tests/fixtures/files/`

Tool execution responses contain remote file paths. These files must also be saved so the mock server can serve them during local tests.

```python
import json
from pathlib import Path

# Read the fixture to find referenced file paths
fixture_dir = Path("tests/fixtures/tool-runs/deeporigin.pocketfinder")
latest = max(fixture_dir.glob("*.json"), key=lambda f: f.stat().st_mtime)
with open(latest) as f:
    response = json.load(f)

outputs = response.get("jobOutputs") or response.get("functionOutputs") or {}
# Download each referenced file
for pocket_data in outputs.get("pockets", []):
    remote_path = pocket_data["file_path"]
    local_path = Path("tests/fixtures/files") / remote_path
    local_path.parent.mkdir(parents=True, exist_ok=True)
    client.files.download(remote_path=remote_path, local_path=str(local_path))
```

### Step 4: Verify locally

```bash
uv run pytest tests/test_drug_discovery_tools.py -x --env local -v
```

### Step 5: Clean up

- Delete the throwaway capture script.
- Remove stale fixture files and directories from `tests/fixtures/` that are no longer referenced (use `git status` to identify new files).
- Run the full test suite to check for regressions: `uv run pytest --env local -x`

## How fixture hashing works

The hash is computed by `normalize_tool_execution_body()` in `src/utils/hashing.py`. This function:

1. Extracts `inputs` (or `params`) from the request body.
2. **Recursively strips all `id` keys** from nested dicts (via `_strip_ids()`), since IDs are environment-specific (protein IDs, ligand IDs differ between dev/local).
3. Preserves `approveAmount` if present (affects quote vs run behavior).
4. Excludes `clusterId`, `tag`, `app`, and `session` (environment-specific).

The same normalization is used when `record=True` on the client names the fixture file and when the mock server looks up molprops fixtures.

This means the fixture hash depends only on **content-deterministic fields** like `file_path` (content hash), `smiles`, `pocket_count`, `box_size`, etc. — not on randomly-generated IDs.

## Common pitfalls

- **The `file_path` field in responses is execution-specific** (contains a UUID like `tool-runs/{uuid}/pocket_1.pdb`). Every capture produces different UUIDs, so you must save both the fixture JSON and its referenced files together.
- **Tests must not depend on each other.** If a test needs a pocket (or other upstream output), load it from a fixture file (e.g. `Pocket.from_pdb_file("tests/fixtures/files/tool-runs/{uuid}/pocket_1.pdb")`), not by calling the upstream tool. This avoids coupling tests and eliminates issues with non-deterministic upstream outputs.
- **Capture each tool independently.** Since tests are independent, you can capture fixtures for each tool in separate script runs. Just make sure the fixture files referenced in responses are also saved.
