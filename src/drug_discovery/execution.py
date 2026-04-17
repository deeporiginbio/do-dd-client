"""Base class for the jobs-centric API.

Provides ``Execution`` -- a base class with read-only ``@property`` descriptors
for system-managed fields and lifecycle state management.  Subclasses also
expose immutable input fields as read-only properties and compose with mixins
(``QuoteMixin``, ``SyncExecutableMixin``, ``AsyncExecutableMixin``) to build
concrete execution types like ``PocketFinder``, ``Docking``, and ``ABFE``.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, Self

from deeporigin.platform.constants import ALLOWED_STATUS_TRANSITIONS

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

# Kwargs understood by :meth:`Results.get_poses` (not raw :meth:`Results.get`).
_RESULTS_GET_POSE_KWARGS = frozenset(
    {"best_pose", "protein_id", "ligand_id", "tool_version", "effort"}
)


class Execution:
    """Base class for all execution types in the jobs-centric API.

    System-managed fields ``estimate`` and ``cost`` are exposed as read-only
    properties. Platform execution ``id`` is defined on
    :class:`~deeporigin.drug_discovery.execution_mixins.QuoteMixin` (typical job
    classes include that mixin). Subclasses should use the same ``@property``
    pattern for user-supplied input
    fields that must not change after construction.

    Attributes:
        estimate: Cost estimate in dollars, set by ``quote()``.
        cost: Actual cost in dollars, set after execution completes.
        name: Optional user label; writable until execution ``id`` is set, then read-only.
        tool_key: Platform tool key identifying this execution type.
        tool_version: Version of the tool to use.
    """

    tool_key: str = ""

    def __init__(self, *, client: DeepOriginClient | None = None) -> None:
        super().__init__()
        self._estimate: float | None = None
        self._cost: float | None = None
        self._name: str | None = None

        if client is None:
            from deeporigin.platform.client import DeepOriginClient

            client = DeepOriginClient()
        self.client: DeepOriginClient = client

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

    @property
    def name(self) -> str | None:
        """Optional user-defined label for this execution.

        May be set or changed only while ``id`` is unset. After an execution
        ID exists, ``name`` is read-only."""
        return self._name

    @name.setter
    def name(self, value: str | None) -> None:
        """Set ``name`` only before the platform assigns an execution ``id``."""
        if getattr(self, "_id", None) is not None:
            raise AttributeError("cannot assign to 'name': execution id is already set")
        self._name = value

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

    def duplicate(self, *, client: DeepOriginClient | None = None) -> Self:
        """Create a fresh copy with the same configuration but no execution state.

        Useful after ``from_id()`` to re-run the same calculation.  The
        returned instance has no ``id``, ``status``, ``estimate``, or
        ``cost`` — it is ready for ``quote()`` / ``start()``.

        Args:
            client: Optional API client for the new instance.
                Falls back to the current instance's client.

        Returns:
            A new instance sharing the same domain-specific configuration.
        """
        new = copy.copy(self)
        if hasattr(new, "_id"):
            new._id = None
        new._estimate = None
        new._cost = None
        for attr in ("status", "progress", "_execution_dto"):
            if hasattr(new, attr):
                delattr(new, attr)
        if client is not None:
            new.client = client
        return new

    def get_results(self, **kwargs: Any) -> Any:
        """Fetch results for this execution from the data platform.

        Args:
            **kwargs: Passed to :meth:`deeporigin.platform.results.Results.get`,
                or to :meth:`~deeporigin.platform.results.Results.get_poses` when
                any pose-specific filter is set (``best_pose``, ``protein_id``,
                ``ligand_id``, ``tool_version``, ``effort``). ``limit`` and
                ``select`` are forwarded to whichever call is used.

        Returns:
            Result-explorer response dict with ``data`` and ``meta`` keys.

        Raises:
            ValueError: If the execution has no ID yet.
            TypeError: If unknown keyword arguments are passed, or if
                ``filter_dict`` is combined with pose-specific arguments
                (``best_pose``, ``protein_id``, etc.).
        """
        exec_id = getattr(self, "_id", None)
        if exec_id is None:
            raise ValueError(
                "Cannot get results: no execution has been started (id is None)."
            )
        limit = kwargs.pop("limit", None)
        select = kwargs.pop("select", None)
        filter_dict = kwargs.pop("filter_dict", None)

        pose_keys = _RESULTS_GET_POSE_KWARGS & kwargs.keys()
        if pose_keys and filter_dict is not None:
            raise TypeError(
                "get_results() cannot combine filter_dict with pose-specific "
                f"arguments ({', '.join(sorted(pose_keys))})."
            )

        if pose_keys:
            return self.client.results.get_poses(
                compute_job_id=exec_id,
                limit=limit,
                select=select,
                **kwargs,
            )

        if kwargs:
            bad = ", ".join(sorted(kwargs))
            raise TypeError(f"get_results() got unexpected keyword arguments: {bad}")

        return self.client.results.get(
            filter_dict=filter_dict,
            compute_job_id=exec_id,
            limit=limit,
            select=select,
        )

    def __repr__(self) -> str:
        """Return a concise summary of the execution."""
        parts: list[str] = [type(self).__name__]
        if self._name is not None:
            parts.append(f"name={self._name!r}")
        exec_id = getattr(self, "_id", None)
        if exec_id:
            parts.append(f"id={exec_id!r}")
        status = getattr(self, "status", None)
        if status:
            parts.append(f"status={status!r}")
        if self.estimate is not None:
            parts.append(f"estimate=${self.estimate:.2f}")
        if self.cost is not None:
            parts.append(f"cost=${self.cost:.2f}")
        return f"<{' '.join(parts)}>"
