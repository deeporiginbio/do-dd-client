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

# tool, function keys and versions
DOCKING_TOOL_KEY = "deeporigin.docking"
DOCKING_TOOL_VERSION = "3.0.0-29"
DOCKING_FUNCTION_KEY = "deeporigin.docking"
DOCKING_FUNCTION_VERSION = "2.0.0"

POCKET_FINDER_FUNCTION_KEY = "deeporigin.pocketfinder"
POCKET_FINDER_FUNCTION_VERSION = "0.5.4"

CONSTRAINED_DOCKING_FUNCTION_KEY = "deeporigin.constrained-docking"

MOL_PROPS_FUNCTION_KEY_PREFIX = "deeporigin.mol-props"
PROTONATION_FUNCTION_KEY = "deeporigin.mol-props-protonation"
MOL_PROPS_FUNCTION_VERSION = "0.2.0"

ABFE_TOOL_KEY = "deeporigin.abfe-end-to-end"
ABFE_TOOL_VERSION = "0.2.39"

RBFE_TOOL_KEY = "deeporigin.rbfe-end-to-end"
RBFE_TOOL_VERSION = "0.2.39"

SYSPREP_FUNCTION_KEY = "deeporigin.system-prep"
SYSPREP_FUNCTION_VERSION = "0.8.0"

FUNCTION_VERSION_MAP: dict[str, str] = {
    DOCKING_FUNCTION_KEY: DOCKING_FUNCTION_VERSION,
    POCKET_FINDER_FUNCTION_KEY: POCKET_FINDER_FUNCTION_VERSION,
    SYSPREP_FUNCTION_KEY: SYSPREP_FUNCTION_VERSION,
}
