"""Metabolism -- predict sites of metabolism for ligands (sync-only).

Backed by the platform tool ``deeporigin.metabolism``. One :class:`Metabolism`
instance is configured with ligands, then executed with a blocking
:meth:`run`, which returns a :class:`pandas.DataFrame` of Metabolism site
rows (atom, enzyme, site confidence). :meth:`get_molecules` returns
molecule-level ``confidence_tier`` rows.

The tool scores every cytochrome P450 isoform it supports; the client does
not select or filter enzymes. ``tool_version`` stays ``"latest"``. Ligands
are not mutated. Payload ``id`` is sent only when
:attr:`~deeporigin.drug_discovery.structures.ligand.Ligand.id` is already set.

Usage::

    from deeporigin.drug_discovery import Metabolism, Ligand

    job = Metabolism(ligands=Ligand.from_smiles("CCO"))
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

    The tool scores every cytochrome P450 isoform it supports. Ligands are
    **not** mutated (contrast with
    :class:`~deeporigin.drug_discovery.molprops.Molprops`).

    Attributes:
        ligands: Ligands whose SMILES are sent to the tool.
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

        Does not pin ``tool_version``; it stays ``"latest"``.

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

        Blocks until the job finishes. There is no ``quote=True`` path. The
        sites table includes every enzyme the tool scored.

        Returns:
            A :class:`pandas.DataFrame` of Metabolism site rows.

        Raises:
            DeepOriginException: If the execution did not complete successfully
                or no site rows could be parsed.
            ValueError: If there are more than 250 ligands.
        """
        _ensure_ligand_cap(self._ligands)
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
