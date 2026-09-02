"""LigandSearch -- search vendor compound libraries for a query molecule.

Backed by the platform tool ``deeporigin.ligand-search``. One
:class:`LigandSearch` is configured with a query molecule, a ``search_mode`` and
the libraries to search, then executed with a blocking :meth:`run` or an
asynchronous :meth:`start`. Both return / yield a :class:`pandas.DataFrame` of
hits.

The tool exposes four ``search_mode`` values:

- ``EXACT`` -- InChIKey lookup against a catalog index.
- ``SUBSTRUCTURE`` -- SMARTS pattern match, smallest matches first.
- ``SIMILARITY_2D`` -- 2D fingerprint similarity (ECFP4 or ErG).
- ``SYNTHON`` -- searches un-enumerated combinatorial space by cutting the query
  at breakable bonds and reconstructing candidates from compatible synthons.

Not every library can serve every mode -- see
:data:`~deeporigin.utils.constants.LIGAND_SEARCH_MODE_LIBRARIES`. Selecting
several libraries fans out, merges into one globally re-ranked list, and applies
the result cap once.

``SYNTHON`` is markedly slower than the other modes (its cost is quadratic in
``synthon_prefilter_size``), so prefer :meth:`start` plus :meth:`wait` /
:meth:`watch` for it and :meth:`run` for the rest.

Usage::

    from deeporigin.drug_discovery import Ligand, LigandSearch

    query = Ligand.from_smiles("CC(=O)Nc1ccc(O)cc1")

    # 2D similarity across the catalog and Onepot
    search = LigandSearch(
        query=query,
        search_mode="SIMILARITY_2D",
        libraries=["enamine_hll", "onepot"],
    )
    hits = search.run()

    # Substructure search takes a SMARTS pattern
    hits = LigandSearch(
        smarts="c1ccccc1Br",
        search_mode="SUBSTRUCTURE",
        libraries=["enamine_hll"],
    ).run()

    # Synthon search is slow -- submit it asynchronously
    search = LigandSearch(
        query=query,
        search_mode="SYNTHON",
        libraries=["enamine_real_synthons"],
    )
    search.start()
    search.wait()
    hits = search.get_results()
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Self

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import (
    AsyncExecutableMixin,
    SyncExecutableMixin,
)
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status
from deeporigin.utils.constants import (
    LIGAND_SEARCH_DEFAULT_SYNTHON_PREFILTER_SIZE,
    LIGAND_SEARCH_DEFAULT_THRESHOLD,
    LIGAND_SEARCH_FINGERPRINTS,
    LIGAND_SEARCH_LIBRARIES,
    LIGAND_SEARCH_MAX_LIMIT,
    LIGAND_SEARCH_MODE_LIBRARIES,
    LIGAND_SEARCH_MODES,
    LIGAND_SEARCH_REACTION_RULES,
)

#: Modes for which ``synthon_prefilter_size`` and ``reaction_rules`` apply.
_SYNTHON_MODE = "SYNTHON"

#: Output key carrying the single pointer row that names the results CSV.
_RESULTS_KEY = "similarity_search_results"


class LigandSearch(
    Execution,
    SyncExecutableMixin,
    AsyncExecutableMixin,
    NotebookWatchMixin,
):
    """Search vendor compound libraries via ``deeporigin.ligand-search``.

    Configure the instance with a query molecule, a ``search_mode`` and the
    libraries to search, then call :meth:`run` (blocking) or :meth:`start`
    (asynchronous). Results are a :class:`pandas.DataFrame` of hit rows parsed
    from the tool's results CSV.

    The tool writes hits to a CSV in file storage and publishes a single pointer
    row naming it, rather than returning hit rows inline. :meth:`get_results`
    downloads and parses that CSV; :attr:`results_csv_path` exposes the remote
    path for callers that would rather hand it to something else.

    Attributes:
        search_mode: One of ``EXACT``, ``SUBSTRUCTURE``, ``SIMILARITY_2D``, ``SYNTHON``.
        libraries: Vendor libraries searched by this run.
        fingerprint: 2D fingerprint used for ``SIMILARITY_2D``.
        threshold: Minimum similarity for ``SIMILARITY_2D``.
        limit: Maximum hits returned, applied once after merging libraries.
        cap_hit: Whether the last run hit the result cap (the CSV is truncated),
            or ``None`` before results are read.
        row_count: Number of hit rows in the results CSV, or ``None`` before
            results are read.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["ligand_search"]["tool_key"]

    @beartype
    def __init__(
        self,
        *,
        query: Ligand | str | None = None,
        search_mode: str,
        libraries: list[str] | None = None,
        smarts: str | None = None,
        molblock: str | None = None,
        fingerprint: str = "ECFP4",
        threshold: float = LIGAND_SEARCH_DEFAULT_THRESHOLD,
        limit: int = LIGAND_SEARCH_MAX_LIMIT,
        synthon_prefilter_size: int = LIGAND_SEARCH_DEFAULT_SYNTHON_PREFILTER_SIZE,
        reaction_rules: str = "brics",
        self_test: bool = False,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["ligand_search"]["tool_version"],
        client: DeepOriginClient | None = None,
    ) -> None:
        """Configure a search over one or more vendor libraries.

        Args:
            query: Query molecule, either a
                :class:`~deeporigin.drug_discovery.structures.ligand.Ligand` or a
                SMILES string. Its ``id`` (when set) is echoed back as
                ``query_ligand_id`` in the pointer row. Omit only when
                ``self_test`` is true, or when supplying ``smarts`` / ``molblock``.
            search_mode: One of :data:`~deeporigin.utils.constants.LIGAND_SEARCH_MODES`.
            libraries: Vendor libraries to search; one or more of
                :data:`~deeporigin.utils.constants.LIGAND_SEARCH_LIBRARIES`.
                Several libraries fan out and merge into one re-ranked list.
            smarts: SMARTS pattern for ``SUBSTRUCTURE``. Takes precedence over a
                SMILES query for that mode.
            molblock: MDL molblock, accepted so a sketcher can supply a structure
                directly. Used when neither ``smarts`` nor a SMILES query applies.
            fingerprint: 2D fingerprint for ``SIMILARITY_2D``; ``ECFP4``
                (circular topological) or ``ERG`` (extended reduced graph).
            threshold: Minimum Tanimoto similarity for ``SIMILARITY_2D``.
                Defaults to 0.4 -- see
                :data:`~deeporigin.utils.constants.LIGAND_SEARCH_DEFAULT_THRESHOLD`.
            limit: Maximum hits to return (at most
                :data:`~deeporigin.utils.constants.LIGAND_SEARCH_MAX_LIMIT`),
                applied once after every library has been merged.
            synthon_prefilter_size: Synthons pulled from each label bucket before
                reconstruction (``SYNTHON`` only). Search cost is roughly
                quadratic in this value, so it is the dominant wall-time lever.
            reaction_rules: Rule set for ``SYNTHON``; must match the rules the
                synthon pool was built with.
            self_test: Search a tiny catalog index baked into the tool image,
                ignoring the query and libraries. Useful to check the tool is
                reachable.
            tool_version: Platform tool version to run. Settable so callers can
                pin or upgrade independently of the SDK release.
            client: Optional API client. Uses the default if not provided.

        Raises:
            ValueError: If ``search_mode`` is unknown, the query or libraries are
                missing or malformed, no selected library can serve the mode, or
                a numeric bound is exceeded.
        """
        super().__init__(client=client)
        self.tool_version = tool_version
        self._query = Ligand.from_smiles(query) if isinstance(query, str) else query
        self._search_mode = search_mode
        self._libraries = list(libraries) if libraries else []
        self._smarts = smarts
        self._molblock = molblock
        self._fingerprint = fingerprint
        self._threshold = threshold
        self._limit = limit
        self._synthon_prefilter_size = synthon_prefilter_size
        self._reaction_rules = reaction_rules
        self._self_test = self_test
        self._cap_hit: bool | None = None
        self._row_count: int | None = None
        self._results_csv_path: str | None = None
        self._validate()

    def _validate(self) -> None:
        """Validate the configured inputs for the selected ``search_mode``.

        Raises:
            ValueError: If any input is invalid for the selected mode.
        """
        if self._search_mode not in LIGAND_SEARCH_MODES:
            raise ValueError(
                f"Unknown search_mode {self._search_mode!r}. "
                f"Allowed: {sorted(LIGAND_SEARCH_MODES)}"
            )
        if self._fingerprint not in LIGAND_SEARCH_FINGERPRINTS:
            raise ValueError(
                f"Unknown fingerprint {self._fingerprint!r}. "
                f"Allowed: {sorted(LIGAND_SEARCH_FINGERPRINTS)}"
            )
        if self._reaction_rules not in LIGAND_SEARCH_REACTION_RULES:
            raise ValueError(
                f"Unknown reaction_rules {self._reaction_rules!r}. "
                f"Allowed: {sorted(LIGAND_SEARCH_REACTION_RULES)}"
            )
        if not (0.0 <= self._threshold <= 1.0):
            raise ValueError(
                f"threshold must be between 0 and 1, got {self._threshold}."
            )
        if not (1 <= self._limit <= LIGAND_SEARCH_MAX_LIMIT):
            raise ValueError(
                f"limit must be between 1 and {LIGAND_SEARCH_MAX_LIMIT}, "
                f"got {self._limit}."
            )
        if self._synthon_prefilter_size < 1:
            raise ValueError(
                "synthon_prefilter_size must be a positive integer, "
                f"got {self._synthon_prefilter_size}."
            )

        if self._self_test:
            return

        self._validate_query()
        self._validate_libraries()

    def _validate_query(self) -> None:
        """Validate that the selected mode has the query representation it needs.

        Raises:
            ValueError: If no usable query was supplied for the mode.
        """
        if self._search_mode == "SUBSTRUCTURE":
            if not self._smarts and not (self._query and self._query.smiles):
                raise ValueError(
                    "SUBSTRUCTURE requires a smarts pattern (or a query whose "
                    "SMILES is used as the pattern)."
                )
            return
        if self._smarts:
            raise ValueError(
                f"smarts is only used by SUBSTRUCTURE, not {self._search_mode!r}."
            )
        if not self._molblock and not (self._query and self._query.smiles):
            raise ValueError(
                f"{self._search_mode} requires a query molecule (a Ligand, a "
                "SMILES string, or a molblock)."
            )

    def _validate_libraries(self) -> None:
        """Validate the requested libraries against the mode's capability matrix.

        A library that cannot serve the mode contributes a warning and zero hits
        server-side, so a mixed selection is allowed. A selection where *no*
        library can serve the mode can only ever return nothing, so it is
        rejected here rather than after a round trip.

        Raises:
            ValueError: If ``libraries`` is empty, names an unknown library, or
                contains no library that can serve the mode.
        """
        if not self._libraries:
            raise ValueError(
                "libraries must name at least one vendor library. "
                f"Allowed: {sorted(LIGAND_SEARCH_LIBRARIES)}"
            )
        unknown = [lib for lib in self._libraries if lib not in LIGAND_SEARCH_LIBRARIES]
        if unknown:
            raise ValueError(
                f"Unknown libraries {unknown}. "
                f"Allowed: {sorted(LIGAND_SEARCH_LIBRARIES)}"
            )
        capable = LIGAND_SEARCH_MODE_LIBRARIES[self._search_mode]
        if not any(lib in capable for lib in self._libraries):
            raise ValueError(
                f"No selected library can serve {self._search_mode}. "
                f"{self._search_mode} is served by {sorted(capable)}, "
                f"but you selected {sorted(self._libraries)}."
            )

    @property
    def query(self) -> Ligand | None:
        """Query molecule for this search, if one was supplied (read-only)."""
        return self._query

    @property
    def search_mode(self) -> str:
        """Search mode for this run (read-only)."""
        return self._search_mode

    @property
    def libraries(self) -> list[str]:
        """Vendor libraries searched by this run (read-only)."""
        return list(self._libraries)

    @property
    def fingerprint(self) -> str:
        """2D fingerprint used for ``SIMILARITY_2D`` (read-only)."""
        return self._fingerprint

    @property
    def threshold(self) -> float:
        """Minimum similarity for ``SIMILARITY_2D`` (read-only)."""
        return self._threshold

    @property
    def limit(self) -> int:
        """Maximum hits returned after merging libraries (read-only)."""
        return self._limit

    @property
    def cap_hit(self) -> bool | None:
        """Whether the last run hit the result cap, truncating the CSV.

        ``None`` until results have been read.
        """
        return self._cap_hit

    @property
    def row_count(self) -> int | None:
        """Number of hit rows in the results CSV, or ``None`` before results are read."""
        return self._row_count

    @property
    def results_csv_path(self) -> str | None:
        """Remote path of the results CSV, or ``None`` before results are read."""
        return self._results_csv_path

    def __repr__(self) -> str:
        """Return a concise summary of this LigandSearch."""
        parts = [f"LigandSearch search_mode={self._search_mode!r}"]
        if self._libraries:
            parts.append(f"libraries={self._libraries!r}")
        if self.id:
            parts.append(f"id={self.id!r}")
        status = getattr(self, "status", None)
        if status:
            parts.append(f"status={status!r}")
        return f"<{' '.join(parts)}>"

    def _make_query_input(self) -> dict[str, Any]:
        """Build the ``query`` object for the tool payload."""
        query_input: dict[str, Any] = {}
        if self._query is not None and self._query.smiles:
            query_input["smiles"] = self._query.smiles
        if self._smarts:
            query_input["smarts"] = self._smarts
        if self._molblock:
            query_input["molblock"] = self._molblock
        if self._query is not None and self._query.id is not None:
            query_input["ligand_id"] = str(self._query.id)
        return query_input

    def _make_payload(
        self,
        *,
        approve_amount: int | None = None,
        sync: bool = True,
    ) -> dict[str, Any]:
        """Build the POST body for ``executions.create``.

        Mode-irrelevant parameters are omitted rather than sent at their
        defaults, so a stored payload reads as the search that was actually
        requested.

        Args:
            approve_amount: Spend cap forwarded as ``approveAmount`` when set.
            sync: ``True`` for blocking (direct) execution.

        Returns:
            Payload dict for ``executions.create``.
        """
        inputs: dict[str, Any] = {
            "search_mode": self._search_mode,
            "limit": self._limit,
        }
        if self._self_test:
            inputs["self_test"] = True
        else:
            inputs["query"] = self._make_query_input()
            inputs["libraries"] = list(self._libraries)

        if self._search_mode == "SIMILARITY_2D":
            inputs["fingerprint"] = self._fingerprint
            inputs["threshold"] = self._threshold
        elif self._search_mode == _SYNTHON_MODE:
            inputs["threshold"] = self._threshold
            inputs["synthon_prefilter_size"] = self._synthon_prefilter_size
            inputs["reaction_rules"] = self._reaction_rules

        payload: dict[str, Any] = {
            "inputs": inputs,
            "outputs": {},
            "metadata": {},
            "sync": sync,
        }
        if self.name is not None:
            payload["name"] = self.name
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount
        return payload

    @beartype
    def run(self) -> pd.DataFrame:
        """Execute the search synchronously (blocking) and return a DataFrame.

        ``SYNTHON`` searches can take minutes, because the reconstruction funnel
        costs roughly ``synthon_prefilter_size`` squared per cut. Prefer
        :meth:`start` plus :meth:`wait` or :meth:`watch` for that mode.

        Returns:
            A :class:`pandas.DataFrame` of hit rows, one per matched compound.

        Raises:
            DeepOriginException: If the execution did not complete successfully
                or no results could be parsed.
        """
        dto = self._create_execution(data=self._make_payload(sync=True))
        self.update_from_dto(dto)

        if not is_success_status(self.status):
            raise DeepOriginException(
                title="Ligand search did not complete",
                message=(
                    f"LigandSearch execution ended in {self.status!r} state "
                    f"(execution id {self.id!r})."
                ),
            )

        return self.get_results(dto)

    def _start_impl(self, *, approve_amount: int | None = None, **kwargs: Any) -> None:
        """Submit the search as a persisted async execution (``sync=False``).

        Sets :attr:`id`, :attr:`status`, and the cached DTO from the platform
        response. Poll :meth:`sync`, block with :meth:`wait`, or use
        :meth:`watch` in Jupyter until the execution reaches a terminal state,
        then call :meth:`get_results`.

        Args:
            approve_amount: Resolved spend cap forwarded to the platform.
            **kwargs: Unused extra keyword arguments from the mixin.

        Raises:
            ValueError: If the platform response carries no ``executionId``.
        """
        del kwargs
        execution_dto = self._create_execution(
            data=self._make_payload(approve_amount=approve_amount, sync=False)
        )
        execution_id = execution_dto.get("executionId")
        if execution_id is None:
            raise ValueError("Execution response must contain 'executionId'") from None

        self._dto = execution_dto
        self._id = execution_id
        self.status = execution_dto.get("status")

    @beartype
    def get_results(self, dto: dict[str, Any] | None = None) -> pd.DataFrame:
        """Return this search's hits as a :class:`pandas.DataFrame`.

        Reads ``jobOutputs`` from ``dto`` (or fetches it via
        ``client.executions.get`` when omitted, e.g. after :meth:`from_id`),
        then downloads and parses the results CSV it points at.

        Args:
            dto: Optional execution payload from ``executions.create`` /
                ``executions.get``. Passing it avoids an extra GET.

        Returns:
            A DataFrame of hit rows in
            :data:`~deeporigin.utils.constants.LIGAND_SEARCH_RESULTS_CSV_COLUMNS`
            order.

        Raises:
            ValueError: If :attr:`id` is unset.
            DeepOriginException: If the execution published no results pointer,
                or the pointer names no CSV.
        """
        exec_id = self._ensure_id()
        if dto is None:
            dto = self.client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
        job_outputs = dto.get("jobOutputs") if isinstance(dto, dict) else None
        if not isinstance(job_outputs, dict):
            job_outputs = {}

        csv_path = self._read_results_pointer(job_outputs)

        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = os.path.join(tmpdir, "results.csv")
            self.client.files.download(
                remote_path=csv_path,
                local_path=local_path,
            )
            return pd.read_csv(local_path)

    @beartype
    def download_results(self, local_path: str) -> str:
        """Download the raw results CSV to ``local_path`` without parsing it.

        Useful when the file is destined for
        ``deeporigin.import-dataset`` rather than for analysis in the session.

        Args:
            local_path: Where to write the CSV.

        Returns:
            ``local_path``, for chaining.

        Raises:
            ValueError: If :attr:`id` is unset.
            DeepOriginException: If the execution published no results pointer.
        """
        exec_id = self._ensure_id()
        dto = self.client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
        job_outputs = dto.get("jobOutputs") if isinstance(dto, dict) else None
        if not isinstance(job_outputs, dict):
            job_outputs = {}

        csv_path = self._read_results_pointer(job_outputs)
        self.client.files.download(remote_path=csv_path, local_path=local_path)
        return local_path

    def _read_results_pointer(self, job_outputs: dict[str, Any]) -> str:
        """Read the single pointer row and cache its metadata.

        Args:
            job_outputs: The execution's ``jobOutputs`` mapping.

        Returns:
            Remote path of the results CSV.

        Raises:
            DeepOriginException: If the pointer row or its CSV path is missing.
        """
        results = [
            row
            for row in (job_outputs.get(_RESULTS_KEY) or [])
            if isinstance(row, dict)
        ]
        if not results:
            raise DeepOriginException(
                title="No search results",
                message=f"The execution returned no {_RESULTS_KEY}.",
            )
        first = results[0]
        csv_path = first.get("csv_file_path")
        if not csv_path:
            raise DeepOriginException(
                title="No results CSV",
                message=f"{_RESULTS_KEY} is missing csv_file_path.",
            )

        self._cap_hit = bool(first.get("cap_hit", False))
        row_count = first.get("row_count")
        self._row_count = int(row_count) if row_count is not None else None
        self._results_csv_path = str(csv_path)
        return str(csv_path)

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct a ``LigandSearch`` from a tools execution DTO.

        Rehydrates the query and search parameters from ``userInputs`` (falling
        back to ``inputs`` for older payloads).

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client. Uses the default if not provided.

        Returns:
            A ``LigandSearch`` with ``id``, pricing fields, and domain inputs set.

        Raises:
            ValueError: If the stored inputs carry a missing or unknown
                ``search_mode``.
        """
        instance = super().from_dto(dto, client=client)
        inputs: dict[str, Any] = dto.get("userInputs") or dto.get("inputs") or {}

        search_mode = str(inputs.get("search_mode") or "")
        if search_mode not in LIGAND_SEARCH_MODES:
            raise ValueError(
                "Cannot rehydrate LigandSearch: stored inputs have an unknown "
                f"search_mode {search_mode!r}. Allowed: {sorted(LIGAND_SEARCH_MODES)}"
            )

        query_in = inputs.get("query") or {}
        query = None
        if query_in.get("smiles"):
            query = Ligand.from_smiles(str(query_in["smiles"]))
            if query_in.get("ligand_id") is not None:
                query.id = str(query_in["ligand_id"])

        instance._query = query
        instance._search_mode = search_mode
        instance._libraries = list(inputs.get("libraries") or [])
        instance._smarts = query_in.get("smarts")
        instance._molblock = query_in.get("molblock")
        instance._fingerprint = str(inputs.get("fingerprint", "ECFP4"))
        instance._threshold = float(
            inputs.get("threshold", LIGAND_SEARCH_DEFAULT_THRESHOLD)
        )
        instance._limit = int(inputs.get("limit", LIGAND_SEARCH_MAX_LIMIT))
        instance._synthon_prefilter_size = int(
            inputs.get(
                "synthon_prefilter_size", LIGAND_SEARCH_DEFAULT_SYNTHON_PREFILTER_SIZE
            )
        )
        instance._reaction_rules = str(inputs.get("reaction_rules", "brics"))
        instance._self_test = bool(inputs.get("self_test", False))
        instance._cap_hit = None
        instance._row_count = None
        instance._results_csv_path = None
        return instance
