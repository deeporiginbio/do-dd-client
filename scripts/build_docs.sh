#!/bin/bash
# The purpose of this script is to catch any warnings
# during the docs build process and surface them as errors
# so that there are no missing links or other issues

set -euo pipefail

# Install dependencies (package + extras needed for notebooks, docs, and mock server)
echo "📦 Installing dependencies..."
uv sync --extra docs --extra core --extra tools --extra test --extra plots
echo "✅ Dependencies installed"

# Convert notebooks to HTML — same set as tests/test_notebooks.py (test_*_notebook)
DOC_NOTEBOOKS=(
  docs/notebooks/clean/pocketfinder.ipynb
  docs/notebooks/clean/pocket-finder-selection.ipynb
  docs/notebooks/clean/docking-single-ligand.ipynb
  docs/notebooks/clean/projects.ipynb
)
doc_notebooks_all_present=true
for _nb in "${DOC_NOTEBOOKS[@]}"; do
  if [ ! -f "$_nb" ]; then
    doc_notebooks_all_present=false
    break
  fi
done

if [ "$doc_notebooks_all_present" = true ]; then
  echo "📓 Converting notebooks to HTML..."
  mkdir -p docs/notebooks/html
  
  # Start mock server in background for local testing
  echo "🚀 Starting mock server..."
  uv run python -m tests.run_mock_server --port 4931 --abfe-duration 5 > /dev/null 2>&1 &
  MOCK_SERVER_PID=$!
  
  # Wait a moment for server to start
  sleep 2
  
  # Ensure mock server is stopped on exit (success or failure)
  trap 'kill $MOCK_SERVER_PID 2>/dev/null || true; rm -f .env' EXIT
  
  # Create .env file for notebook execution (client will auto-handle local env)
  echo "🔧 Setting up environment for local testing..."
  cat > .env << EOF
DO_ENV=local
JOB_WATCH_BLOCK=1
EOF
  
  # Register Python kernel for notebook execution
  echo "🔧 Registering Python kernel..."
  uv run python -m ipykernel install --user --name python3 --display-name "Python 3"
  
  # Convert notebooks to HTML with execution (only notebooks covered by test_notebooks.py)
  uv run jupyter nbconvert --to html --execute "${DOC_NOTEBOOKS[@]}" --output-dir docs/notebooks/html
  echo "✅ Notebooks converted and executed"
  
  # Stop mock server
  kill $MOCK_SERVER_PID 2>/dev/null || true
  trap - EXIT
fi

# Build docs and capture output
echo "📚 Building documentation..."
# Use a temp file to capture output while still showing it in real-time
ZENSICAL_OUTPUT_FILE=$(mktemp)
trap "rm -f $ZENSICAL_OUTPUT_FILE" EXIT

# Capture exit code from zensical (not tee) using PIPESTATUS
set +e  # Temporarily disable exit on error to capture exit code
uv run zensical build 2>&1 | tee "$ZENSICAL_OUTPUT_FILE"
BUILD_EXIT_CODE=${PIPESTATUS[0]}
set -e  # Re-enable exit on error

# Check if build failed
if [ "$BUILD_EXIT_CODE" -gt 0 ]; then
  echo "❌ Build failed with exit code $BUILD_EXIT_CODE"
  echo "Build output:"
  cat "$ZENSICAL_OUTPUT_FILE"
  exit "$BUILD_EXIT_CODE"
fi

# Read captured output for warning checking
ZENSICAL_OUT=$(cat "$ZENSICAL_OUTPUT_FILE")

# Check for warnings
WARNING_COUNT=$(echo "$ZENSICAL_OUT" | grep -c "WARNING" || true)
if [ "$WARNING_COUNT" -gt 0 ]; then
  echo "❌ Found $WARNING_COUNT WARNING(s) during docs build. Aborting."
  echo "Build output:"
  echo "$ZENSICAL_OUT"
  exit 1
fi

echo "✅ Built docs successfully with no warnings"





