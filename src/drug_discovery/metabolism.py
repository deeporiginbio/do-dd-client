"""Metabolism -- predict sites of metabolism for ligands.

Backed by the platform tool ``deeporigin.metabolism``. One :class:`Metabolism`
instance is configured with ligands, then executed with a blocking
:meth:`run` (small batches) or asynchronous :meth:`start` (larger batches).
:meth:`run` returns a :class:`pandas.DataFrame` of Metabolism site rows
(atom, enzyme, site confidence). :meth:`get_molecules` returns
molecule-level ``confidence_tier`` rows for **this execution**.

Class-level :meth:`fetch_results` / :meth:`fetch_molecules` load indexed
rows for a ligand set from the data platform (any past jobs) by
``ligand_id``. Before ``run`` / ``start``, if every ligand has a platform id
and every id already has a Metabolism molecule, the client refuses (no
execution). If the job still proceeds and any id is already indexed, it
warns. There is no force/recompute path.

The tool scores every cytochrome P450 isoform it supports; the client does
not select or filter enzymes. ``tool_version`` stays ``"latest"``. Ligands
are not mutated. Payload ``id`` is sent only when
:attr:`~deeporigin.drug_discovery.structures.ligand.Ligand.id` is already set.

Sync usage (blocking; fewer than 30 ligands)::

    from deeporigin.drug_discovery import Metabolism, Ligand

    job = Metabolism(ligands=Ligand.from_smiles("CCO"))
    sites = job.run()
    mols = job.get_molecules()

Async usage (30 or more ligands, or any size)::

    job = Metabolism(ligands=ligands)
    job.start()
    await job.watch()  # or job.wait()
    sites = job.get_results()
    mols = job.get_molecules()

Fetch indexed rows without starting a job::

    sites = Metabolism.fetch_results(ligands=ligands)
    mols = Metabolism.fetch_molecules(ligands=ligands)
"""

from __future__ import annotations

from typing import Any, Self
import warnings

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import (
    AsyncExecutableMixin,
    SyncExecutableMixin,
)
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status
from deeporigin.utils.constants import (
    METABOLISM_EXECUTION_TIMEOUT_SECONDS,
    METABOLISM_LIGAND_ID_QUERY_BATCH_SIZE,
    METABOLISM_RESULT_EXPLORER_PAGE_SIZE,
    METABOLISM_WORKFLOW_LIGAND_THRESHOLD,
)

_SITE_COLUMNS: tuple[str, ...] = (
    "ligand_id",
    "smiles",
    "atom_index",
    "enzyme",
    "confidence",
)
_MOLECULE_COLUMNS: tuple[str, ...] = (
    "ligand_id",
    "smiles",
    "confidence_tier",
)
# Platform catalog base entities (``filter.result_type`` = x-data-type base,
# not ``x-result-group``). Matches toolbox MetabolismMolecule skip filter.
_RESULT_TYPE_SITES = "metabolismsite"
_RESULT_TYPE_MOLECULES = "metabolismmolecule"


def _normalize_ligands(
    ligands: Ligand | list[Ligand] | LigandSet,
) -> list[Ligand]:
    """Return a list of ligands from a constructor ``ligands=`` value.

    Args:
        ligands: A single ligand, a list, or a :class:`LigandSet`.

    Returns:
        A new list of the ligands to score.

    Raises:
        ValueError: If the result is empty.
    """

    if isinstance(ligands, LigandSet):
        out = list(ligands.ligands)
    elif isinstance(ligands, Ligand):
        out = [ligands]
    else:
        out = list(ligands)
    if not out:
        raise ValueError("Metabolism requires at least one ligand.")
    return out


def _metabolism_default_name(ligand_count: int) -> str:
    """Build a short human-readable label for a Metabolism execution.

    Args:
        ligand_count: Number of ligands in the run.

    Returns:
        A string such as ``Site of Metabolism for 12 ligands``.
    """
    suffix = "ligand" if ligand_count == 1 else "ligands"
    return f"Site of Metabolism for {ligand_count} {suffix}"


