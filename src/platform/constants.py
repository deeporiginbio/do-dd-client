"""Constants for platform API operations."""

from typing import Literal

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
DOCKING_TOOL_KEY = "deeporigin.bulk-docking"
DOCKING_TOOL_VERSION = "0.7.0"
DOCKING_FUNCTION_KEY = "deeporigin.docking"
DOCKING_FUNCTION_VERSION = "0.6.0"
POCKET_FINDER_FUNCTION_KEY = "deeporigin.pocketfinder"
POCKET_FINDER_FUNCTION_VERSION = "0.4.4"
