#!/bin/bash
set -euo pipefail

# script that builds the low level SDK for the Deep Origin Platform

# clean previously copied files to keep runs idempotent
rm -rf platform-sdk/src/platform platform-sdk/src/utils
rm -f platform-sdk/src/auth.py platform-sdk/src/config.py platform-sdk/src/exceptions.py
rm -f platform-sdk/src/__init__.py
mkdir -p platform-sdk/src platform-sdk/src/utils

# copy required files to the platform-sdk directory (subset of platform package).
# All platform modules needed by client.py, except job.py / job_viz_functions.py (heavy job UI stack).
mkdir -p platform-sdk/src/platform
cp src/platform/__init__.py platform-sdk/src/platform/
cp src/platform/billing.py platform-sdk/src/platform/
cp src/platform/client.py platform-sdk/src/platform/
cp src/platform/clusters.py platform-sdk/src/platform/
cp src/platform/constants.py platform-sdk/src/platform/
cp src/platform/entities.py platform-sdk/src/platform/
cp src/platform/executions.py platform-sdk/src/platform/
cp src/platform/files.py platform-sdk/src/platform/
cp src/platform/functions.py platform-sdk/src/platform/
cp src/platform/organizations.py platform-sdk/src/platform/
cp src/platform/progress_reports.py platform-sdk/src/platform/
cp src/platform/projects.py platform-sdk/src/platform/
cp src/platform/results.py platform-sdk/src/platform/
cp src/platform/tools.py platform-sdk/src/platform/
cp src/__init__.py platform-sdk/src/__init__.py
cp src/utils/constants.py platform-sdk/src/utils/constants.py
cp src/utils/network.py platform-sdk/src/utils/network.py
cp src/utils/env.py platform-sdk/src/utils/env.py
cp src/utils/display.py platform-sdk/src/utils/display.py
cp src/utils/hashing.py platform-sdk/src/utils/hashing.py
cp src/utils/__init__.py platform-sdk/src/utils/__init__.py
cp src/auth.py platform-sdk/src/auth.py
cp src/exceptions.py platform-sdk/src/exceptions.py
cp src/config.py platform-sdk/src/config.py

# in every .py file, replace "from deeporigin" with "from do_sdk_platform"
python3 - <<'PY'
from pathlib import Path

for path in Path("platform-sdk/src").rglob("*.py"):
    text = path.read_text()
    path.write_text(text.replace("from deeporigin", "from deeporigin_sdk"))
PY

# run uv build in the platform-sdk directory
cd platform-sdk && uv build 