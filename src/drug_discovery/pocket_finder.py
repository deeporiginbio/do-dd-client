"""PocketFinder -- find binding pockets via synchronous or asynchronous execution.

Sync usage (blocking, returns pockets directly)::

    pf = PocketFinder(protein)
    pf.quote()           # populates pf.estimate
    pockets = pf.run()   # blocking; calls get_results(); populates pf.cost

Async usage (persisted execution, watch in notebook)::

    pf = PocketFinder(protein)
    pf.start()            # submits async; sets pf.id and pf.status
    await pf.watch()      # live Jupyter updates (or pf.sync() in a loop)
    pockets = pf.get_results()
"""

from __future__ import annotations

from typing import Any, Self

from beartype import beartype

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import (
    AsyncExecutableMixin,
    QuoteMixin,
    SyncExecutableMixin,
)
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS


class PocketFinder(
    Execution, QuoteMixin, SyncExecutableMixin, AsyncExecutableMixin, NotebookWatchMixin
):
    """Find binding pockets in a protein structure.

    The execution request body includes ``sync`` (``true`` = blocking, ``false`` =
    immediate DTO). :meth:`run` sets ``"sync": true`` and blocks until the run
    finishes. :meth:`start` and :meth:`quote` set ``"sync": false`` (non-blocking);
    ``start`` returns immediately with an execution DTO that you can poll with
    :meth:`sync` (or watch with :meth:`watch` / :meth:`watch_async` in Jupyter).
    Track async jobs with :meth:`sync`, :meth:`from_id`, and :meth:`list`.

    Attributes:
        protein: The protein to analyse.
        pocket_count: Maximum number of pockets to detect.
        pocket_min_size: Minimum pocket volume in cubic Angstroms.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_key"]

    def __init__(
        self,
        protein: Protein,
        *,
        pocket_count: int = 1,
        pocket_min_size: int = 30,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_version"],
        client: DeepOriginClient | None = None,
    ) -> None:
        """Create a PocketFinder for the given protein.

        Args:
            protein: Protein structure to search for pockets.
            pocket_count: Maximum number of pockets to detect. Defaults to 1.
            pocket_min_size: Minimum pocket size in cubic Angstroms. Defaults to 30.
            tool_version: Platform tool version to run. Settable so callers
                can pin or upgrade independently of the SDK release.
            client: Optional API client. Uses the default if not provided.
        """
        super().__init__(client=client)
        self.tool_version = tool_version
        self._protein = protein
        self._pocket_count = pocket_count
        self._pocket_min_size = pocket_min_size

    @property
    def protein(self) -> Protein:
        """The protein to analyse."""
        return self._protein

    @property
    def pocket_count(self) -> int:
        """Maximum number of pockets to detect."""
        return self._pocket_count

    @property
    def pocket_min_size(self) -> int:
        """Minimum pocket volume in cubic Angstroms."""
        return self._pocket_min_size

    def __repr__(self) -> str:
        """Return a concise summary of the PocketFinder."""
        parts = [f"PocketFinder protein={self.protein.id!r}"]
        if self.id:
            parts.append(f"id={self.id!r}")
        parts.append(f"pocket_count={self.pocket_count}")
        parts.append(f"pocket_min_size={self.pocket_min_size}")
        return f"<{' '.join(parts)}>"

    def _validate_pocket_params(self) -> None:
        """Raise if ``pocket_count`` or ``pocket_min_size`` are invalid."""
        if self._pocket_count < 1:
            raise ValueError("pocket_count must be at least 1") from None
        if self._pocket_min_size < 1:
            raise ValueError("pocket_min_size must be at least 1") from None

    def _ensure_protein_remote(self) -> None:
        """Upload/sync protein and ensure ``remote_path`` is set for the API."""
        self._validate_pocket_params()

        self._protein.sync(lazy=True, client=self.client)
        self._protein.ensure_remote_path(client=self.client, label="Protein")

    def _make_payload(
        self,
        *,
        sync: bool = True,
        approve_amount: int | None = None,
    ) -> dict[str, Any]:
        """Build the POST body for ``executions.create``.

        ``sync`` lives inside ``inputs`` because the pocket-finder tool
        definition declares it as an input property; the platform's
        estimator reads ``inputs.sync`` to choose direct serving (sync) vs.
        Argo workflow (async). A top-level ``sync`` would be silently dropped
        and the AJV default (``true``) used instead.
        """
        payload: dict[str, Any] = {
            "inputs": {
                "protein": {
                    "file_path": self._protein.remote_path,
                    "id": self._protein.id,
                },
                "pocket_count": self._pocket_count,
                "pocket_min_size": self._pocket_min_size,
                "sync": sync,
            },
            "outputs": {},
            "metadata": {},
        }
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount
        return payload

    def _get_quote(self) -> dict[str, Any]:
        """Return the tools API execution DTO for a quotation (``approveAmount=0``)."""

        return self.client.executions.create(  # ty:ignore[unresolved-attribute]
            data=self._make_payload(sync=False, approve_amount=0),
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )

    @staticmethod
    def _parse_inputs_dict(inputs: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
        """Return ``protein`` input dict, ``pocket_count``, and ``pocket_min_size``."""
        protein_input = inputs.get("protein") or {}
        protein_id = protein_input.get("id")
        if protein_id is None:
            raise ValueError(
                "Missing 'protein.id' in execution userInputs; "
                "this execution may have been created with an older input schema."
            )
        raw_count = inputs.get("pocket_count")
        raw_min_size = inputs.get("pocket_min_size")
        try:
            pocket_count = int(raw_count) if raw_count is not None else 1
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid pocket_count in execution inputs.") from exc
        try:
            pocket_min_size = int(raw_min_size) if raw_min_size is not None else 30
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid pocket_min_size in execution inputs.") from exc
        if pocket_count < 1:
            raise ValueError("pocket_count from execution inputs must be at least 1")
        if pocket_min_size < 1:
            raise ValueError("pocket_min_size from execution inputs must be at least 1")
        return protein_input, pocket_count, pocket_min_size

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct a ``PocketFinder`` from a tools execution DTO.

        Rehydrates ``protein``, ``pocket_count``, and ``pocket_min_size`` from
        ``userInputs`` (falling back to ``inputs`` for older payloads). The
        protein is loaded with ``Protein.from_id(..., download=False)`` and
        ``remote_path_override`` from the stored input, matching
        :meth:`_make_payload` / :meth:`Docking.from_dto`.

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client. Uses the default if not provided.

        Returns:
            A ``PocketFinder`` with ``id``, pricing fields, and domain inputs set.

        Raises:
            ValueError: If ``protein.id`` is missing from stored inputs.
        """
        instance = super().from_dto(dto, client=client)
        inputs: dict[str, Any] = dto.get("userInputs") or dto.get("inputs") or {}
        protein_input, pocket_count, pocket_min_size = cls._parse_inputs_dict(inputs)

        instance._protein = Protein.from_id(
            str(protein_input["id"]),
            client=client,
            download=False,
            remote_path_override=protein_input.get("file_path"),
        )
        instance._pocket_count = pocket_count
        instance._pocket_min_size = pocket_min_size

        return instance

    @beartype
    def get_results(self, dto: dict[str, Any] | None = None) -> list[Pocket]:
        """Load pockets for this execution from the data platform or ``jobOutputs``.

        Tries :meth:`~deeporigin.drug_discovery.structures.pocket.Pocket.from_result`
        first. On failure, parses ``jobOutputs.pockets`` from ``dto``, or from
        ``client.executions.get`` when ``dto`` is omitted (for example after
        :meth:`~deeporigin.drug_discovery.execution.Execution.from_id`).

        Args:
            dto: Optional execution payload (``executions.create`` /
                ``executions.get``). Passing it avoids an extra GET when the data
                platform path fails but the sync response included ``jobOutputs``.

        Returns:
            List of ``Pocket`` objects for this execution.

        Raises:
            ValueError: If :attr:`id` is unset.
            DeepOriginException: If no pockets could be loaded from the data
                platform or ``jobOutputs``.
        """
        exec_id = self._ensure_id()

        try:
            return Pocket.from_result(
                execution_id=exec_id,
                client=self.client,
            )
        except Exception:
            pass

        try:
            if dto is None:
                dto = self.client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
            jo = dto.get("jobOutputs")
            raw = jo.get("pockets", []) if isinstance(jo, dict) else []
            return Pocket.from_json(raw, client=self.client)
        except Exception:
            raise DeepOriginException(
                title="Could not load pockets",
                message=(
                    "No pockets could be parsed from the data platform or jobOutputs."
                ),
            ) from None

    @beartype
    def run(self, *, approve_amount: int | None = None) -> list[Pocket]:
        """Execute pocket finding synchronously (blocking).

        Submits one synchronous tools execution (``sync=True``) and returns the
        detected pockets via :meth:`get_results`. The server blocks until the
        run completes; use :meth:`start` for async, persisted execution.

        Returns:
            List of ``Pocket`` objects found in the protein.

        Raises:
            DeepOriginException: If no pockets could be loaded from the data
                platform or ``jobOutputs``.
        """
        self._ensure_protein_remote()
        dto = self.client.executions.create(  # ty:ignore[unresolved-attribute]
            data=self._make_payload(
                sync=True,
                approve_amount=approve_amount,
            ),
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )
        self.update_from_dto(dto)

        return self.get_results(dto)

    def _start_impl(self, **kwargs: Any) -> None:
        """Submit pocket finding as a persisted async execution (``sync=False``).

        Sets :attr:`id`, :attr:`status`, and :attr:`_execution_dto` from the
        platform response. Poll :meth:`sync` or use :meth:`watch` /
        :meth:`watch_async` in Jupyter until the execution reaches a terminal
        state, then call :meth:`get_results` to retrieve the pockets.
        """
        self._ensure_protein_remote()
        execution_dto = self.client.executions.create(  # ty:ignore[unresolved-attribute]
            data=self._make_payload(sync=False),
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )
        execution_id = execution_dto.get("executionId")
        if execution_id is None:
            raise ValueError("Execution response must contain 'executionId'") from None

        self._execution_dto = execution_dto
        self._id = execution_id
        self.status = execution_dto.get("status")
