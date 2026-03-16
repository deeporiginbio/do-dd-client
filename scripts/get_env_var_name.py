#!/usr/bin/env python3
"""Extract environment variable names from constants.py.

This script reads the ENV_VARIABLES dictionary from src/utils/constants.py
and outputs the environment variable name for a given key.

The purpose of this script is to maintain a single source of truth for
environment variable names. By reading from constants.py, we ensure that
GitHub Actions workflows and other scripts always use the correct variable
names without hardcoding them. If the variable names change in constants.py,
this script will automatically reflect those changes.

Usage:
    python scripts/get_env_var_name.py <key>

Where <key> is one of: access_token, org_key, env
"""

from pathlib import Path
import re
import sys

# Get the project root (assuming script is in scripts/)
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
CONSTANTS_FILE = PROJECT_ROOT / "src" / "utils" / "constants.py"


def get_env_var_name(key: str) -> str:
    """Extract environment variable name from constants.py for the given key.

    Args:
        key: The key in ENV_VARIABLES dict (e.g., 'access_token', 'org_key', 'env')

    Returns:
        The environment variable name (e.g., 'DO_AUTH_TOKEN')
    """
    if not CONSTANTS_FILE.exists():
        # Fallback values if file doesn't exist
        fallbacks = {
            "access_token": "DO_AUTH_TOKEN",
            "org_key": "DO_ORG_KEY",
            "env": "DO_ENV",
        }
        return fallbacks.get(key, "")

    content = CONSTANTS_FILE.read_text()
    # Match pattern like "'access_token': 'DO_AUTH_TOKEN'"
    pattern = rf"'{key}':\s*'([^']+)'"
    match = re.search(pattern, content)

    if match:
        return match.group(1)

    # Fallback values if regex doesn't match
    fallbacks = {
        "access_token": "DO_AUTH_TOKEN",
        "org_key": "DO_ORG_KEY",
        "env": "DO_ENV",
    }
    return fallbacks.get(key, "")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <key>", file=sys.stderr)
        print("Where <key> is one of: access_token, org_key, env", file=sys.stderr)
        sys.exit(1)

    key = sys.argv[1]
    env_var_name = get_env_var_name(key)
    print(env_var_name)
