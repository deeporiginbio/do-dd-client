#!/usr/bin/env bash
set -euo pipefail

NOTEBOOKS_DIR="docs/notebooks"
DIRTY="${NOTEBOOKS_DIR}/dirty"
CLEAN="${NOTEBOOKS_DIR}/clean"

echo "Sanitizing notebooks..."

# Ensure dirs exist
mkdir -p "$CLEAN"

# Copy dirty -> clean (exit 0 if source doesn't exist)
if [ ! -d "$DIRTY" ] || [ -z "$(ls -A "$DIRTY" 2>/dev/null)" ]; then
    echo "No dirty notebooks found, exiting."
    exit 0
fi
# Use nullglob to handle case where glob doesn't match
shopt -s nullglob
cp -r "$DIRTY"/* "$CLEAN" || {
    echo "No dirty notebooks found, exiting."
    exit 0
}
shopt -u nullglob

# Clean all notebooks
uvx nb-clean clean "$CLEAN"

# Stage sanitized notebooks
git add "$CLEAN"/*.ipynb

exit 0