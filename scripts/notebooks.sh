#!/usr/bin/env bash
set -euo pipefail

DIRTY="notebooks/dirty"
CLEAN="notebooks/clean"

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