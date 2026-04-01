.PHONY:  test test-github jupyter install mock-server

SHELL := /bin/bash
uname=$(shell uname -s)
IMAGE_NAME := deeporigin-uv-temp
repo=$(shell basename $(CURDIR))


chosen_tests=""
org_key="deeporigin"

test: 
	uv run ruff format .
	uv run ruff check --select I . --fix
	uv run interrogate -c pyproject.toml -vv . -f 100 --omit-covered-files
	uv run pytest -x --failed-first -k $(chosen_tests) --env local --org_key $(org_key)
	uv run pytest -x docs --markdown-docs --markdown-docs-syntax=superfences --env local

# set up jupyter dev kernel
jupyter:
	uv run python -m ipykernel install --user --name $(repo) 
		

# install in a virtual env with all extras
install: install-pre-commit
	@echo "Installing deeporigin in editable mode in a venv..."
	uv sync --all-extras


docs-build:
	@echo "Building docs..."
	uv run --extra docs zensical build

docs-serve: install
	@echo "Serving docs locally on http://localhost:5566 ..."
	uv run --extra docs zensical serve --dev-addr localhost:5566

# run mock server for local development and testing
mock-server:
	@echo "Starting mock server..."
	uv run python -m tests.run_mock_server \
	    $(if $(PORT),--port $(PORT),) \
	    $(if $(ABFE_DURATION),--abfe-duration $(ABFE_DURATION),)


# Build image from current directory and start an interactive shell
docker:
	docker build --pull -t $(IMAGE_NAME) .
	docker run --rm -it $(IMAGE_NAME)


install-pre-commit:
	@echo "Installing pre-commit hook..."
	@mkdir -p .git/hooks
	@cp scripts/notebooks.sh .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "Pre-commit hook installed."