"""Simplified configuration management for Deep Origin client.

This module stores and retrieves only two configuration values:
`env` and `org_key`.

Behavior:
- If the config file does not exist, it is created with `env=prod` and an
  empty `org_key`.
- If the config file exists, it is read and a dictionary is returned.
"""

import json
import os
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import pandas as pd

from deeporigin.utils.constants import ENV_VARIABLES
from deeporigin.utils.core import _ensure_do_folder, _supports_unicode_output

CONFIG_JSON_LOCATION = _ensure_do_folder() / "config.json"

__all__ = [
    "get_org",
    "set_org",
    "get_env",
    "set_env",
    "get_value",
    "CONFIG_JSON_LOCATION",
]


def _ensure_config_file_exists() -> None:
    """Ensure the configuration file exists; create with defaults if missing."""

    if not os.path.isfile(CONFIG_JSON_LOCATION):
        default_data: dict = {"env": "prod", "org_key": ""}
        os.makedirs(os.path.dirname(CONFIG_JSON_LOCATION), exist_ok=True)
        with open(CONFIG_JSON_LOCATION, "w") as file:
            json.dump(default_data, file, indent=2)


def get_org() -> str | None:
    """Get the organization key.

    Creates the config file with defaults if it doesn't exist.

    Returns:
        The organization key, or None if not set. Environment variables
        override the config file value.
    """
    return get_value()["org_key"]


def set_org(value: str) -> None:
    """Set the organization key.

    Args:
        value: The organization key to set.

    Raises:
        DeepOriginException: If the organization key does not exist in the
            list of accessible organizations.
    """
    from deeporigin.exceptions import DeepOriginException

    # Validate that the org key exists
    orgs_df = list_orgs()
    if value not in orgs_df["key"].values:
        available_keys = ", ".join(orgs_df["key"].tolist())
        raise DeepOriginException(
            title="Invalid organization key",
            message=f"Organization key '{value}' not found in accessible organizations.",
            fix=f"Available organization keys: {available_keys}",
            level="danger",
        )

    _set_value("org_key", value)


def get_env() -> str:
    """Get the environment.

    Creates the config file with defaults if it doesn't exist.

    Returns:
        The environment (e.g., 'prod', 'staging', 'edge', 'dev', 'local'). Defaults to 'prod'.
        Environment variables override the config file value.
    """
    return get_value()["env"]


def set_env(value: str) -> None:
    """Set the environment.

    Args:
        value: The environment to set (e.g., 'prod', 'staging', 'edge', 'dev', 'local').
    """
    _set_value("env", value)


def _set_value(key: Literal["env", "org_key"], value) -> None:
    """Internal helper to set a configuration value.

    Args:
        key: Configuration key to set (must be 'env' or 'org_key').
        value: Value to set.
    """
    _ensure_config_file_exists()

    with open(CONFIG_JSON_LOCATION, "r") as file:
        data = json.load(file) or {}

    data[key] = value

    # Persist updated data
    with open(CONFIG_JSON_LOCATION, "w") as file:
        json.dump(data, file, indent=2)

    # Prefer Unicode on capable terminals; fall back to ASCII-safe symbols
    if _supports_unicode_output():
        check, arrow = "✔︎", "→"
    else:
        check, arrow = "OK", "->"
    print(f"{check} {key} {arrow} {value}")


def get_value() -> dict:
    """Get the configuration values.

    Creates the file with defaults if it doesn't exist, then returns a dict
    with keys `env` and `org_key`.

    Args:
        config_file_location: Optional custom path for the config file.

    Returns:
        A dictionary with keys `env` and `org_key`.
    """

    _ensure_config_file_exists()

    with open(CONFIG_JSON_LOCATION, "r") as file:
        data = json.load(file) or {}

    # Fill defaults if missing
    env = data.get("env", "prod")
    org_key = data.get("org_key", None)

    # env variables override config file
    if ENV_VARIABLES["env"] in os.environ:
        env = os.environ[ENV_VARIABLES["env"]]
    if ENV_VARIABLES["org_key"] in os.environ:
        org_key = os.environ[ENV_VARIABLES["org_key"]]

    return {"env": env, "org_key": org_key}


def list_orgs() -> "pd.DataFrame":
    """List all organizations accessible to the authenticated user.

    Returns:
        A pandas DataFrame with columns: name, key, autoApproveMaxAmount, threshold.
    """
    import pandas as pd

    from deeporigin.platform.client import DeepOriginClient

    client = DeepOriginClient.get()
    orgs = client.organizations.list()

    # Extract only the required columns and map orgKey to key
    data = [
        {
            "name": org["name"],
            "key": org["orgKey"],
            "autoApproveMaxAmount": org["autoApproveMaxAmount"],
            "threshold": org["threshold"],
        }
        for org in orgs
    ]

    return pd.DataFrame(data)
