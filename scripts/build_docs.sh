#!/bin/bash
# The purpose of this script is to catch any warnings
# during the docs build process and surface them as errors
# so that there are no missing links or other issues

set -euo pipefail

# Convert notebooks to HTML if they exist
if [ -d "docs/notebooks/clean" ] && [ "$(ls -A docs/notebooks/clean/*.ipynb 2>/dev/null)" ]; then
  echo "📓 Converting notebooks to HTML..."
  mkdir -p docs/notebooks/html
  
  # Create .env file for notebook execution
  echo "🔧 Creating .env file for notebook execution..."
  cat > .env << EOF
DEEPORIGIN_ORG_KEY=deeporigin
DEEPORIGIN_ENV=local
JOB_WATCH_BLOCK=1
DEEPORIGIN_TOKEN=${DEEPORIGIN_TOKEN:-}
EOF
  
  # Convert notebooks to HTML with execution
  uvx jupyter nbconvert --to html --execute docs/notebooks/clean/*.ipynb --output-dir docs/notebooks/html
  echo "✅ Notebooks converted and executed"
  
  # Clean up .env file
  rm -f .env
fi

# Install dependencies if running in CI
if [ "${CI:-false}" = "true" ]; then
  echo "🚧 Running in CI, installing dependencies using uv..."
  uv sync --extra docs
  echo "✅ Dependencies installed"
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





