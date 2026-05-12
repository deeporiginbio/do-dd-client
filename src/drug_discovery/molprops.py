"""Molprops -- synchronous ADMET / molprops runs on one or more ligands.

Backed by the single combined platform tool ``deeporigin.mol-props-combined``,
which accepts a list of ``ligands`` and a ``molprops`` array selecting which
properties to compute, and returns one row per input ligand keyed by
``ligand_id``.

Usage::

    mp = Molprops(ligands=[ligand], props=["ames", "logp"])
    mp.quote()  # estimate ≈ N × quote for first ligand only
    mp.run()  # mutates ligands in place; sets ``cost`` on success

    # Optional: cap ligands per API request on ``run()`` (e.g. 10 at a time)
    Molprops(ligands=ligands, batch_size=10).run()
"""

from __future__ import annotations

from typing import Any

from beartype import beartype
from tqdm import tqdm

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import QuoteMixin, SyncExecutableMixin
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


def _execution_price_total(dto: dict) -> float | None:
    """Extract ``priceTotal`` from a tool execution DTO's ``quotationResult``."""
    quotation = dto.get("quotationResult") or {}
    successful = quotation.get("successfulQuotations") or []
    if not successful:
        return None
    price = successful[0].get("priceTotal")
    return float(price) if price is not None else None


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
    return _execution_price_total(raw)


class Molprops(Execution, QuoteMixin, SyncExecutableMixin):
    """Predict molprops / ADMET for ligands via the combined platform tool.

    Issues one ``client.executions.create`` per batch against
    ``deeporigin.mol-props-combined``, requesting all selected property keys
    (e.g. ``logp``, ``logd``) in a single call. ``run()`` mutates each
    passed-in :class:`~deeporigin.drug_discovery.structures.ligand.Ligand`
    in place via
    :meth:`~deeporigin.drug_discovery.structures.ligand.Ligand._apply_molprops_result`.

    This is a blocking flow. It does **not** assign a single platform execution
    ``id`` -- use :attr:`tool_key` to see which tool key is invoked.

    Attributes:
        ligands: Ligands to predict (same order as SMILES sent to the API).
        batch_size: Max ligands per ``run()`` API payload, or ``None`` for all at once.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["mol_props"]["tool_key"]

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
        self._quoted = False

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
    def tool_keys(self) -> tuple[str, ...]:
        """Platform tool key invoked for this run (single combined tool).

        Kept as a tuple for backwards-compatibility with callers that iterated
        per-property tool keys; the combined tool now occupies a single slot.
        """
        return (self.tool_key,)

    @property
    def batch_size(self) -> int | None:
        """Maximum ligands per :meth:`run` request, or ``None`` if all ligands per call."""

        return self._batch_size

    def quote(self) -> None:
        """Request a total cost estimate (linear in ligand count).

        Quotes the combined tool once using only the **first** ligand, then
        sets :attr:`~deeporigin.drug_discovery.execution.Execution.estimate`
        to that total multiplied by the number of ligands (``N``). This
        assumes per-ligand linear pricing.

        Raises:
            ValueError: If this instance was already quoted.
        """
        if self._quoted:
            raise ValueError(
                "Cannot quote: a quotation already exists for this Molprops instance."
            )
        if self.id is not None:
            raise ValueError(f"Cannot quote: execution already has id {self.id!r}.")
        self._populate_estimate_from_quote()
        self._quoted = True

    def _populate_estimate_from_quote(self) -> None:
        """Populate ``estimate`` from a single-ligand quote scaled by ligand count."""

        n_ligands = len(self._ligands)
        single = molprops_quote_total(
            LigandSet(ligands=[self._ligands[0]]),
            properties=self._properties,
            client=self.client,
        )
        if single is not None:
            self._estimate = single * n_ligands

    @beartype
    def run(self) -> Molprops:
        """Execute the combined molprops tool, mutate ligands, and set :attr:`cost`.

        Issues one ``client.executions.create`` per batch (controlled by
        :attr:`batch_size`). Total USD :attr:`cost` is the sum of
        ``priceTotal`` values from each batch's ``quotationResult``.

        Ligands without a platform ``id`` are assigned ``"0"``, ``"1"``, … here so
        batched requests merge on stable ``ligand_id`` values.

        A ``tqdm`` bar is shown only when there is more than one API **batch**
        (i.e. ``batch_size`` splits the run). The bar advances by ligands
        completed and reports **ligands/s**, not batches/s.

        Returns:
            ``self`` for chaining.
        """
        for idx, lig in enumerate(self._ligands):
            if lig.id is None:
                lig.id = str(idx)
        ligand_set = LigandSet(ligands=self._ligands)
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

        total_cost = 0.0
        any_priced = False
        for raw in raw_responses:
            price = _execution_price_total(raw)
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
