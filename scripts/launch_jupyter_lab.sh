#!/usr/bin/env bash
# Launch JupyterLab from the do-dd-client project venv (required for AnyWidget).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

NOTEBOOK="${1:-.}"
PORT="${JUPYTER_PORT:-8888}"
EXTRAS=(dev core tools)

uv_sync_args=()
for extra in "${EXTRAS[@]}"; do
  uv_sync_args+=(--extra "$extra")
done

uv sync "${uv_sync_args[@]}"

JUPYTER_LAB="$REPO_ROOT/.venv/bin/jupyter-lab"
if [[ ! -x "$JUPYTER_LAB" ]]; then
  echo "error: $JUPYTER_LAB not found — run: uv sync --extra dev --extra core --extra tools" >&2
  exit 1
fi

uv run "${uv_sync_args[@]}" python -m ipykernel install --sys-prefix \
  --name do-dd-client --display-name "Python (do-dd-client)"
uv run "${uv_sync_args[@]}" python -m ipykernel install --user \
  --name do-dd-client --display-name "Python (do-dd-client)"
uv run "${uv_sync_args[@]}" python scripts/verify_notebook_widgets.py

if command -v lsof >/dev/null 2>&1; then
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if [[ "$cmd" != *"$REPO_ROOT/.venv"* ]]; then
      echo ""
      echo "WARNING: port $PORT is used by a non-project Jupyter server:" >&2
      echo "  pid $pid: $cmd" >&2
      echo "  Stop it first: kill $pid" >&2
      echo "  Widgets will NOT render until you use this repo's .venv JupyterLab." >&2
      echo ""
    fi
  done < <(lsof -ti ":$PORT" 2>/dev/null || true)
fi

echo ""
echo "Starting JupyterLab from: $JUPYTER_LAB"
echo "  root_dir: $REPO_ROOT"
echo "  notebook: $NOTEBOOK"
echo "  kernel:   Python (do-dd-client)"
echo ""

exec uv run "${uv_sync_args[@]}" jupyter lab \
  --ServerApp.root_dir="$REPO_ROOT" \
  --ServerApp.port="$PORT" \
  "$NOTEBOOK"
