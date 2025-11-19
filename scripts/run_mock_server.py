#!/usr/bin/env python3
"""Standalone script to run the mock server for local development and testing.

This script starts a local mock server that mimics the DeepOrigin Platform API.
It's useful for local development and testing without making real API calls.

Usage:
    python scripts/run_mock_server.py [OPTIONS]

Options:
    PORT: Port number to run the server on (default: 8000)
    --abfe-duration SECONDS: Duration for ABFE executions in seconds (default: 300)

Examples:
    python scripts/run_mock_server.py 8000
    python scripts/run_mock_server.py --abfe-duration 600
    python scripts/run_mock_server.py 8080 --abfe-duration 120
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

# Load mock_server module directly using importlib instead of modifying sys.path
# This is cleaner than sys.path manipulation and avoids polluting the import system
project_root = Path(__file__).parent.parent
mock_server_path = project_root / "tests" / "mock_server.py"
if not mock_server_path.exists():
    raise FileNotFoundError(
        f"Could not find mock_server.py at {mock_server_path}. "
        "Make sure you're running this script from the project root."
    )
spec = importlib.util.spec_from_file_location("mock_server", mock_server_path)
if spec is None or spec.loader is None:
    raise ImportError(f"Could not create module spec for {mock_server_path}")
mock_server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mock_server_module)
MockServer = mock_server_module.MockServer


def main() -> None:
    """Run the mock server."""
    parser = argparse.ArgumentParser(
        description="Run the DeepOrigin Platform API mock server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "port",
        type=int,
        nargs="?",
        default=8000,
        help="Port number to run the server on (default: 8000)",
    )
    parser.add_argument(
        "--abfe-duration",
        type=float,
        default=300.0,
        help="Duration for ABFE executions in seconds (default: 300)",
    )

    args = parser.parse_args()

    # Create MockServer instance
    server = MockServer(port=args.port)

    # Set execution durations
    server._mock_execution_durations["deeporigin.abfe-end-to-end"] = args.abfe_duration

    # Run with uvicorn directly - this blocks, which is fine for a dev script
    import uvicorn

    print(f"Starting mock server on http://127.0.0.1:{args.port}")
    print(f"ABFE execution duration: {args.abfe_duration} seconds")
    print("Press Ctrl+C to stop...")
    print()
    uvicorn.run(server.app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
