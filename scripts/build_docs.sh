# The purpose of this script is to catch any warnings
# during the docs built process and surface them as errors
# so that there are no missing links or other issues



if [ "$CI" = "true" ]; then
  echo "Running in GitHub Actions runner, installing repo."
  echo "🚧 Installing repo using uv..."
  uv sync --extra docs
  echo "Installed using uv."
  MKDOCS_OUT="$(uv run mkdocs build -s 2>&1)"

else
  echo "Running Locally, will not install."
  MKDOCS_OUT="$(uv run mkdocs build -s 2>&1)"
fi



if [ "$?" -gt 0 ]; then
  echo "Something went wrong building docs. The error is:";
  echo $MKDOCS_OUT
  exit 3;
fi
warnings=$(echo $MKDOCS_OUT | grep "WARNING" | wc -l)
if [ "$warnings" -gt 0 ]; then
  echo "WARNINGS were found when making docs; aborting. The output of `mkdocs build --strict` is:";
  echo $MKDOCS_OUT
  exit 4;
fi

echo "Built docs successfully"





