#!/usr/bin/env bash
set -euo pipefail

NOTEBOOKS_DIR="docs/notebooks"
DIRTY="${NOTEBOOKS_DIR}/dirty"
CLEAN="${NOTEBOOKS_DIR}/clean"

# Skip Jupyter scratch notebooks (e.g. Untitled.ipynb, Untitled1.ipynb).
is_untitled_notebook() {
    local name_lower
    name_lower="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
    [[ "$name_lower" =~ ^untitled[0-9]*\.ipynb$ ]]
}

# List .ipynb files in dirty/ modified since the last commit (or all if no commits yet).
find_dirty_notebooks_since_last_commit() {
    if [ ! -d "$DIRTY" ]; then
        return 0
    fi

    if git rev-parse --verify HEAD >/dev/null 2>&1; then
        local since
        since="$(git log -1 --format=%ci)"
        find "$DIRTY" -maxdepth 1 -name '*.ipynb' -type f -newermt "$since" 2>/dev/null || true
    else
        find "$DIRTY" -maxdepth 1 -name '*.ipynb' -type f 2>/dev/null || true
    fi
}

mkdir -p "$CLEAN"

CHANGED_NOTEBOOKS=()
while IFS= read -r notebook; do
    [ -n "$notebook" ] || continue
    name="$(basename "$notebook")"
    if is_untitled_notebook "$name"; then
        echo "Skipping untitled notebook: $name"
        continue
    fi
    CHANGED_NOTEBOOKS+=("$notebook")
done < <(find_dirty_notebooks_since_last_commit)

if [ ${#CHANGED_NOTEBOOKS[@]} -eq 0 ]; then
    echo "No dirty notebooks modified since last commit, skipping."
    exit 0
fi

echo "Sanitizing ${#CHANGED_NOTEBOOKS[@]} notebook(s)..."

CLEAN_NOTEBOOKS=()
for dirty_notebook in "${CHANGED_NOTEBOOKS[@]}"; do
    name="$(basename "$dirty_notebook")"
    clean_notebook="${CLEAN}/${name}"

    cp "$dirty_notebook" "$clean_notebook"
    CLEAN_NOTEBOOKS+=("$clean_notebook")
done

uvx nb-clean clean "${CLEAN_NOTEBOOKS[@]}"

echo "Removing kernel metadata from notebooks..."
for notebook in "${CLEAN_NOTEBOOKS[@]}"; do
    uvx jupyter nbconvert \
        --clear-output \
        --ClearMetadataPreprocessor.enabled=True \
        --inplace "$notebook"
done

git add "${CLEAN_NOTEBOOKS[@]}"

exit 0
