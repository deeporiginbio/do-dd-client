"""Tests that execute Jupyter notebooks end-to-end."""

import os
from pathlib import Path
import sys

from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpec
from nbclient import NotebookClient
import nbformat

from deeporigin.utils.constants import JOB_WATCH_BLOCK_ENV

NOTEBOOKS_DIR = Path(__file__).resolve().parent.parent / "docs" / "notebooks" / "clean"


def _notebook_kernel_manager() -> KernelManager:
    """Kernel manager that always uses the active test interpreter.

    User-installed ``python3`` kernelspecs often pin an absolute venv path from
    another checkout (e.g. after moving ``~/code/cli`` → ``do-dd-client``).
    """
    km = KernelManager()
    km.kernel_name = ""
    km._kernel_spec = KernelSpec(
        argv=[
            sys.executable,
            "-m",
            "ipykernel_launcher",
            "-f",
            "{connection_file}",
        ],
        display_name="do-dd-client-pytest",
        language="python",
    )
    return km


def _execute_notebook(notebook_path: Path) -> None:
    """Execute a notebook using a kernel tied to the active test interpreter.

    Avoids relying on a user-installed ``python3`` kernelspec, which may point
    at another checkout's virtualenv.

    Args:
        notebook_path: Absolute path to the ``.ipynb`` file to execute.
    """
    notebook_path = notebook_path.resolve()
    nb = nbformat.read(notebook_path, as_version=4)
    client = NotebookClient(
        nb,
        timeout=600,
        km=_notebook_kernel_manager(),
        resources={"metadata": {"path": str(notebook_path.parent)}},
    )
    # Notebooks call the non-blocking NotebookWatchMixin.watch() by design
    # (it's what a real interactive session should do); headless execution
    # needs JOB_WATCH_BLOCK=1 so the cell waits for the job instead of
    # racing ahead, same as scripts/build_docs.sh does for the doc build.
    previous = os.environ.get(JOB_WATCH_BLOCK_ENV)
    os.environ[JOB_WATCH_BLOCK_ENV] = "1"
    try:
        client.execute()
    finally:
        if previous is None:
            os.environ.pop(JOB_WATCH_BLOCK_ENV, None)
        else:
            os.environ[JOB_WATCH_BLOCK_ENV] = previous


def test_pocketfinder_notebook():
    """Execute the pocketfinder notebook end-to-end."""
    _execute_notebook(NOTEBOOKS_DIR / "pocketfinder.ipynb")


def test_pocket_finder_selection_notebook():
    """Execute the pocket-finder define-by-selection notebook end-to-end."""
    _execute_notebook(NOTEBOOKS_DIR / "pocket-finder-selection.ipynb")


def test_docking_notebook():
    """Execute the docking notebook end-to-end."""
    _execute_notebook(NOTEBOOKS_DIR / "docking-single-ligand.ipynb")


def test_bulk_docking_notebook():
    """Execute the docking notebook end-to-end."""
    _execute_notebook(NOTEBOOKS_DIR / "docking-many-ligands.ipynb")


def test_projects_notebook():
    """Execute the docking notebook end-to-end."""
    _execute_notebook(NOTEBOOKS_DIR / "projects.ipynb")
