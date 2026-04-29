"""Constants for platform API operations."""

from typing import Literal

PlatformStatus = Literal[
    "Quoted",
    "Created",
    "Queued",
    "Running",
    "Succeeded",
    "Failed",
    "Cancelled",
    "InsufficientFunds",
    "FailedQuotation",
]

ALLOWED_STATUS_TRANSITIONS: dict[str | None, set[str]] = {
    None: {"Quoted", "Created"},
    "Quoted": {"Created", "Queued", "Running"},
    "Created": {"Queued", "Running", "Failed", "Cancelled"},
    "Queued": {"Running", "Failed", "Cancelled"},
    "Running": {"Succeeded", "Failed", "Cancelled"},
    "Succeeded": set(),
    "Failed": set(),
    "Cancelled": set(),
    "InsufficientFunds": set(),
    "FailedQuotation": set(),
}

# Terminal states for tool executions
TERMINAL_STATES = {
    "Succeeded",
    "Failed",
    "Cancelled",
    "Quoted",
    "InsufficientFunds",
    "FailedQuotation",
}

# Non-terminal states for tool executions
NON_TERMINAL_STATES = {"Created", "Queued", "Running"}

# Non-failed states for tool executions
NON_FAILED_STATES = {"Succeeded", "Running", "Queued", "Created"}

# Possible providers for files that work with the tools API
PROVIDER = Literal["ufa", "s3"]

# Single registry for platform tools/functions: iterate ``TOOL_KEYS_AND_VERSIONS``
# to verify tools and functions are registered (see keys per entry below).
# Optional fields are omitted when not applicable.
TOOL_KEYS_AND_VERSIONS: dict[str, dict[str, str]] = {
    "docking": {
        "tool_key": "deeporigin.docking",
        "tool_version": "3.1.11",
    },
    "pocket_finder": {
        "tool_key": "deeporigin.pocket-finder",
        "tool_version": "1.2.0",
    },
    "constrained_docking": {
        "function_key": "deeporigin.constrained-docking",
        "function_version": "2.0.2",
    },
    "mol_props": {
        "function_key_prefix": "deeporigin.mol-props",
        "protonation_function_key": "deeporigin.mol-props-protonation",
        "function_version": "0.2.0",
    },
    "abfe": {
        "tool_key": "deeporigin.abfe-end-to-end",
        "tool_version": "0.2.39",
    },
    "rbfe": {
        "tool_key": "deeporigin.rbfe-end-to-end",
        "tool_version": "0.2.39",
    },
    "sysprep": {
        "tool_key": "deeporigin.system-prep",
        "tool_version": "0.15.0",
    },
}
