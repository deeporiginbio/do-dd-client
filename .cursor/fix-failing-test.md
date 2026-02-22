
---
name: fix failing tests
description: Fix tests that fail on --env local due to missing/incorrect fixtures
---

# Fix Failing tests on --env local

## When to use

If you find a test is failing on `--env local`, but passes on `--env dev`, use this skill. 

## What's happening

Tests on `--env local` work by running a mock server (at `tests/mock_server/`) that responds to API requests identically to how the real server does (without doing any computation). 

For **function runs** (pocket finder, docking, sysprep, molprops, etc.), the mock server looks up pre-recorded responses from JSON fixture files stored under `tests/fixtures/function-runs/{function_key}/{hash}.json`. The hash is computed from the normalized request body using `normalize_function_body()` in `src/utils/core.py`.

For **file downloads**, the mock server serves files from `tests/fixtures/files/`. Function responses reference remote file paths (e.g. `tool-runs/{execution_id}/pocket_1.pdb`), and those files must exist at `tests/fixtures/files/{remote_path}`.

## Why it breaks

1. **Missing fixture JSON**: A function's inputs changed (new params, different version), so the hash no longer matches any existing fixture file.
2. **Missing fixture files**: The fixture JSON references remote file paths (PDBs, SDFs, XMLs) that don't exist in `tests/fixtures/files/`.
3. **Stale fixture content**: The response format changed on the server side, making the old fixture invalid.

## How to fix

### Step 1: Verify tests pass on dev

```bash
uv run ruff format . && uv run ruff check --select I . --fix
uv run pytest tests/test_functions.py -x --env dev -v
```

### Step 2: Capture fixtures using `record=True`

Write a throwaway script that runs the failing test operations against dev with `record=True` on the client. This automatically saves responses as fixture files with the correct hash.

```python
"""Throwaway script to capture fixtures from dev."""
import os
os.environ["DEEPORIGIN_ENV"] = "dev"

from deeporigin.drug_discovery import BRD_DATA_DIR, Protein
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient.get(record=True, replace=True)

# Run the same operations as the failing test
protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
protein.remove_water()
pockets = protein.find_pockets(pocket_count=1, use_cache=False, client=client)
```

Key points:

- Pass `record=True, replace=True` to `DeepOriginClient.get()` so the singleton client records responses.
- Use `use_cache=False` to force fresh API calls.
- Pass `client=client` explicitly to ensure the recording client is used.
- If tests depend on each other (e.g. docking uses pockets from pocket finder), **capture everything in one script run** so file paths and pocket centers are consistent.

### Step 3: Save referenced files to `tests/fixtures/files/`

Function responses contain remote file paths. These files must also be saved so the mock server can serve them during local tests.

```python
import json
from pathlib import Path

# Read the fixture to find referenced file paths
fixture_dir = Path("tests/fixtures/function-runs/deeporigin.pocketfinder")
latest = max(fixture_dir.glob("*.json"), key=lambda f: f.stat().st_mtime)
with open(latest) as f:
    response = json.load(f)

# Download each referenced file
for pocket_data in response["functionOutputs"]["pockets"]:
    remote_path = pocket_data["file_path"]
    local_path = Path("tests/fixtures/files") / remote_path
    local_path.parent.mkdir(parents=True, exist_ok=True)
    client.files.download_file(remote_path=remote_path, local_path=str(local_path))
```

### Step 4: Verify locally

```bash
uv run pytest tests/test_functions.py -x --env local -v
```

### Step 5: Clean up

- Delete the throwaway capture script.
- Remove stale fixture files and directories from `tests/fixtures/` that are no longer referenced (use `git status` to identify new files).
- Run the full test suite to check for regressions: `uv run pytest --env local -x`

## How fixture hashing works

The hash is computed by `normalize_function_body()` in `src/utils/core.py`. This function:

1. Extracts `inputs` (or `params`) from the request body.
2. **Recursively strips all `id` keys** from nested dicts (via `_strip_ids()`), since IDs are environment-specific (protein IDs, ligand IDs differ between dev/local).
3. Preserves `approveAmount` if present (affects quote vs run behavior).
4. Excludes `clusterId` and `tag` (environment-specific).

The same normalization is used in both:
- `src/platform/functions.py` — when `record=True`, to name the fixture file
- `tests/mock_server/server.py` — to look up the fixture file for a request

This means the fixture hash depends only on **content-deterministic fields** like `file_path` (content hash), `smiles`, `pocket_count`, `box_size`, etc. — not on randomly-generated IDs.

## Common pitfalls

- **Running the capture multiple times overwrites fixtures.** If you capture pocket finder, then capture docking (which also calls pocket finder internally), the pocket finder fixture gets overwritten with a new execution ID. The old pocket PDB files won't match. Always capture in **one consistent run**.
- **The `file_path` field in responses is execution-specific** (contains a UUID like `tool-runs/{uuid}/pocket_1.pdb`). Every capture produces different UUIDs, so you must save both the fixture JSON and its referenced files together.
- **Pocket finder is non-deterministic.** Different runs may produce slightly different pocket centers. Since docking payloads include `pocket_center`, a docking fixture captured in a separate run from pocket finder may have a different hash. Capture them together.
