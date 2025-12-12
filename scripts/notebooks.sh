#!/usr/bin/env bash
set -euo pipefail

DIRTY="notebooks/dirty"
CLEAN="notebooks/clean"

# Ensure dirs exist
mkdir -p "$CLEAN"

# Find dirty notebooks that have changed in the working tree
mapfile -t CHANGED_DIRTY_NBS < <(
  git status --porcelain "$DIRTY" \
    | awk '{print $2}' \
    | grep -E '\.ipynb$' || true
)

# Nothing to do
if [ ${#CHANGED_DIRTY_NBS[@]} -eq 0 ]; then
  exit 0
fi

echo "Sanitizing changed notebooks:"
printf '  - %s\n' "${CHANGED_DIRTY_NBS[@]}"

# Copy dirty -> clean
for src in "${CHANGED_DIRTY_NBS[@]}"; do
  dst="$CLEAN/$(basename "$src")"
  cp -f "$src" "$dst"
done

# Clean only the touched notebooks
uvx nb-clean clean "$CLEAN"

# Stage sanitized notebooks
git add "$CLEAN"/*.ipynb

exit 0