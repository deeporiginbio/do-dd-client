"""Constants for platform API operations."""

from typing import Literal

LEGACY_SUCCEEDED_STATUS = "Succeeded"
CANONICAL_SUCCESS_STATUS = "Completed"

PlatformStatus = Literal[
    "Quoted",
    "Created",
    "Queued",
    "Running",
    "Completed",
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
    "Running": {"Completed", "Failed", "Cancelled"},
    "Completed": set(),
    "Succeeded": set(),
    "Failed": set(),
    "Cancelled": set(),
    "InsufficientFunds": set(),
    "FailedQuotation": set(),
}

# Terminal states for tool executions
TERMINAL_STATES = {
    "Completed",
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
NON_FAILED_STATES = {"Completed", "Running", "Queued", "Created"}


def normalize_platform_status(status: str | None) -> str | None:
    """Map legacy ``Succeeded`` to canonical ``Completed``.

    Args:
        status: Raw platform execution status from an API DTO.

    Returns:
        Normalized status, or ``None`` when ``status`` is ``None``.
    """
    if status == LEGACY_SUCCEEDED_STATUS:
        return CANONICAL_SUCCESS_STATUS
    return status


def is_success_status(status: str | None) -> bool:
    """Return whether ``status`` is a terminal-success execution state.

    Args:
        status: Platform execution status (raw or normalized).

    Returns:
        ``True`` for ``Completed`` or legacy ``Succeeded``.
    """
    return status in {CANONICAL_SUCCESS_STATUS, LEGACY_SUCCEEDED_STATUS}


def display_platform_status(status: str | None) -> str:
    """Return the user-facing label for a platform execution status.

    Args:
        status: Platform execution status (raw or normalized).

    Returns:
        Display label; legacy ``Succeeded`` is shown as ``Completed``.
    """
    if status is None or not str(status).strip():
        return "New"
    normalized = normalize_platform_status(str(status).strip())
    return normalized if normalized is not None else "New"


# Possible providers for files that work with the tools API
PROVIDER = Literal["ufa", "s3"]

# Single registry for platform tools: iterate ``TOOL_KEYS_AND_VERSIONS``
# to verify tools are registered (see keys per entry below).
# Optional fields are omitted when not applicable.
TOOL_KEYS_AND_VERSIONS: dict[str, dict[str, str]] = {
    "docking": {
        "tool_key": "deeporigin.docking",
        "tool_version": "3",
    },
    "constrained_docking": {
        "tool_key": "deeporigin.constrained-docking",
        "tool_version": "3",
    },
    "pocket_finder": {
        "tool_key": "deeporigin.pocket-finder",
        "tool_version": "1",
    },
    "mol_props": {
        "tool_key": "deeporigin.mol-props-combined",
        "tool_version": "latest",
    },
    "protonation": {
        "tool_key": "deeporigin.mol-props-protonation",
        "tool_version": "latest",
    },
    "konnektor": {
        "tool_key": "deeporigin.konnektor",
        "tool_version": "latest",
    },
    "abfe": {
        "tool_key": "deeporigin.abfe-end-to-end",
        "tool_version": "latest",
    },
    "rbfe": {
        "tool_key": "deeporigin.rbfe",
        "tool_version": "latest",
    },
    "sysprep": {
        "tool_key": "deeporigin.system-prep",
        "tool_version": "1",
    },
    "protein_prep": {
        "tool_key": "deeporigin.protein-prep",
        "tool_version": "latest",
    },
    "patent": {
        "tool_key": "deeporigin.draco",
        "tool_version": "latest",
    },
    "enumerator": {
        "tool_key": "deeporigin.enumerator",
        "tool_version": "latest",
    },
    "admet": {
        "tool_key": "deeporigin.admet-properties",
        "tool_version": "latest",
    },
    "metabolism": {
        "tool_key": "deeporigin.metabolism",
        "tool_version": "latest",
    },
    "import_dataset": {
        "tool_key": "deeporigin.import-dataset",
        "tool_version": "latest",
    },
}
