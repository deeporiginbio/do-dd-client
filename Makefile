.PHONY: docker test test-github jupyter jupyter-lab install mock-server prototype-ddos-6937 demo-interactive-docking-box stop-jupyter smoke-widget-render

SHELL := /bin/bash
uname=$(shell uname -s)
IMAGE_NAME := deeporigin-uv-temp
repo=$(shell basename $(CURDIR))
KERNEL_NAME := do-dd-client
REPO_ROOT := $(CURDIR)

chosen_tests=""
org_key="deeporigin"
NOTEBOOK ?= .
JUPYTER_PORT ?= 8888
NOTEBOOK_EXTRAS := dev core tools
UV_RUN = uv run $(foreach e,$(NOTEBOOK_EXTRAS),--extra $(e))

test:
	uv run --extra lint ruff format .
	uv run --extra lint ruff check --select I . --fix
	uv run --extra test interrogate -c pyproject.toml -vv . -f 100 --omit-covered-files
	uv run --extra test pytest -x --failed-first -k $(chosen_tests) --env local --org_key $(org_key)
	uv run --extra test pytest -x docs --markdown-docs --markdown-docs-syntax=superfences --env local

# Sync notebook deps, register kernel in .venv + user dir, verify widget env.
jupyter:
	uv sync $(foreach e,$(NOTEBOOK_EXTRAS),--extra $(e))
	$(UV_RUN) python -m ipykernel install --sys-prefix --name $(KERNEL_NAME) --display-name "Python (do-dd-client)"
	$(UV_RUN) python -m ipykernel install --user --name $(KERNEL_NAME) --display-name "Python (do-dd-client)"
	$(UV_RUN) python scripts/verify_notebook_widgets.py

# launch JupyterLab from the project .venv (widgets require this server, not Homebrew / uv cache)
jupyter-lab: jupyter
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

# headless browser smoke: AnyWidget iframe renders in JupyterLab
smoke-widget-render: jupyter
	$(UV_RUN) --with playwright python scripts/smoke_widget_render.py

# open DDOS-6937 interactive box wireframe notebook (throwaway prototype)
prototype-ddos-6937:
	@chmod +x scripts/launch_jupyter_lab.sh
	JUPYTER_PORT=$(JUPYTER_PORT) scripts/launch_jupyter_lab.sh \
		prototypes/ddos-6937-interactive-box-wireframe/wireframe.ipynb

# interactive docking box demo — MUST use this launcher (not Homebrew / parent-dir jupyter)
demo-interactive-docking-box:
	@chmod +x scripts/launch_jupyter_lab.sh
	JUPYTER_PORT=$(JUPYTER_PORT) scripts/launch_jupyter_lab.sh \
		docs/notebooks/dirty/interactive-docking-box.ipynb

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

docker:
	docker build --pull -t $(IMAGE_NAME) .
	docker run --rm -it $(IMAGE_NAME)

install-pre-commit:
	@echo "Installing pre-commit hook..."
	@mkdir -p .git/hooks
	@cp scripts/notebooks.sh .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "Pre-commit hook installed."
