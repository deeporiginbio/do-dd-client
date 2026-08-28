"""Metabolism -- predict sites of metabolism for ligands.

Backed by the platform tool ``deeporigin.metabolism``. One :class:`Metabolism`
instance is configured with ligands, then executed with a blocking
:meth:`run` (small batches) or asynchronous :meth:`start` (larger batches).
:meth:`run` returns a :class:`pandas.DataFrame` of Metabolism site rows
(atom, enzyme, site confidence). :meth:`get_molecules` returns
molecule-level ``confidence_tier`` rows.

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
"""

from __future__ import annotations

from typing import Any, Self

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
    return f"Site of Metabolism for {ligand_count} ligands"


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
    """

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
    :meth:`wait` or :meth:`watch`, then :meth:`get_results`.

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

    def _make_payload(self, *, sync: bool) -> dict[str, Any]:
        """Build the body dict for ``client.executions.create``.

        Args:
            sync: ``True`` for blocking :meth:`run`; ``False`` for :meth:`start`.
        """
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

    @beartype
    def run(self) -> pd.DataFrame:
        """Execute metabolism synchronously and return site rows.

        Blocks until the job finishes. Requires fewer than
        :data:`~deeporigin.utils.constants.METABOLISM_WORKFLOW_LIGAND_THRESHOLD`
        ligands; use :meth:`start` for larger batches. There is no
        ``quote=True`` path. The sites table includes every enzyme the tool
        scored.

        Returns:
            A :class:`pandas.DataFrame` of Metabolism site rows.

        Raises:
            DeepOriginException: If the execution did not complete successfully
                or no site rows could be parsed.
            ValueError: If there are 30 or more ligands.
        """
        self._ensure_run_ligand_count()
        dto = self._create_execution(data=self._make_payload(sync=True))
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
            approve_amount: Unused (Metabolism has no quote path). Accepted for
                mixin compatibility.
            **kwargs: Unused extra keyword arguments from the mixin.
        """
        del approve_amount, kwargs
        execution_dto = self._create_execution(data=self._make_payload(sync=False))
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
            rows: Parsed jobOutputs rows.
            kind: Human label for the error title (``sites`` or ``molecules``).
            key: jobOutputs key that was read.

        Raises:
            DeepOriginException: If *rows* is empty.
        """
        if rows:
            return
        raise DeepOriginException(
            title=f"Metabolism {kind} missing",
            message=(
                f"Metabolism execution {self.id!r} returned no {key} rows "
                f"in jobOutputs."
            ),
        )

    @beartype
    def get_results(self, dto: dict[str, Any] | None = None) -> pd.DataFrame:
        """Return this execution's Metabolism site rows as a DataFrame.

        Includes every enzyme the tool scored.

        Args:
            dto: Optional execution payload from ``executions.create`` /
                ``executions.get``.

        Returns:
            DataFrame with ``ligand_id``, ``smiles``, ``atom_index``,
            ``enzyme``, and ``confidence``.

        Raises:
            ValueError: If :attr:`id` is unset and ``dto`` is omitted.
            DeepOriginException: If no site rows could be parsed.
        """
        if dto is None:
            exec_id = self._ensure_id()
            dto = self.client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]

        rows = _job_output_rows(dto, key="sites")
        self._require_rows(rows, kind="sites", key="sites")
        return _ordered_dataframe(rows, columns=_SITE_COLUMNS).reset_index(drop=True)

    @beartype
    def get_molecules(self, dto: dict[str, Any] | None = None) -> pd.DataFrame:
        """Return molecule-level ``confidence_tier`` rows as a DataFrame.

        One row per scored SMILES.

        Args:
            dto: Optional execution payload from ``executions.create`` /
                ``executions.get``.

        Returns:
            DataFrame with ``ligand_id``, ``smiles``, and ``confidence_tier``.

        Raises:
            ValueError: If :attr:`id` is unset and ``dto`` is omitted.
            DeepOriginException: If no molecule rows could be parsed.
        """
        if dto is None:
            if self._dto is not None:
                dto = self._dto
            else:
                exec_id = self._ensure_id()
                dto = self.client.executions.get(  # ty:ignore[unresolved-attribute]
                    exec_id
                )

        rows = _job_output_rows(dto, key="molecules")
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
