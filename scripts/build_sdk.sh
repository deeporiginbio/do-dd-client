#!/bin/bash

# script that builds the low level SDK for the Deep Origin Platform

# clean previously copied files to keep runs idempotent
rm -rf platform-sdk/src/platform platform-sdk/src/utils
rm -f platform-sdk/src/auth.py platform-sdk/src/config.py
mkdir -p platform-sdk/src/utils

# copy required files to the platform-sdk directory
cp -r src/platform platform-sdk/src/
cp -r src/utils/core.py platform-sdk/src/utils/core.py
cp -r src/utils/constants.py platform-sdk/src/utils/constants.py
cp -r src/utils/network.py platform-sdk/src/utils/network.py
cp -r src/auth.py platform-sdk/src/auth.py
cp -r src/config.py platform-sdk/src/config.py

# in every .py file, replace "from deeporigin" with "from do_sdk_platform"
python - <<'PY'
from pathlib import Path

for path in Path("platform-sdk/src").rglob("*.py"):
    text = path.read_text()
    path.write_text(text.replace("from deeporigin", "from deeporigin_sdk"))
PY

# run uv build in the platform-sdk directory
cd platform-sdk && uv build 