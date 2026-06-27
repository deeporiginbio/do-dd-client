"""Molprops -- synchronous ADMET / molprops runs on one or more ligands.

Backed by the single combined platform tool ``deeporigin.mol-props-combined``,
which accepts a list of ``ligands`` and a ``molprops`` array selecting which
properties to compute, and returns one row per input ligand keyed by
``ligand_id``.

Usage::

    mp = Molprops(ligands=[ligand], props=["ames", "logp"])
    mp.run(quote=True)  # one quote for all ligands + props (ignores ``batch_size``)
    mp.run()  # mutates ligands in place; sets ``cost`` on success

    # Optional: cap ligands per API request on ``run()`` (e.g. 10 at a time)
    Molprops(ligands=ligands, batch_size=10).run()
"""

from __future__ import annotations

from typing import Any

from beartype import beartype
from tqdm import tqdm

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import SyncExecutableMixin
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import (
    MOLPROPS_DEFAULT_PROPERTIES,
    MOLPROPS_PROPERTY_KEYS,
)

# Merged molprops rows are keyed by ligand id (combined molprops output schema).
MOLPROPS_MERGE_KEY = "ligand_id"


def _validate_molprops_properties(properties: set[str] | None) -> set[str]:
    """Return the resolved property set or raise if any key is unknown."""

    if properties is None:
        return set(MOLPROPS_DEFAULT_PROPERTIES)
    if not properties:
        raise ValueError("properties must be non-empty when provided.")
    unknown = properties - MOLPROPS_PROPERTY_KEYS
    if unknown:
        raise ValueError(
            f"Unknown molprops properties {sorted(unknown)}. "
            f"Allowed: {sorted(MOLPROPS_PROPERTY_KEYS)}"
        )
    return properties


def _resolve_molprops_props(
    *,
    props: list[str] | None,
    properties: set[str] | None,
) -> set[str]:
    """Resolve ``props`` / ``properties`` into a validated set (mutually exclusive)."""

    if props is not None and properties is not None:
        raise ValueError("Pass only one of props or properties, not both.")
    if props is not None:
        if not props:
            raise ValueError("props must be non-empty when provided.")
        return _validate_molprops_properties(set(props))
    return _validate_molprops_properties(properties)


def _execution_outputs_as_rows(dto: dict) -> list[dict]:
    """Return per-ligand molprops rows from a combined-tool execution DTO.

    The combined tool's output schema wraps rows under a ``molprops`` key
    (``{"molprops": [...]}``), but some response pipelines flatten the array
    to the top of ``jobOutputs``. Both shapes are accepted.
    """
    jo = dto.get("jobOutputs")
    if isinstance(jo, dict):
        molprops = jo.get("molprops")
        if isinstance(molprops, list):
            return [row for row in molprops if isinstance(row, dict)]
        return [jo]
    if isinstance(jo, list):
        return [row for row in jo if isinstance(row, dict)]
    return []


def _molprops_payload(*, ligand_set: LigandSet, properties: set[str]) -> dict[str, Any]:
    """Build the ``inputs`` dict for ``deeporigin.mol-props-combined``."""
    return {
        "ligands": ligand_set.to_dict(),
        "molprops": sorted(properties),
    }


def run_molprops_combined(
    *,
    ligand_set: LigandSet,
    properties: set[str],
    client: DeepOriginClient,
    quote: bool = False,
) -> tuple[list[dict], dict]:
    """Issue one combined-tool execution and return ``(rows, raw_dto)``.

    When ``quote`` is true, the call requests a cost estimate without
    executing (``approveAmount=0``, ``sync=False``) and ``rows`` is empty.
    """
    body: dict[str, Any] = {
        "inputs": _molprops_payload(ligand_set=ligand_set, properties=properties),
        "outputs": {},
        "metadata": {},
        "sync": True,
    }
    if quote:
        body["approveAmount"] = 0
        body["sync"] = False

    raw = client.executions.create(  # ty:ignore[unresolved-attribute]
        tool_key=TOOL_KEYS_AND_VERSIONS["mol_props"]["tool_key"],
        tool_version=TOOL_KEYS_AND_VERSIONS["mol_props"]["tool_version"],
        data=body,
    )
    rows = [] if quote else _execution_outputs_as_rows(raw)
    return rows, raw


def molprops_quote_total(
    ligand_set: LigandSet,
    properties: set[str],
    *,
    client: DeepOriginClient,
) -> float | None:
    """Quote the combined molprops tool and return the total estimate.

    Returns ``None`` if the quotation has no ``priceTotal``.
    """
    _rows, raw = run_molprops_combined(
        ligand_set=ligand_set,
        properties=properties,
        client=client,
        quote=True,
    )
    return Execution._quotation_total(raw)


