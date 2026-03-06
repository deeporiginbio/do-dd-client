"""Base class for the jobs-centric API.

Provides ``Execution`` -- a base class with read-only attribute enforcement,
lifecycle state management, and scoped internal mutation via ``_system_update``.
Subclasses declare their own immutable input fields and compose with mixins
(``QuoteMixin``, ``SyncExecutableMixin``, ``AsyncExecutableMixin``) to build
concrete execution types like ``PocketFinder``, ``Docking``, and ``ABFE``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

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


class Execution:
    """Base class for all execution types in the jobs-centric API.

    Enforces read-only semantics on system-managed fields (``id``, ``estimate``,
    ``cost``) and immutability on user-supplied input fields declared by
    subclasses via ``_immutable_fields``.

    Attributes:
        id: Platform execution ID, set after ``start()`` or by ``from_id()``.
        estimate: Cost estimate in dollars, set by ``quote()``.
        cost: Actual cost in dollars, set after execution completes.
        tool_key: Platform tool key identifying this execution type.
        tool_version: Version of the tool to use.
    """

    tool_key: str = ""
    tool_version: str = ""

    _readonly_fields: frozenset[str] = frozenset({"id", "estimate", "cost"})
    _immutable_fields: frozenset[str] = frozenset()

    _allowed_transitions: dict[str | None, set[str]] = {
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

    def __init__(self) -> None:
        with self._system_update():
            self.id: str | None = None
            self.estimate: float | None = None
            self.cost: float | None = None
            self._internal_write = False
        self._client: DeepOriginClient | None = None

    def __setattr__(self, name: str, value: object) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return

        writing = getattr(self, "_internal_write", True)
        if not writing:
            protected = self._readonly_fields | self._immutable_fields
            if name in protected:
                raise AttributeError(
                    f"Cannot set '{name}' directly. "
                    f"This field is managed by the system."
                )

        object.__setattr__(self, name, value)

    @contextmanager
    def _system_update(self):
        """Context manager that temporarily allows writes to protected fields."""
        object.__setattr__(self, "_internal_write", True)
        try:
            yield
        finally:
            object.__setattr__(self, "_internal_write", False)

    def _set_status(self, new_status: str) -> None:
        """Validate and apply a lifecycle state transition.

        Args:
            new_status: The target status to transition to.

        Raises:
            ValueError: If the transition from the current status is not allowed.
        """
        current = getattr(self, "status", None)
        allowed = self._allowed_transitions.get(current, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid status transition: {current!r} -> {new_status!r}. "
                f"Allowed transitions from {current!r}: {allowed}"
            )
        with self._system_update():
            self.status = new_status

    def _resolve_client(self) -> DeepOriginClient:
        """Return the client, falling back to the default singleton."""
        if self._client is not None:
            return self._client
        from deeporigin.platform.client import DeepOriginClient

        return DeepOriginClient.get()

    def __repr__(self) -> str:
        """Return a concise summary of the execution."""
        parts: list[str] = [type(self).__name__]
        if self.id:
            parts.append(f"id={self.id!r}")
        status = getattr(self, "status", None)
        if status:
            parts.append(f"status={status!r}")
        if self.estimate is not None:
            parts.append(f"estimate=${self.estimate:.2f}")
        if self.cost is not None:
            parts.append(f"cost=${self.cost:.2f}")
        return f"<{' '.join(parts)}>"
