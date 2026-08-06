#!/usr/bin/env python3
"""Verify Jupyter notebook widget dependencies and kernel wiring for do-dd-client."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def _repo_root() -> Path:
    """Return the do-dd-client repository root."""
    root = Path(__file__).resolve().parents[1]
    if not (root / "pyproject.toml").is_file():
        raise SystemExit(f"Could not locate repo root from {__file__}")
    return root


def _expected_python(repo_root: Path) -> Path:
    """Return the project venv interpreter path."""
    for name in ("python", "python3"):
        candidate = repo_root / ".venv" / "bin" / name
        if candidate.is_file():
            return candidate.resolve()
    raise SystemExit(f"No interpreter found under {repo_root / '.venv' / 'bin'}")


def _check_interpreter(repo_root: Path) -> None:
    """Fail when the active interpreter is not the project venv."""
    expected = _expected_python(repo_root).resolve()
    actual = Path(sys.executable).resolve()
    if actual != expected:
        raise SystemExit(
            "Wrong Python interpreter for notebook widgets.\n"
            f"  active:   {actual}\n"
            f"  expected: {expected}\n"
            "Run `make jupyter` from do-dd-client and select kernel "
            "'Python (do-dd-client)'."
        )


def _check_imports() -> tuple[str, str]:
    """Import widget packages and return their versions."""
    try:
        import anywidget
        import ipywidgets
    except ImportError as error:
        raise SystemExit(
            "Missing notebook widget dependencies.\n"
            f"  {error}\n"
            "Run: uv sync --extra dev --extra core --extra tools"
        ) from error
    return anywidget.__version__, ipywidgets.__version__


def _check_kernelspec(repo_root: Path) -> Path:
    """Ensure the do-dd-client kernelspec points at the project venv."""
    candidates = [
        repo_root / ".venv" / "share" / "jupyter" / "kernels" / "do-dd-client",
        Path.home() / "Library" / "Jupyter" / "kernels" / "do-dd-client",
        Path.home() / ".local" / "share" / "jupyter" / "kernels" / "do-dd-client",
    ]
    for path in candidates:
        kernel_json = path / "kernel.json"
        if not kernel_json.is_file():
            continue
        spec = json.loads(kernel_json.read_text(encoding="utf-8"))
        argv = spec.get("argv") or []
        if not argv:
            continue
        kernel_python = Path(argv[0]).resolve()
        expected = _expected_python(repo_root).resolve()
        if kernel_python != expected:
            raise SystemExit(
                "Jupyter kernel 'do-dd-client' points at the wrong interpreter.\n"
                f"  kernel:   {kernel_python}\n"
                f"  expected: {expected}\n"
                "Run: make jupyter"
            )
        return path
    raise SystemExit(
        "Jupyter kernel 'do-dd-client' is not installed.\nRun: make jupyter"
    )


def _check_labextensions(repo_root: Path) -> None:
    """Ensure anywidget and jupyterlab-widgets labextensions are enabled."""
    labextension = repo_root / ".venv" / "bin" / "jupyter-labextension"
    if not labextension.is_file():
        raise SystemExit(
            "jupyter-labextension is not installed in the project venv.\n"
            "Run: uv sync --extra dev --extra core --extra tools"
        )
    result = subprocess.run(
        [str(labextension), "list"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(
            "Could not inspect JupyterLab extensions.\n"
            f"{result.stderr or result.stdout}"
        )
    output = f"{result.stdout}\n{result.stderr}"
    for needle in ("anywidget", "@jupyter-widgets/jupyterlab-manager"):
        matching_lines = [line for line in output.splitlines() if needle in line]
        if not matching_lines:
            raise SystemExit(
                f"Missing JupyterLab extension: {needle}\n"
                "Run: uv sync --extra dev --extra core --extra tools"
            )
        line = matching_lines[0]
        if "enabled" not in line or "OK" not in line:
            raise SystemExit(f"JupyterLab extension not healthy: {needle}\n{line}")


def _check_widget_mime(repo_root: Path) -> None:
    """Execute a widget display in the registered kernel and inspect mime output."""
    from jupyter_client import KernelManager

    km = KernelManager(kernel_name="do-dd-client")
    km.start_kernel()
    kc = km.client()
    kc.start_channels()
    kc.wait_for_ready(timeout=30)

    code = """
from deeporigin.utils.iframe_comm_bridge import _IframeCommWidget
from IPython.display import display
display(_IframeCommWidget(
    bridge_id="verify",
    iframe_src="data:text/html,<html><body>verify</body></html>",
    height=120,
))
"""
    msg_id = kc.execute(code)
    found_widget = False
    while True:
        msg = kc.get_iopub_msg(timeout=15)
        if msg["parent_header"].get("msg_id") != msg_id:
            continue
        if (
            msg["msg_type"] == "status"
            and msg["content"].get("execution_state") == "idle"
        ):
            break
        if msg["msg_type"] == "display_data":
            data = msg["content"].get("data", {})
            if "application/vnd.jupyter.widget-view+json" in data:
                found_widget = True
                break
    km.shutdown_kernel(now=True)
    if not found_widget:
        raise SystemExit("Kernel did not emit application/vnd.jupyter.widget-view+json")


def main() -> None:
    """Run all notebook widget environment checks."""
    repo_root = _repo_root()
    _check_interpreter(repo_root)
    anywidget_version, ipywidgets_version = _check_imports()
    kernelspec_dir = _check_kernelspec(repo_root)
    _check_labextensions(repo_root)
    _check_widget_mime(repo_root)
    print("Notebook widget environment OK")
    print(f"  python:     {Path(sys.executable).resolve()}")
    print(f"  anywidget:  {anywidget_version}")
    print(f"  ipywidgets: {ipywidgets_version}")
    print(f"  kernel:     {kernelspec_dir}")


if __name__ == "__main__":
    main()
