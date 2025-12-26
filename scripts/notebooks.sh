#!/usr/bin/env bash
set -euo pipefail

NOTEBOOKS_DIR="docs/notebooks"
DIRTY="${NOTEBOOKS_DIR}/dirty"
CLEAN="${NOTEBOOKS_DIR}/clean"

echo "Sanitizing notebooks..."

# Ensure dirs exist
mkdir -p "$CLEAN"

# Copy dirty -> clean (exit 0 if source doesn't exist)
cp -r "$DIRTY"/* "$CLEAN" 2>/dev/null || {
    echo "No dirty notebooks found, exiting."
    exit 0
}

# Clean all notebooks
uvx nb-clean clean "$CLEAN"

# Remove kernel metadata to avoid CI kernel issues
echo "Removing kernel metadata from notebooks..."
for notebook in "$CLEAN"/*.ipynb; do
    if [ -f "$notebook" ]; then
        uvx jupyter nbconvert \
            --clear-output \
            --ClearMetadataPreprocessor.enabled=True \
            --inplace "$notebook"
    fi
done

# Stage sanitized notebooks
git add "$CLEAN"/*.ipynb

exit 0