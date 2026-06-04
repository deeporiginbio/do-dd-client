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

# Single registry for platform tools: iterate ``TOOL_KEYS_AND_VERSIONS``
# to verify tools are registered (see keys per entry below).
# Optional fields are omitted when not applicable.
TOOL_KEYS_AND_VERSIONS: dict[str, dict[str, str]] = {
    "docking": {
        "tool_key": "deeporigin.docking",
        "tool_version": "3.2.3",
    },
    "constrained_docking": {
        "tool_key": "deeporigin.constrained-docking",
        "tool_version": "3.2.3",
    },
    "pocket_finder": {
        "tool_key": "deeporigin.pocket-finder",
        "tool_version": "1.4.3",
    },
    "mol_props": {
        "tool_key": "deeporigin.mol-props-combined",
        "tool_version": "0.4.5",
    },
    "protonation": {
        "tool_key": "deeporigin.mol-props-protonation",
        "tool_version": "0.3.3",
    },
    "abfe": {
        "tool_key": "deeporigin.abfe-end-to-end",
        "tool_version": "0.3.3",
    },
    "rbfe": {
        "tool_key": "deeporigin.rbfe",
        "tool_version": "0.3.2",
    },
    "sysprep": {
        "tool_key": "deeporigin.system-prep",
        "tool_version": "0.16.3",
    },
}
