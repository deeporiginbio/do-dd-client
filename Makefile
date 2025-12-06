.PHONY:  test test-github jupyter install mock-server

SHELL := /bin/bash
uname=$(shell uname -s)

repo=$(shell basename $(CURDIR))


chosen_tests=""
org_key="deeporigin"

test: 
	uv run ruff format .
	uv run ruff check --select I . --fix
	uv run interrogate -c pyproject.toml -vv . -f 100 --omit-covered-files
	uv run pytest -x --failed-first -k $(chosen_tests) --env local --org_key $(org_key)
	uv run pytest -x docs --markdown-docs --markdown-docs-syntax=superfences

# set up jupyter dev kernel
jupyter:
	uv run python -m ipykernel install --user --name $(repo) 
		

# install in a virtual env with all extras
install:
	@echo "Installing deeporigin in editable mode in a venv..."
	uv sync --all-extras


docs-build:
	bash scripts/build_docs.sh

docs-serve:
	@echo "Serving docs locally..."
	uv run mkdocs serve

docs-deploy: 
	@echo "Deploying to live environment..."
	uv run mkdocs gh-deploy 

# run mock server for local development and testing
mock-server:
	@echo "Starting mock server..."
	uv run python -m tests.run_mock_server \
	    $(if $(PORT),--port $(PORT),) \
	    $(if $(ABFE_DURATION),--abfe-duration $(ABFE_DURATION),)


test-github-live:
	pytest -v --ignore=tests/test_config.py --ignore=tests/test_context.py


notebooks-html:
	@echo "Making marimo notebooks..."
	@source $(CURDIR)/venv/bin/activate && \
	rm -f docs/notebooks/*.html && \
	marimo export html notebooks/docking.py -o docs/notebooks/docking.html && \
	deactivate