.PHONY: test jupyter-lab install mock-server stop-jupyter

SHELL := /bin/bash
REPO_ROOT := $(CURDIR)

chosen_tests=""
org_key="deeporigin"
NOTEBOOK ?= .
JUPYTER_PORT ?= 8888
NOTEBOOK_EXTRAS := dev core tools
TEST_EXTRAS := test core tools plots
UV_RUN = uv run $(foreach e,$(NOTEBOOK_EXTRAS),--extra $(e))
UV_TEST_RUN = uv run $(foreach e,$(TEST_EXTRAS),--extra $(e))

test:
	uv run --extra lint ruff format .
	uv run --extra lint ruff check --select I . --fix
	$(UV_TEST_RUN) interrogate -c pyproject.toml -vv . -f 100 --omit-covered-files
	$(UV_TEST_RUN) pytest -x --failed-first -k $(chosen_tests) --env local --org_key $(org_key)
	$(UV_TEST_RUN) pytest -x docs --markdown-docs --markdown-docs-syntax=superfences --env local

# Launch JupyterLab from the project .venv (widgets require this server, not Homebrew / uv cache)
jupyter-lab:
	uv sync $(foreach e,$(NOTEBOOK_EXTRAS),--extra $(e))
	$(UV_RUN) jupyter lab \
		--ServerApp.root_dir="$(REPO_ROOT)" \
		--ServerApp.port=$(JUPYTER_PORT) \
		$(NOTEBOOK)

# kill JupyterLab on JUPYTER_PORT (use when a stale wrong-env server is bound)
stop-jupyter:
	@pids=$$(lsof -ti :$(JUPYTER_PORT) 2>/dev/null || true); \
	if [ -z "$$pids" ]; then \
	  echo "No process on port $(JUPYTER_PORT)"; \
	else \
	  echo "Killing port $(JUPYTER_PORT): $$pids"; \
	  kill $$pids; \
	fi

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
	    $(if $(ABFE_DURATION),--abfe-duration $(ABFE_DURATION),) \
	    $(if $(RBFE_DURATION),--rbfe-duration $(RBFE_DURATION),)

install-pre-commit:
	@echo "Installing pre-commit hook..."
	@mkdir -p .git/hooks
	@cp scripts/notebooks.sh .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "Pre-commit hook installed."
