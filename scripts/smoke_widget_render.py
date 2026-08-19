#!/usr/bin/env python3
"""Browser smoke test: JupyterLab renders the AnyWidget iframe bridge."""

from __future__ import annotations

from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request


def _repo_root() -> Path:
    """Return the do-dd-client repository root."""
    root = Path(__file__).resolve().parents[1]
    if not (root / "pyproject.toml").is_file():
        raise SystemExit(f"Could not locate repo root from {__file__}")
    return root


def _python(repo_root: Path) -> Path:
    """Return the project venv interpreter."""
    return repo_root / ".venv" / "bin" / "python"


def _wait_for_server(base_url: str, timeout_s: float = 45.0) -> None:
    """Poll the Jupyter server until it responds."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/lab", timeout=2) as response:
                if response.status == 200:
                    return
        except urllib.error.HTTPError as error:
            if error.code in {200, 302, 403}:
                return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.5)
    raise SystemExit(f"Jupyter server did not start at {base_url}")


def main() -> None:
    """Launch JupyterLab headlessly and confirm the widget iframe appears."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise SystemExit(
            "playwright is required for browser smoke test.\n"
            "Run: make smoke-widget-render"
        ) from error

    repo_root = _repo_root()
    python = _python(repo_root)
    port = 8899
    base_url = f"http://127.0.0.1:{port}"
    notebook_rel = "docs/notebooks/dirty/interactive-docking-box.ipynb"
    lab_url = f"{base_url}/lab/tree/{notebook_rel}?kernel_name=do-dd-client"

    server = subprocess.Popen(
        [
            str(python),
            "-m",
            "jupyter",
            "lab",
            "--no-browser",
            f"--ServerApp.port={port}",
            "--ServerApp.token=",
            "--ServerApp.password=",
            "--ServerApp.open_browser=False",
            f"--ServerApp.root_dir={repo_root}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_server(base_url)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(lab_url, wait_until="domcontentloaded", timeout=120_000)
            page.locator(".jp-NotebookPanel").wait_for(state="visible", timeout=120_000)

            page.get_by_role("menuitem", name="Run").click()
            page.get_by_role("menuitem", name="Run All Cells").click()

            iframe = page.locator("iframe[id^='do-bridge-']").first
            iframe.wait_for(state="attached", timeout=180_000)
            frame = iframe.content_frame
            if frame is None:
                raise SystemExit("AnyWidget iframe did not attach a content frame")
            frame.locator("#DeepOriginMolstarViewer").wait_for(
                state="visible",
                timeout=60_000,
            )
            browser.close()
        print("Browser smoke test OK: AnyWidget iframe rendered in JupyterLab")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