def _job_output_rows(dto: dict[str, Any], *, key: str) -> list[dict[str, Any]]:
    """Return dict rows from ``jobOutputs[key]``.

    Args:
        dto: Execution payload from ``executions.create`` / ``executions.get``.
        key: ``sites`` or ``molecules``.

    Returns:
        Dict rows, or an empty list when the key is missing or not a list.
    """

    job_outputs = dto.get("jobOutputs")
    if not isinstance(job_outputs, dict):
        return []
    rows = job_outputs.get(key)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _rows_from_result_explorer(response: Any) -> list[dict[str, Any]]:
    """Extract nested ``data`` payloads from a result-explorer search response.

    Expands whole-schema wrappers (``metabolismmolecules`` / ``metabolismsites``
    lists) the same way the toolbox skip filter does. Flat molecule/site
    dicts pass through unchanged.

    Args:
        response: Return value of :meth:`deeporigin.platform.results.Results.get`.

    Returns:
        Dict rows from each record's ``data`` field, or an empty list.
    """

    if not isinstance(response, dict):
        return []
    records = response.get("data")
    if not isinstance(records, list):
        return []
    rows: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        data = record.get("data")
        if isinstance(data, dict):
            rows.extend(_expand_metabolism_payload(data))
    return rows


def _expand_metabolism_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return flat Metabolism site/molecule dicts from a result ``data`` payload.

    Args:
        payload: Nested ``data`` object from a result-explorer record.

    Returns:
        One or more row dicts. Empty when the payload is not a recognized shape.
    """

    for wrapper_key in ("metabolismmolecules", "metabolismsites"):
        nested = payload.get(wrapper_key)
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
    # Flat MQ / HTTP row shapes.
    if "confidence_tier" in payload or "enzyme" in payload or "atom_index" in payload:
        return [payload]
    return []


def _ordered_dataframe(
    rows: list[dict[str, Any]],
    *,
    columns: tuple[str, ...],
) -> pd.DataFrame:
    """Build a DataFrame with *columns* first, then any extras.

    Args:
        rows: Result dicts.
        columns: Preferred column order.

    Returns:
        A DataFrame with the requested columns that exist, then extras.
        When *rows* is empty, returns an empty DataFrame with *columns*.
    """

    if not rows:
        return pd.DataFrame(columns=list(columns))
    df = pd.DataFrame(rows)
    ordered = [c for c in columns if c in df.columns]
    extra = [c for c in df.columns if c not in ordered]
    return df[ordered + extra]


def _ligands_from_inputs(inputs: dict[str, Any]) -> list[Ligand]:
    """Rebuild ligands from stored metabolism ``userInputs``.

    Args:
        inputs: ``userInputs`` or ``inputs`` from an execution DTO.

    Returns:
        Ligands with SMILES and optional platform ids restored.

    Raises:
        ValueError: If ligands are missing or a row has no SMILES.
    """

    raw = inputs.get("ligands")
    if not isinstance(raw, list) or not raw:
        raise ValueError("Cannot rehydrate Metabolism: stored inputs have no ligands.")
    ligands: list[Ligand] = []
    for idx, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(
                f"Cannot rehydrate Metabolism: ligands[{idx}] is not an object."
            )
        smiles = row.get("smiles")
        if not smiles or not isinstance(smiles, str):
            raise ValueError(
                f"Cannot rehydrate Metabolism: ligands[{idx}] has no SMILES."
            )
        ligand = Ligand.from_smiles(smiles)
        if row.get("id") is not None:
            ligand.id = str(row["id"])
        ligands.append(ligand)
    return ligands


def _resolve_client(client: DeepOriginClient | None) -> DeepOriginClient:
    """Return *client* or construct the default :class:`DeepOriginClient`.

    Args:
        client: Optional API client.

    Returns:
        A usable :class:`DeepOriginClient`.
    """

    return client if client is not None else DeepOriginClient()


def _platform_ligand_ids(ligands: list[Ligand]) -> list[str]:
    """Return non-empty platform ligand ids in input order (duplicates kept).

    Args:
        ligands: Ligands that may or may not have ``id`` set.

    Returns:
        Stripped id strings for ligands that have a platform id.
    """

    ids: list[str] = []
    for lig in ligands:
        raw = lig.id
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            ids.append(text)
    return ids


def _unique_preserve_order(values: list[str]) -> list[str]:
    """Return unique strings preserving first-seen order.

    Args:
        values: Possibly duplicated strings.

    Returns:
        Deduplicated list.
    """

    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _rows_for_ligand_ids(
    client: DeepOriginClient,
    *,
    ligand_ids: list[str],
    result_type: str,
) -> list[dict[str, Any]]:
    """Load result-explorer ``data`` payloads for *ligand_ids* and *result_type*.

    Args:
        client: Platform API client.
        ligand_ids: Platform ligand ids to query (may be empty).
        result_type: Catalog base entity (e.g. ``metabolismsite``).

    Returns:
        Nested ``data`` dicts from matching records (may be empty/partial).
    """

    unique_ids = _unique_preserve_order(ligand_ids)
    if not unique_ids:
        return []

    rows: list[dict[str, Any]] = []
    batch_size = METABOLISM_LIGAND_ID_QUERY_BATCH_SIZE
    for start in range(0, len(unique_ids), batch_size):
        batch = unique_ids[start : start + batch_size]
        response = client.results.get(
            filter_dict={"ligand_id": {"in": batch}},
            result_type=result_type,
            limit=None,
            page_size=METABOLISM_RESULT_EXPLORER_PAGE_SIZE,
        )
        rows.extend(_rows_from_result_explorer(response))
    return rows


def _ligand_ids_with_metabolism_molecule(
    client: DeepOriginClient,
    *,
    ligand_ids: list[str],
) -> set[str]:
    """Return the subset of *ligand_ids* that have indexed MetabolismMolecule rows.

    Args:
        client: Platform API client.
        ligand_ids: Platform ligand ids to check.

    Returns:
        Ids that appear on at least one ``metabolismmolecule`` row.
    """

    found: set[str] = set()
    unique_ids = _unique_preserve_order(ligand_ids)
    if not unique_ids:
        return found

    id_set = set(unique_ids)
    for row in _rows_for_ligand_ids(
        client,
        ligand_ids=unique_ids,
        result_type=_RESULT_TYPE_MOLECULES,
    ):
        ligand_id = row.get("ligand_id")
        if isinstance(ligand_id, str) and ligand_id in id_set:
            found.add(ligand_id)
    return found


def _smiles_by_ligand_id(ligands: list[Ligand]) -> dict[str, str]:
    """Map platform ligand id → Caller SMILES from *ligands*.

    When multiple ligands share an id, the first non-empty SMILES wins.

    Args:
        ligands: Ligands that may carry platform ids and SMILES.

    Returns:
        Mapping of stripped ligand id to SMILES string.
    """

    out: dict[str, str] = {}
    for lig in ligands:
        raw_id = lig.id
        if raw_id is None:
            continue
        ligand_id = str(raw_id).strip()
        if not ligand_id or ligand_id in out:
            continue
        smiles = lig.smiles
        if isinstance(smiles, str) and smiles:
            out[ligand_id] = smiles
    return out


def _backfill_smiles_from_ligands(
    rows: list[dict[str, Any]],
    *,
    ligands: list[Ligand],
) -> list[dict[str, Any]]:
    """Fill missing ``smiles`` on result rows from input ligands by ``ligand_id``.

    Indexed MQ rows omit Caller SMILES; HTTP ``jobOutputs`` keep them. Fetch
    APIs restore SMILES from the caller's ligand objects when the index row
    has no SMILES.

    Args:
        rows: Result-explorer or similar row dicts (not mutated).
        ligands: Ligands passed to ``fetch_*``.

    Returns:
        New list of row dicts with ``smiles`` filled when possible.
    """

    smiles_by_id = _smiles_by_ligand_id(ligands)
    if not smiles_by_id:
        return list(rows)

    filled: list[dict[str, Any]] = []
    for row in rows:
        ligand_id = row.get("ligand_id")
        existing = row.get("smiles")
        has_smiles = isinstance(existing, str) and bool(existing)
        if (
            has_smiles
            or not isinstance(ligand_id, str)
            or ligand_id not in smiles_by_id
        ):
            filled.append(row)
            continue
        filled.append({**row, "smiles": smiles_by_id[ligand_id]})
    return filled


def _fetch_dataframe_for_ligands(
    *,
    ligands: Ligand | list[Ligand] | LigandSet,
    client: DeepOriginClient | None,
    result_type: str,
    columns: tuple[str, ...],
) -> pd.DataFrame:
    """Query indexed Metabolism rows for *ligands* and return a DataFrame.

    Missing ``smiles`` values are filled from the input ligands by matching
    ``ligand_id`` (MQ-indexed rows omit Caller SMILES).

    Args:
        ligands: Ligands whose platform ids are queried.
        client: Optional API client.
        result_type: ``metabolismsite`` or ``metabolismmolecule``.
        columns: Preferred column order.

    Returns:
        DataFrame of matching rows (possibly empty / partial).
    """

    resolved = _resolve_client(client)
    ligand_list = _normalize_ligands(ligands)
    rows = _rows_for_ligand_ids(
        resolved,
        ligand_ids=_platform_ligand_ids(ligand_list),
        result_type=result_type,
    )
    rows = _backfill_smiles_from_ligands(rows, ligands=ligand_list)
    return _ordered_dataframe(rows, columns=columns).reset_index(drop=True)


class Metabolism(
    Execution,
    SyncExecutableMixin,
    AsyncExecutableMixin,
    NotebookWatchMixin,
):
    """Predict sites of metabolism for ligands via ``deeporigin.metabolism``.

    The tool scores every cytochrome P450 isoform it supports. Ligands are
    **not** mutated (contrast with
    :class:`~deeporigin.drug_discovery.molprops.Molprops`).

    Use :meth:`run` for fewer than
    :data:`~deeporigin.utils.constants.METABOLISM_WORKFLOW_LIGAND_THRESHOLD`
    ligands (blocking). For larger batches, call :meth:`start`, then
    :meth:`wait` or :meth:`watch`, then :meth:`get_results` /
    :meth:`get_molecules` (data platform first, ``jobOutputs`` fallback).

    Use :meth:`fetch_results` / :meth:`fetch_molecules` to read indexed rows
    for a ligand set without starting a job.

    Attributes:
        ligands: Ligands whose SMILES are sent to the tool.
        name: Execution label, set from the ligand count unless overridden.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["metabolism"]["tool_key"]
    tool_version: str = TOOL_KEYS_AND_VERSIONS["metabolism"]["tool_version"]

    @beartype
    def __init__(
        self,
        *,
        ligands: Ligand | list[Ligand] | LigandSet,
        client: DeepOriginClient | None = None,
        name: str | None = None,
    ) -> None:
        """Configure a site-of-metabolism run for one or more ligands.

        Does not pin ``tool_version``; it stays ``"latest"``.

        Args:
            ligands: A ligand, a list of ligands, or a :class:`LigandSet`.
            client: Optional API client. Uses the default if not provided.
            name: Optional execution label. When omitted, set from the ligand
                count (e.g. ``Site of Metabolism for 5 ligands``).

        Raises:
            ValueError: If no ligands are provided.
        """
        super().__init__(client=client)
        self._ligands: list[Ligand] = _normalize_ligands(ligands)
        self.name = (
            name if name is not None else _metabolism_default_name(len(self._ligands))
        )

    @property
    def ligands(self) -> list[Ligand]:
        """Ligands targeted by this run (read-only)."""
        return self._ligands

    @classmethod
    @beartype
    def fetch_results(
        cls,
        ligands: Ligand | list[Ligand] | LigandSet,
        *,
        client: DeepOriginClient | None = None,
    ) -> pd.DataFrame:
        """Load indexed Metabolism site rows for *ligands* (any past jobs).

        Queries the data platform by platform ``ligand_id``. Does not start an
        execution. Ligands without an id contribute no filter keys; missing
        indexed rows are omitted (partial or empty tables are OK). Missing
        ``smiles`` on indexed rows is filled from *ligands* by ``ligand_id``.

        Args:
            ligands: A ligand, list, or :class:`LigandSet`.
            client: Optional API client. Uses the default if not provided.

        Returns:
            DataFrame with preferred columns ``ligand_id``, ``smiles``,
            ``atom_index``, ``enzyme``, and ``confidence``.
        """
        return _fetch_dataframe_for_ligands(
            ligands=ligands,
            client=client,
            result_type=_RESULT_TYPE_SITES,
            columns=_SITE_COLUMNS,
        )

    @classmethod
    @beartype
    def fetch_molecules(
        cls,
        ligands: Ligand | list[Ligand] | LigandSet,
        *,
        client: DeepOriginClient | None = None,
    ) -> pd.DataFrame:
        """Load indexed Metabolism molecule rows for *ligands* (any past jobs).

        Queries the data platform by platform ``ligand_id``. Does not start an
        execution. Partial or empty tables are OK when some ligands lack an id
        or have no indexed ``MetabolismMolecule``. Missing ``smiles`` on
        indexed rows is filled from *ligands* by ``ligand_id``.

        Args:
            ligands: A ligand, list, or :class:`LigandSet`.
            client: Optional API client. Uses the default if not provided.

        Returns:
            DataFrame with preferred columns ``ligand_id``, ``smiles``, and
            ``confidence_tier``.
        """
        return _fetch_dataframe_for_ligands(
            ligands=ligands,
            client=client,
            result_type=_RESULT_TYPE_MOLECULES,
            columns=_MOLECULE_COLUMNS,
        )

    def _make_inputs(self) -> dict[str, Any]:
        """Build tool ``inputs`` matching the metabolism schema."""
        ligand_payloads: list[dict[str, str]] = []
        for idx, lig in enumerate(self._ligands):
            smiles = lig.smiles or ""
            if not smiles:
                raise ValueError(f"ligands[{idx}] has no SMILES.")
            payload: dict[str, str] = {"smiles": smiles}
            if lig.id is not None:
                payload["id"] = str(lig.id)
            ligand_payloads.append(payload)
        return {"ligands": ligand_payloads}

    def _make_payload(
        self,
        *,
        approve_amount: int | None,
        sync: bool,
    ) -> dict[str, Any]:
        """Build the body dict for ``client.executions.create``.

        Args:
            approve_amount: Must be ``None``; Metabolism has no quote/billing
                path (see :meth:`_start_impl`).
            sync: ``True`` for blocking :meth:`run`; ``False`` for :meth:`start`.

        Raises:
            ValueError: If ``approve_amount`` is not ``None``.
        """
        if approve_amount is not None:
            raise ValueError(
                "Metabolism has no quote/approve_amount support; "
                "call run() or start() without quote=True or approve_amount."
            )
        payload: dict[str, Any] = {
            "inputs": self._make_inputs(),
            "outputs": {},
            "metadata": {},
            "sync": sync,
        }
        if self.name is not None:
            payload["name"] = self.name
        return payload

    def _create_execution(
        self,
        *,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Submit ``data`` with the extended Metabolism POST timeout."""
        resolved_key = self.tool_key
        resolved_version = getattr(self, "tool_version", None)
        if not resolved_key or not resolved_version:
            raise ValueError(
                "tool_key and tool_version are required for execution create"
            )
        return self.client.executions.create(  # ty:ignore[unresolved-attribute]
            tool_key=resolved_key,
            tool_version=resolved_version,
            data=data,
            timeout=METABOLISM_EXECUTION_TIMEOUT_SECONDS,
        )

    def _ensure_run_ligand_count(self) -> None:
        """Raise if :meth:`run` is used with a workflow-scale batch.

        Raises:
            ValueError: If there are
                :data:`~deeporigin.utils.constants.METABOLISM_WORKFLOW_LIGAND_THRESHOLD`
                or more ligands.
        """
        n = len(self._ligands)
        if n >= METABOLISM_WORKFLOW_LIGAND_THRESHOLD:
            raise ValueError(
                f"run() supports fewer than "
                f"{METABOLISM_WORKFLOW_LIGAND_THRESHOLD} ligands "
                f"(got {n}). Use start() then wait() or watch()."
            )

    def _preflight_already_scored(self, *, sync: bool) -> None:
        """Refuse or warn based on indexed MetabolismMolecule coverage.

        Refuses when every ligand has a platform id and every id already has
        a Metabolism molecule. When the job still proceeds and at least one
        id is already indexed, emits a :class:`UserWarning`.

        Args:
            sync: ``True`` when called from :meth:`run` (path-aware warn copy).

        Raises:
            DeepOriginException: If nothing remains to compute.
        """
        ligand_ids = _platform_ligand_ids(self._ligands)
        all_have_ids = len(ligand_ids) == len(self._ligands)
        if not ligand_ids:
            return

        scored = _ligand_ids_with_metabolism_molecule(
            self.client,  # ty:ignore[invalid-argument-type]
            ligand_ids=ligand_ids,
        )
        if all_have_ids and all(ligand_id in scored for ligand_id in ligand_ids):
            n = len(self._ligands)
            raise DeepOriginException(
                title="Metabolism already scored",
                message=(
                    f"All {n} ligands already have MetabolismMolecule values; "
                    "nothing to compute. Use Metabolism.fetch_results(...) and "
                    "Metabolism.fetch_molecules(...) to load indexed rows."
                ),
                fix=(
                    "Call Metabolism.fetch_results(ligands=...) / "
                    "fetch_molecules(ligands=...) instead of run() or start()."
                ),
            )

        scored_count = sum(1 for ligand_id in ligand_ids if ligand_id in scored)
        if scored_count == 0:
            return

        total = len(self._ligands)
        if sync:
            detail = (
                "The sync path may recompute those ligands. "
                "Use Metabolism.fetch_results / fetch_molecules to read "
                "existing rows without starting a job."
            )
        else:
            detail = (
                "The workflow may skip already-indexed ligands. "
                "Use Metabolism.fetch_results / fetch_molecules for the full "
                "set; instance get_results / get_molecules only return this "
                "job's new rows."
            )
        warnings.warn(
            (
                f"{scored_count} of {total} ligands already have indexed "
                f"MetabolismMolecule results. {detail}"
            ),
            UserWarning,
            stacklevel=3,
        )

    @beartype
    def run(self) -> pd.DataFrame:
        """Execute metabolism synchronously and return site rows.

        Blocks until the job finishes. Requires fewer than
        :data:`~deeporigin.utils.constants.METABOLISM_WORKFLOW_LIGAND_THRESHOLD`
        ligands; use :meth:`start` for larger batches. There is no
        ``quote=True`` path. The sites table includes every enzyme the tool
        scored.

        Refuses before create when every ligand has a platform id and every
        id already has a Metabolism molecule (use :meth:`fetch_results`
        instead).

        Returns:
            A :class:`pandas.DataFrame` of Metabolism site rows.

        Raises:
            DeepOriginException: If all ligands are already scored, the
                execution did not complete successfully, or no site rows
                could be parsed.
            ValueError: If there are 30 or more ligands.
        """
        self._ensure_run_ligand_count()
        self._preflight_already_scored(sync=True)
        dto = self._create_execution(
            data=self._make_payload(approve_amount=None, sync=True)
        )
        self.update_from_dto(dto)

        if not is_success_status(self.status):
            raise DeepOriginException(
                title="Metabolism prediction did not complete",
                message=(
                    f"Metabolism execution ended in {self.status!r} state "
                    f"(execution id {self.id!r})."
                ),
            )

        return self.get_results(dto)

    def _start_impl(self, *, approve_amount: int | None = None, **kwargs: Any) -> None:
        """Submit metabolism as a persisted async execution (``sync=False``).

        Sets :attr:`id`, :attr:`status`, and :attr:`_dto` from the platform
        response. Poll :meth:`sync`, block with :meth:`wait`, or use
        :meth:`watch` in Jupyter until the execution reaches a terminal state,
        then call :meth:`get_results`.

        Args:
            approve_amount: Must be ``None``; Metabolism has no quote/billing
                path. ``start(quote=True)`` or an explicit ``approve_amount``
                raises rather than silently running for real.
            **kwargs: Unused extra keyword arguments from the mixin.

        Raises:
            ValueError: If ``approve_amount`` is not ``None``.
            DeepOriginException: If every ligand is already scored.
        """
        del kwargs
        self._preflight_already_scored(sync=False)
        execution_dto = self._create_execution(
            data=self._make_payload(approve_amount=approve_amount, sync=False)
        )
        execution_id = execution_dto.get("executionId")
        if execution_id is None:
            raise ValueError("Execution response must contain 'executionId'") from None

        self._dto = execution_dto
        self._id = execution_id
        self.status = execution_dto.get("status")

    def _require_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        kind: str,
        key: str,
    ) -> None:
        """Raise if *rows* is empty.

        Args:
            rows: Parsed result-explorer or jobOutputs rows.
            kind: Human label for the error title (``sites`` or ``molecules``).
            key: Output key that was read (``sites`` or ``molecules``).

        Raises:
            DeepOriginException: If *rows* is empty.
        """
        if rows:
            return
        raise DeepOriginException(
            title=f"Metabolism {kind} missing",
            message=(
                f"Metabolism execution {self.id!r} returned no {key} rows "
                f"from the data platform or jobOutputs."
            ),
        )

    def _fetch_output_rows(
        self,
        *,
        result_type: str,
        job_outputs_key: str,
        dto: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Load sites/molecules from result-explorer, else ``jobOutputs``.

        Async workflow runs typically index rows only in the data platform.
        Sync HTTP runs usually return the same rows in ``jobOutputs``. Prefer
        result-explorer when this instance has an execution id; fall back to
        ``jobOutputs`` from *dto* or a fresh ``executions.get``.

        Args:
            result_type: Platform catalog base entity
                (``metabolismsite`` or ``metabolismmolecule``).
            job_outputs_key: ``sites`` or ``molecules``.
            dto: Optional execution payload for the jobOutputs fallback.

        Returns:
            Dict rows, or an empty list when neither source has data.

        Raises:
            ValueError: If :attr:`id` is unset and ``dto`` is omitted.
        """
        exec_id = getattr(self, "_id", None)

        if exec_id is not None:
            try:
                response = super().get_results(
                    result_type=result_type,
                    limit=None,
                    page_size=METABOLISM_RESULT_EXPLORER_PAGE_SIZE,
                )
                rows = _rows_from_result_explorer(response)
                if rows:
                    return rows
            except Exception:
                pass

        if dto is None:
            if exec_id is None:
                raise ValueError(
                    "Cannot get results: no execution has been started (id is None)."
                )
            dto = self.client.executions.get(  # ty:ignore[unresolved-attribute]
                exec_id
            )
        return _job_output_rows(dto, key=job_outputs_key)

    @beartype
    def get_results(self, dto: dict[str, Any] | None = None) -> pd.DataFrame:
        """Return this execution's Metabolism site rows as a DataFrame.

        Prefers data-platform result-explorer rows for this execution
        (``result_type=metabolismsite``), then falls back to
        ``jobOutputs.sites``. Includes every enzyme the tool scored.

        Args:
            dto: Optional execution payload from ``executions.create`` /
                ``executions.get`` used only for the jobOutputs fallback.

        Returns:
            DataFrame with ``ligand_id``, ``smiles``, ``atom_index``,
            ``enzyme``, and ``confidence``.

        Raises:
            ValueError: If :attr:`id` is unset and ``dto`` is omitted.
            DeepOriginException: If no site rows could be parsed.
        """
        rows = self._fetch_output_rows(
            result_type=_RESULT_TYPE_SITES,
            job_outputs_key="sites",
            dto=dto,
        )
        self._require_rows(rows, kind="sites", key="sites")
        return _ordered_dataframe(rows, columns=_SITE_COLUMNS).reset_index(drop=True)

    @beartype
    def get_molecules(self, dto: dict[str, Any] | None = None) -> pd.DataFrame:
        """Return molecule-level ``confidence_tier`` rows as a DataFrame.

        Prefers data-platform result-explorer rows for this execution
        (``result_type=metabolismmolecule``), then falls back to
        ``jobOutputs.molecules``. One row per scored SMILES.

        Args:
            dto: Optional execution payload from ``executions.create`` /
                ``executions.get`` used only for the jobOutputs fallback.

        Returns:
            DataFrame with ``ligand_id``, ``smiles``, and ``confidence_tier``.

        Raises:
            ValueError: If :attr:`id` is unset and ``dto`` is omitted.
            DeepOriginException: If no molecule rows could be parsed.
        """
        rows = self._fetch_output_rows(
            result_type=_RESULT_TYPE_MOLECULES,
            job_outputs_key="molecules",
            dto=dto,
        )
        self._require_rows(rows, kind="molecules", key="molecules")
        return _ordered_dataframe(rows, columns=_MOLECULE_COLUMNS)

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct a ``Metabolism`` from a tools execution DTO.

        Restores ligands from ``userInputs`` (falling back to ``inputs``).

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client. Uses the default if not provided.

        Returns:
            A :class:`Metabolism` with ``id``, lifecycle fields, and ligands set.

        Raises:
            ValueError: If stored inputs have no ligands.
        """
        instance = super().from_dto(dto, client=client)
        inputs: dict[str, Any] = dto.get("userInputs") or dto.get("inputs") or {}
        instance._ligands = _ligands_from_inputs(inputs)
        return instance
