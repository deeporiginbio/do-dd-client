#!/bin/bash
# The purpose of this script is to catch any warnings
# during the docs build process and surface them as errors
# so that there are no missing links or other issues

set -euo pipefail

# Install dependencies (package + extras needed for notebooks, docs, and mock server)
echo "📦 Installing dependencies..."
uv sync --extra docs --extra core --extra tools --extra test --extra plots
echo "✅ Dependencies installed"

# Convert notebooks to HTML if they exist
if [ -d "docs/notebooks/clean" ] && [ "$(ls -A docs/notebooks/clean/*.ipynb 2>/dev/null)" ]; then
  echo "📓 Converting notebooks to HTML..."
  mkdir -p docs/notebooks/html
  
  # Start mock server in background for local testing
  echo "🚀 Starting mock server..."
  uv run python -m tests.run_mock_server --port 4931 > /dev/null 2>&1 &
  MOCK_SERVER_PID=$!
  
  # Wait a moment for server to start
  sleep 2
  
  # Ensure mock server is stopped on exit (success or failure)
  trap 'kill $MOCK_SERVER_PID 2>/dev/null || true; rm -f .env' EXIT
  
  # Create .env file for notebook execution (client will auto-handle local env)
  echo "🔧 Setting up environment for local testing..."
  cat > .env << EOF
DEEPORIGIN_ENV=local
JOB_WATCH_BLOCK=1
EOF
  
  # Register Python kernel for notebook execution
  echo "🔧 Registering Python kernel..."
  uv run python -m ipykernel install --user --name python3 --display-name "Python 3"
  
  # Convert notebooks to HTML with execution
  uv run jupyter nbconvert --to html --execute docs/notebooks/clean/*.ipynb --output-dir docs/notebooks/html
  echo "✅ Notebooks converted and executed"
  
  # Stop mock server
  kill $MOCK_SERVER_PID 2>/dev/null || true
  trap - EXIT
fi

# Build docs and capture output
echo "📚 Building documentation..."
MKDOCS_OUT="$(uv run mkdocs build -s 2>&1)"
BUILD_EXIT_CODE=$?

# Check if build failed
if [ "$BUILD_EXIT_CODE" -gt 0 ]; then
  echo "❌ Build failed with exit code $BUILD_EXIT_CODE"
  echo "Build output:"
  echo "$MKDOCS_OUT"
  exit "$BUILD_EXIT_CODE"
fi

# Check for warnings
WARNING_COUNT=$(echo "$MKDOCS_OUT" | grep -c "WARNING" || true)
if [ "$WARNING_COUNT" -gt 0 ]; then
  echo "❌ Found $WARNING_COUNT WARNING(s) during docs build. Aborting."
  echo "Build output:"
  echo "$MKDOCS_OUT"
  exit 1
fi

echo "✅ Built docs successfully with no warnings"





