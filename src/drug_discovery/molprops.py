"""Molprops -- synchronous ADMET / molprops runs on one or more ligands.

Each property is its own platform tool (``deeporigin.mol-props-<key>``); a
``Molprops`` instance orchestrates one ``client.executions.create`` per
selected property and merges the per-property ``jobOutputs`` rows by ligand id.

Usage::

    mp = Molprops(ligands=[ligand], props=["ames", "logp"])
    mp.quote()  # estimate ≈ N × quote for first ligand only
    mp.run()  # mutates ligands in place; sets ``cost`` on success

    # Optional: cap ligands per API request on ``run()`` (e.g. 10 at a time)
    Molprops(ligands=ligands, batch_size=10).run()
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
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

# Merged molprops rows are keyed by ligand id (toolbox molprops output schemas).
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


def _molprops_tool_key(prop: str) -> str:
    """Return the platform tool key for a single molprops property (e.g. ``logp``)."""
    prefix = TOOL_KEYS_AND_VERSIONS["mol_props"]["tool_key_prefix"]
    return f"{prefix}-{prop}"


def _execution_price_total(dto: dict) -> float | None:
    """Extract ``priceTotal`` from a tool execution DTO's ``quotationResult``."""
    quotation = dto.get("quotationResult") or {}
    successful = quotation.get("successfulQuotations") or []
    if not successful:
        return None
    price = successful[0].get("priceTotal")
    return float(price) if price is not None else None


def _execution_outputs_as_rows(dto: dict) -> list[dict]:
    """Return ``jobOutputs`` from an execution DTO as a list of row dicts."""
    jo = dto.get("jobOutputs")
    if jo is None:
        return []
    if isinstance(jo, dict):
        return [jo]
    if isinstance(jo, list):
        return [row for row in jo if isinstance(row, dict)]
    return []


def get_single_property(
    *,
    payload: dict,
    prop: str,
    client: DeepOriginClient,
    quote: bool = False,
) -> tuple[list[dict], dict]:
    """Run one molprops tool for ``prop`` and return ``(jobOutputs_rows, raw_dto)``."""

    body: dict[str, Any] = {
        "inputs": payload,
        "outputs": {},
        "metadata": {},
        "sync": True,
    }
    if quote:
        body["approveAmount"] = 0
        body["sync"] = False

    raw = client.executions.create(
        tool_key=_molprops_tool_key(prop),
        tool_version=TOOL_KEYS_AND_VERSIONS["mol_props"]["tool_version"],
        data=body,
    )
    return _execution_outputs_as_rows(raw), raw


def merge_dict_lists(dict_lists, key="ligand_id"):
    """Merge N lists of dicts by a common key (default ``ligand_id``)."""
    merged = defaultdict(dict)
    for lst in dict_lists:
        for d in lst:
            k = d[key]
            merged[k].update(d)
    if dict_lists:
        order = [d[key] for d in dict_lists[0]]
        seen = set()
        result = []
        for k in order + [k for k in merged if k not in order]:
            if k not in seen:
                result.append(deepcopy(merged[k]))
                seen.add(k)
        return result
    return []


def molprops_merged_with_raw_responses(
    ligand_set: LigandSet,
    properties: set[str] | None = None,
    *,
    client: DeepOriginClient,
) -> tuple[list[dict], list[dict]]:
    """Run molprops for each property, merge rows per ligand, and return raw DTOs."""
    if properties is None:
        properties_set: set[str] = set(MOLPROPS_DEFAULT_PROPERTIES)
    else:
        properties_set = set(properties)

    payload = {"ligands": ligand_set.to_dict()}
    outputs_per_prop: list[list[dict]] = []
    raw_responses: list[dict] = []

    for prop in sorted(properties_set):
        rows, raw = get_single_property(
            payload=payload,
            prop=prop,
            client=client,
            quote=False,
        )
        outputs_per_prop.append(rows)
        raw_responses.append(raw)

    merged = merge_dict_lists(outputs_per_prop, key=MOLPROPS_MERGE_KEY)
    return merged, raw_responses


def molprops_quote_total(
    ligand_set: LigandSet,
    properties: set[str],
    *,
    client: DeepOriginClient,
) -> float | None:
    """Quote molprops (one execution per property) and return the summed estimate.

    Returns ``None`` if any per-property quotation has no ``priceTotal``.
    """
    payload = {"ligands": ligand_set.to_dict()}
    total = 0.0
    for prop in sorted(properties):
        _rows, raw = get_single_property(
            payload=payload,
            prop=prop,
            client=client,
            quote=True,
        )
        price = _execution_price_total(raw)
        if price is None:
            return None
        total += price
    return total


class Molprops(Execution, QuoteMixin, SyncExecutableMixin):
    """Predict molprops / ADMET for ligands (composite of several platform tools).

    Orchestrates one ``client.executions.create`` per selected property key (e.g.
    ``logp``, ``logd``). ``run()`` mutates each passed-in
    :class:`~deeporigin.drug_discovery.structures.ligand.Ligand` in place via
    :meth:`~deeporigin.drug_discovery.structures.ligand.Ligand._apply_molprops_result`.

    This is a blocking flow. It does **not** assign a single platform execution
    ``id`` -- use :attr:`tool_keys` to see which tool keys are invoked.

    Attributes:
        ligands: Ligands to predict (same order as SMILES sent to the API).
        batch_size: Max ligands per ``run()`` API payload, or ``None`` for all at once.
    """

    tool_key: str = ""

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
        """Platform tool keys invoked for this configuration (one per property)."""
        return tuple(_molprops_tool_key(p) for p in sorted(self._properties))

    @property
    def batch_size(self) -> int | None:
        """Maximum ligands per :meth:`run` request, or ``None`` if all ligands per call."""

        return self._batch_size

    def quote(self) -> None:
        """Request a total cost estimate (linear in ligand count).

        Quotes the platform once per selected property using only the **first** ligand,
        then sets :attr:`~deeporigin.drug_discovery.execution.Execution.estimate` to that
        total multiplied by the number of ligands (``N``). This assumes per-ligand linear
        pricing.

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
        """Populate ``estimate`` from single-ligand quotes scaled by ligand count."""

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
        """Execute molprops, mutate ligands, and set :attr:`cost` when pricing is available.

        Total USD :attr:`cost` is the sum of per-property ``priceTotal`` values
        from each tool execution's ``quotationResult``.

        Ligands without a platform ``id`` are assigned ``"0"``, ``"1"``, … here so
        batched requests merge on stable ``ligand_id`` values.

        A ``tqdm`` bar is shown only when there is more than one API **batch**
        (i.e. ``batch_size`` splits the run). The bar advances by ligands
        completed and reports **ligands/s**, not batches/s. There is no progress
        bar for applying results to ligands.

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
                batch_merged, batch_raw = molprops_merged_with_raw_responses(
                    LigandSet(ligands=batch_ligands),
                    properties=self._properties,
                    client=self.client,
                )
                merged.extend(batch_merged)
                raw_responses.extend(batch_raw)
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

        for row, lig in zip(merged, self._ligands, strict=True):
            lig._apply_molprops_result(row)
        return self
