"""Metabolism -- predict sites of metabolism for ligands (sync-only).

Backed by the platform tool ``deeporigin.metabolism``. One :class:`Metabolism`
instance is configured with ligands, then executed with a blocking
:meth:`run`, which returns a :class:`pandas.DataFrame` of Metabolism site
rows (atom, enzyme, site confidence). :meth:`get_molecules` returns
molecule-level ``confidence_tier`` rows.

Construction copies the nine cytochrome P450 (CYP) isoform names into
:attr:`enzymes`. Trim that list before :meth:`run` to filter the sites table.
The tool still scores all nine; trimming is client-side. ``tool_version``
stays ``"latest"``. Ligands are not mutated. Payload ``id`` is sent only when
:attr:`~deeporigin.drug_discovery.structures.ligand.Ligand.id` is already set.

Usage::

    from deeporigin.drug_discovery import Metabolism, Ligand

    job = Metabolism(ligands=Ligand.from_smiles("CCO"))
    job.enzymes = ["CYP3A4", "CYP2D6"]
    sites = job.run()
    mols = job.get_molecules()
"""

from __future__ import annotations

from typing import Any, Self

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import SyncExecutableMixin
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status
from deeporigin.utils.constants import (
    METABOLISM_ENZYMES,
    METABOLISM_EXECUTION_TIMEOUT_SECONDS,
    METABOLISM_LIGAND_CAP,
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
_ALLOWED_ENZYMES: frozenset[str] = frozenset(METABOLISM_ENZYMES)


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


def _ensure_ligand_cap(ligands: list[Ligand]) -> None:
    """Raise if *ligands* exceeds :data:`METABOLISM_LIGAND_CAP`.

    Args:
        ligands: Ligands about to be submitted.

    Raises:
        ValueError: If there are more than 250 ligands.
    """

    n = len(ligands)
    if n > METABOLISM_LIGAND_CAP:
        raise ValueError(
            f"Metabolism accepts at most {METABOLISM_LIGAND_CAP} ligands (got {n})."
        )


def _validate_metabolism_enzymes(
    enzymes: list[str] | tuple[str, ...],
    *,
    allowed: frozenset[str],
) -> list[str]:
    """Return a copy of *enzymes* or raise if the selection is invalid.

    Args:
        enzymes: Isoform names to keep in the sites table.
        allowed: Allowlist (the nine CYP names).

    Returns:
        A new list of enzyme names in caller order.

    Raises:
        ValueError: If empty, duplicated, or not in *allowed*.
    """

    if not enzymes:
        raise ValueError("enzymes must be non-empty.")
    if len(enzymes) != len(set(enzymes)):
        raise ValueError("enzymes must not contain duplicates.")
    unknown = set(enzymes) - allowed
    if unknown:
        raise ValueError(
            f"Unknown enzymes {sorted(unknown)}. Allowed: {sorted(allowed)}"
        )
    return list(enzymes)


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


class Metabolism(Execution, SyncExecutableMixin):
    """Predict sites of metabolism for ligands via ``deeporigin.metabolism``.

    Construction fills :attr:`enzymes` with the nine CYP isoform names.
    Trim or replace that list before :meth:`run`. Ligands are **not** mutated
    (contrast with :class:`~deeporigin.drug_discovery.molprops.Molprops`).

    Attributes:
        ligands: Ligands whose SMILES are sent to the tool.
        enzymes: CYP isoform names used to filter the sites table. A list on a
            draft instance (no execution ``id``); a tuple after ``id`` is set;
            ``None`` on a past execution rehydrated from the platform.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["metabolism"]["tool_key"]
    tool_version: str = TOOL_KEYS_AND_VERSIONS["metabolism"]["tool_version"]

    @beartype
    def __init__(
        self,
        *,
        ligands: Ligand | list[Ligand] | LigandSet,
        client: DeepOriginClient | None = None,
    ) -> None:
        """Configure a site-of-metabolism run for one or more ligands.

        Fills :attr:`enzymes` with the nine CYP names. Does not take
        ``enzymes=`` — inspect and trim ``enzymes`` after construct. Does not
        pin ``tool_version``; it stays ``"latest"``.

        Args:
            ligands: A ligand, a list of ligands, or a :class:`LigandSet`.
            client: Optional API client. Uses the default if not provided.

        Raises:
            ValueError: If no ligands are provided, or if there are more than
                250 ligands.
        """
        super().__init__(client=client)
        self._ligands: list[Ligand] = _normalize_ligands(ligands)
        _ensure_ligand_cap(self._ligands)
        self._enzymes: list[str] | tuple[str, ...] | None = list(METABOLISM_ENZYMES)

    @property
    def ligands(self) -> list[Ligand]:
        """Ligands targeted by this run (read-only)."""
        return self._ligands

    @property
    def enzymes(self) -> list[str] | tuple[str, ...] | None:
        """CYP isoform names used to filter the sites table.

        A mutable list on a draft instance. After an execution ``id`` is set,
        a tuple. ``None`` when a past execution is rehydrated (no trim was
        stored on the tool).
        """
        return self._enzymes

    @enzymes.setter
    def enzymes(self, value: list[str]) -> None:
        """Replace the draft enzyme list with a non-empty unique subset."""
        if getattr(self, "_id", None) is not None:
            raise AttributeError(
                "cannot assign to 'enzymes': execution id is already set"
            )
        self._enzymes = _validate_metabolism_enzymes(value, allowed=_ALLOWED_ENZYMES)

    def update_from_dto(self, dto: dict[str, Any]) -> None:
        """Apply execution fields from ``dto`` and freeze ``enzymes``."""
        super().update_from_dto(dto)
        enzymes = getattr(self, "_enzymes", None)
        if self._id is not None and isinstance(enzymes, list):
            self._enzymes = tuple(enzymes)

    def duplicate(self, *, client: DeepOriginClient | None = None) -> Self:
        """Copy configuration into a new draft with writable ``enzymes``.

        ``from_dto`` leaves ``enzymes`` as ``None`` (the tool never recorded a
        trim). Fill the nine names here so the draft can assign ``enzymes``
        like a constructor-built instance.

        Args:
            client: Optional API client for the new instance.

        Returns:
            A draft :class:`Metabolism` with no execution id.
        """
        new = super().duplicate(client=client)
        if isinstance(getattr(new, "_enzymes", None), tuple):
            new._enzymes = list(new._enzymes)
        if new._enzymes is None:
            new._enzymes = list(METABOLISM_ENZYMES)
        return new

    def _ensure_enzymes_for_run(self) -> None:
        """Validate in-place edits before submitting the execution.

        Preserves the tuple/list invariant: a re-run on an already-executed
        instance (``enzymes`` already frozen to a tuple) must not leave a
        mutable list on ``self._enzymes`` if ``_create_execution`` raises
        before :meth:`update_from_dto` re-freezes it.
        """
        if self._enzymes is None:
            return
        was_frozen = isinstance(self._enzymes, tuple)
        validated = _validate_metabolism_enzymes(
            list(self._enzymes),
            allowed=_ALLOWED_ENZYMES,
        )
        self._enzymes = tuple(validated) if was_frozen else validated

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

    def _make_payload(self) -> dict[str, Any]:
        """Build the body dict for ``client.executions.create``."""
        return {
            "inputs": self._make_inputs(),
            "outputs": {},
            "metadata": {},
            "sync": True,
        }

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

    @beartype
    def run(self) -> pd.DataFrame:
        """Execute metabolism synchronously and return site rows.

        Blocks until the job finishes. There is no ``quote=True`` path.

        Returns:
            A :class:`pandas.DataFrame` of Metabolism site rows, filtered to
            :attr:`enzymes` when that list is set.

        Raises:
            DeepOriginException: If the execution did not complete successfully
                or no site rows could be parsed.
            ValueError: If ``enzymes`` is empty, has duplicates, or names
                isoforms outside the nine CYP names, or if there are
                more than 250 ligands.
        """
        _ensure_ligand_cap(self._ligands)
        self._ensure_enzymes_for_run()
        dto = self._create_execution(data=self._make_payload())
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

        When :attr:`enzymes` is set, only those isoform rows are kept. When
        it is ``None`` (rehydrated jobs), every site row is returned.

        Args:
            dto: Optional execution payload from ``executions.create`` /
                ``executions.get``.

        Returns:
            DataFrame with ``ligand_id``, ``smiles``, ``atom_index``,
            ``enzyme``, and ``confidence``.

        Raises:
            ValueError: If :attr:`id` is unset and ``dto`` is omitted.
            DeepOriginException: If no site rows could be parsed, or the
                enzyme filter left no rows.
        """
        if dto is None:
            exec_id = self._ensure_id()
            dto = self.client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]

        rows = _job_output_rows(dto, key="sites")
        self._require_rows(rows, kind="sites", key="sites")
        df = _ordered_dataframe(rows, columns=_SITE_COLUMNS)
        if self._enzymes is not None:
            if "enzyme" not in df.columns:
                self._require_rows([], kind="sites", key="sites")
            df = df[df["enzyme"].isin(list(self._enzymes))]
            if df.empty:
                raise DeepOriginException(
                    title="Metabolism sites missing",
                    message=(
                        f"Metabolism execution {self.id!r} had no site rows "
                        f"for enzymes {list(self._enzymes)!r}."
                    ),
                )
        return df.reset_index(drop=True)

    @beartype
    def get_molecules(self, dto: dict[str, Any] | None = None) -> pd.DataFrame:
        """Return molecule-level ``confidence_tier`` rows as a DataFrame.

        Not filtered by :attr:`enzymes`. One row per scored SMILES.

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
        ``enzymes`` stays ``None`` — the tool never recorded a trim, so
        :meth:`get_results` returns every site row.

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
        instance._enzymes = None
        return instance
