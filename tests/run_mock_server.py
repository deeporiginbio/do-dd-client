#!/usr/bin/env python3
"""Standalone script to run the mock server for local development and testing.

This script starts a local mock server that mimics the DeepOrigin Platform API.
It's useful for local development and testing without making real API calls.

Usage:
    python -m tests.run_mock_server [OPTIONS]

Options:
    PORT: Port number to run the server on (default: 8000)
    --abfe-duration SECONDS: Duration for ABFE executions in seconds (default: 300)

Examples:
    python -m tests.run_mock_server 8000
    python -m tests.run_mock_server --abfe-duration 600
    python -m tests.run_mock_server 8080 --abfe-duration 120
"""

from __future__ import annotations

import argparse

from tests.mock_server import MockServer


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