class Molprops(Execution, SyncExecutableMixin):
    """Predict molprops / ADMET for ligands via the combined platform tool.

    Issues one ``client.executions.create`` per batch against
    ``deeporigin.mol-props-combined`` on a normal :meth:`run`, or a single
    quotation request for all ligands when :meth:`run` is called with
    ``quote=True``. Each request carries all selected property keys
    (e.g. ``logp``, ``logd``). A normal ``run()`` mutates each
    passed-in :class:`~deeporigin.drug_discovery.structures.ligand.Ligand`
    in place via
    :meth:`~deeporigin.drug_discovery.structures.ligand.Ligand._apply_molprops_result`.

    This is a blocking flow. :meth:`run` refreshes ``id``, ``status``, and related
    execution fields from the platform response via
    :meth:`~deeporigin.drug_discovery.execution.Execution.update_from_dto`
    (the last batch when :attr:`batch_size` splits the run).

    Attributes:
        ligands: Ligands to predict (same order as SMILES sent to the API).
        batch_size: Max ligands per ``run()`` API payload, or ``None`` for all at once.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["mol_props"]["tool_key"]
    tool_version: str = TOOL_KEYS_AND_VERSIONS["mol_props"]["tool_version"]

    @beartype
    def __init__(
        self,
        *,
        ligands: list[Ligand] | LigandSet,
        props: list[str] | None = None,
        properties: set[str] | None = None,
        batch_size: int | None = None,
        client: DeepOriginClient | None = None,
    ) -> None:
        """Configure a molprops run for one or more ligands."""
        super().__init__(client=client)
        if isinstance(ligands, LigandSet):
            self._ligands: list[Ligand] = list(ligands.ligands)
        else:
            self._ligands = list(ligands)
        if not self._ligands:
            raise ValueError("Molprops requires at least one ligand.")
        if batch_size is not None and batch_size <= 0:
            raise ValueError("batch_size must be a positive integer when set.")
        self._batch_size = batch_size
        self._properties = _resolve_molprops_props(props=props, properties=properties)

    @property
    def ligands(self) -> list[Ligand]:
        """Ligands targeted by this run (read-only)."""
        return self._ligands

    @property
    def properties(self) -> frozenset[str]:
        """Molprops property keys that will be requested (e.g. ``logp``, ``logd``)."""
        return frozenset(self._properties)

    @property
    def props(self) -> tuple[str, ...]:
        """Selected molprops keys in stable sorted order (same set as :attr:`properties`)."""
        return tuple(sorted(self._properties))

    @property
    def batch_size(self) -> int | None:
        """Maximum ligands per :meth:`run` request, or ``None`` if all ligands per call."""

        return self._batch_size

    @beartype
    def run(
        self,
        *,
        quote: bool = False,
    ) -> Molprops:
        """Execute the combined molprops tool, mutate ligands, and set :attr:`cost`.

        With ``quote=True``, sends **one** ``client.executions.create`` with every
        ligand and every selected property (``batch_size`` is ignored), requests a
        quotation only (``approveAmount=0``), and applies the response with
        :meth:`~deeporigin.drug_discovery.execution.Execution.update_from_dto`
        (``estimate``, ``id``, ``status``, etc.). Ligands are **not** updated with
        molprops outputs.

        Otherwise issues one ``client.executions.create`` per batch (controlled by
        :attr:`batch_size`). Total USD :attr:`cost` is the sum of ``priceTotal``
        values from each batch's ``quotationResult``.

        Ligands without a platform ``id`` are assigned ``"0"``, ``"1"``, … here so
        batched requests merge on stable ``ligand_id`` values.

        A ``tqdm`` bar is shown only when there is more than one API **batch**
        (i.e. ``batch_size`` splits the run). The bar advances by ligands
        completed and reports **ligands/s**, not batches/s.

        Args:
            quote: When ``True``, quote the full ligand set in a single request and
                skip batching and result application.

        Returns:
            ``self`` for chaining.
        """
        for idx, lig in enumerate(self._ligands):
            if lig.id is None:
                lig.id = str(idx)
        ligand_set = LigandSet(ligands=self._ligands)

        if quote:
            _unused_rows, raw = run_molprops_combined(
                ligand_set=ligand_set,
                properties=self._properties,
                client=self.client,
                quote=True,
            )
            self.update_from_dto(raw)
            return self

        merged: list[dict] = []
        raw_responses: list[dict] = []
        batches = ligand_set.batches(self._batch_size)
        n_ligands = len(self._ligands)
        use_batch_bar = len(batches) > 1
        with tqdm(
            total=n_ligands,
            desc="Molprops",
            unit="ligand",
            disable=not use_batch_bar,
        ) as pbar:
            for batch_ligands in batches:
                batch_rows, batch_raw = run_molprops_combined(
                    ligand_set=LigandSet(ligands=batch_ligands),
                    properties=self._properties,
                    client=self.client,
                )
                merged.extend(batch_rows)
                raw_responses.append(batch_raw)
                pbar.update(len(batch_ligands))

        if raw_responses:
            self.update_from_dto(raw_responses[-1])

        total_cost = 0.0
        any_priced = False
        for raw in raw_responses:
            price = Execution._quotation_total(raw)
            if price is not None:
                any_priced = True
                total_cost += price
        if any_priced and total_cost > 0:
            self._cost = total_cost

        rows_by_id: dict[str, dict] = {
            str(row[MOLPROPS_MERGE_KEY]): row
            for row in merged
            if isinstance(row, dict) and MOLPROPS_MERGE_KEY in row
        }
        for lig in self._ligands:
            row = rows_by_id.get(str(lig.id))
            if row is not None:
                lig._apply_molprops_result(row)
        return self
