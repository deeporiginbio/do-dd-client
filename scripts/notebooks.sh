#!/usr/bin/env bash
set -euo pipefail

NOTEBOOKS_DIR="docs/notebooks"
DIRTY="${NOTEBOOKS_DIR}/dirty"
CLEAN="${NOTEBOOKS_DIR}/clean"

echo "Sanitizing notebooks..."

# Ensure dirs exist
mkdir -p "$CLEAN"

# Copy dirty -> clean
cp -r "$DIRTY"/* "$CLEAN"

# Clean all notebooks
uvx nb-clean clean "$CLEAN"

# Stage sanitized notebooks
git add "$CLEAN"/*.ipynb

exit 0