# script that builds the low level SDK for the Deep Origin Platform

# copy the src/platform directory to the platform-sdk directory
cp -r src/platform platform-sdk/src/

# copy the src/utils directory to the platform-sdk directory
cp -r src/utils platform-sdk/src/

# copy the src/auth directory to the platform-sdk directory
cp -r src/auth.py platform-sdk/src/auth.py

# copy the src/config directory to the platform-sdk directory
cp -r src/config.py platform-sdk/src/config.py


# in every .py file, replace "from deeporigin" with "from do_sdk_platform"
python - <<'PY'
from pathlib import Path

for path in Path("platform-sdk/src").rglob("*.py"):
    text = path.read_text()
    path.write_text(text.replace("from deeporigin", "from do_sdk_platform"))
PY

# run uv build in the platform-sdk directory
cd platform-sdk && uv build 