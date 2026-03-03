"""Shared fixtures and helpers for tests."""

from typing import Optional

from deeporigin.platform import DeepOriginClient


def check_function_exists(
    client: DeepOriginClient,
    key: str,
    version: Optional[str] = None,
) -> bool:
    """Check if a function exists on the platform.

    Args:
        client: DeepOrigin client instance.
        key: Function key to look for.
        version: Optional version to match. If None, matches any version.

    Returns:
        True if the function exists (or env is local), False otherwise.
    """

    if client.env == "local":
        return True

    functions = client.functions.list()
    for fcn in functions:
        manifest = fcn["manifestBody"]
        if manifest["key"] == key:
            if version is None or manifest["version"] == version:
                return True
    return False
