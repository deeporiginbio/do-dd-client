"""Tests that execute Jupyter notebooks end-to-end via nbconvert."""

from pathlib import Path
import subprocess

NOTEBOOKS_DIR = Path(__file__).resolve().parent.parent / "docs" / "notebooks" / "clean"


def _execute_notebook(notebook_path: Path) -> None:
    """Execute a notebook with nbconvert and delete the output on success.

    Runs ``jupyter nbconvert --execute`` to produce an executed copy, asserts
    a zero exit code, then removes the output file.

    Args:
        notebook_path: Absolute path to the ``.ipynb`` file to execute.
    """
    output_path = notebook_path.with_name(
        notebook_path.stem + "_executed" + notebook_path.suffix
    )

    try:
        result = subprocess.run(
            [
                "jupyter",
                "nbconvert",
                "--to",
                "notebook",
                "--execute",
                str(notebook_path),
                "--output",
                str(output_path.name),
            ],
            cwd=str(notebook_path.parent),
            capture_output=True,
            text=True,
            timeout=600,
        )

        assert result.returncode == 0, (
            f"Notebook {notebook_path.name} failed with exit code {result.returncode}.\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )
    finally:
        if output_path.exists():
            output_path.unlink()


def test_pocketfinder_notebook():
    """Execute the pocketfinder notebook end-to-end."""
    _execute_notebook(NOTEBOOKS_DIR / "pocketfinder.ipynb")


def test_docking_notebook():
    """Execute the docking notebook end-to-end."""
    _execute_notebook(NOTEBOOKS_DIR / "docking-single-ligand.ipynb")
