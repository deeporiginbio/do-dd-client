#!/usr/bin/env bash
set -euo pipefail

DIRTY="notebooks/dirty"

echo "Sanitizing notebooks..."

# Ensure dirs exist
mkdir -p notebooks/clean

# Copy dirty -> clean
cp -r "$DIRTY"/* notebooks/clean

# Clean all notebooks
uvx nb-clean clean notebooks/clean

# Stage sanitized notebooks
git add notebooks/clean/*.ipynb

exit 0