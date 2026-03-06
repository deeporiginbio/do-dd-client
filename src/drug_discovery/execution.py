"""Base class for the jobs-centric API.

Provides ``Execution`` -- a base class with read-only ``@property`` descriptors
for system-managed fields and lifecycle state management.  Subclasses also
expose immutable input fields as read-only properties and compose with mixins
(``QuoteMixin``, ``SyncExecutableMixin``, ``AsyncExecutableMixin``) to build
concrete execution types like ``PocketFinder``, ``Docking``, and ``ABFE``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deeporigin.platform.constants import ALLOWED_STATUS_TRANSITIONS

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


class Execution:
    """Base class for all execution types in the jobs-centric API.

    System-managed fields (``id``, ``estimate``, ``cost``) are exposed as
    read-only properties.  Subclasses should use the same ``@property``
    pattern for user-supplied input fields that must not change after
    construction.

    Attributes:
        id: Platform execution ID, set after ``start()`` or by ``from_id()``.
        estimate: Cost estimate in dollars, set by ``quote()``.
        cost: Actual cost in dollars, set after execution completes.
        tool_key: Platform tool key identifying this execution type.
        tool_version: Version of the tool to use.
    """

    tool_key: str = ""

    def __init__(self, *, client: DeepOriginClient | None = None) -> None:
        super().__init__()
        self._id: str | None = None
        self._estimate: float | None = None
        self._cost: float | None = None

        if client is None:
            from deeporigin.platform.client import DeepOriginClient

            client = DeepOriginClient.get()
        self.client: DeepOriginClient = client

    @property
    def id(self) -> str | None:
        """Platform execution ID, set after ``start()`` or by ``from_id()``

        id cannot be set manually."""
        return self._id

    @property
    def estimate(self) -> float | None:
        """Cost estimate in dollars, set by ``quote()``. None until ``quote()`` is called.

        This property cannot be set manually."""
        return self._estimate

    @property
    def cost(self) -> float | None:
        """Actual cost in dollars, set after execution completes.

        This property cannot be set manually."""
        return self._cost

    def _set_status(self, new_status: str) -> None:
        """Validate and apply a lifecycle state transition.

        Args:
            new_status: The target status to transition to.

        Raises:
            ValueError: If the transition from the current status is not allowed.
        """
        current = getattr(self, "status", None)
        allowed = ALLOWED_STATUS_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid status transition: {current!r} -> {new_status!r}. "
                f"Allowed transitions from {current!r}: {allowed}"
            )
        self.status = new_status

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
