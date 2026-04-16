"""Molprops -- synchronous ADMET / molprops runs on one or more ligands.

Usage::

    mp = Molprops(ligands=[ligand], props=["ames", "logp"])
    mp.quote()  # estimate ≈ N × quote for first ligand only
    mp.run()  # mutates ligands in place; sets ``cost`` on success

    # Optional: cap ligands per API request on ``run()`` (e.g. 10 at a time)
    Molprops(ligands=ligands, batch_size=10).run()
"""

from __future__ import annotations

from beartype import beartype
from tqdm import tqdm

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import QuoteMixin, SyncExecutableMixin
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.functions.molprops import (
    molprops_merged_with_raw_responses,
    molprops_quote,
)
from deeporigin.functions.result import FunctionResult
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import (
    MOLPROPS_DEFAULT_PROPERTIES,
    MOLPROPS_PROPERTY_KEYS,
)


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


class Molprops(Execution, QuoteMixin, SyncExecutableMixin):
    """Predict molprops / ADMET for ligands (composite of several platform functions).

    Orchestrates one ``functions.run`` per selected property key (e.g. logp, logd).
    ``run()`` mutates each passed-in :class:`~deeporigin.drug_discovery.structures.ligand.Ligand`
    in place via :meth:`~deeporigin.drug_discovery.structures.ligand.Ligand._apply_molprops_result`.

    This is a blocking flow. It does **not** assign a single platform execution ``id`` —
    use :attr:`tool_keys` to see which function keys are invoked.

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
        """Configure a molprops run for one or more ligands.

        Args:
            ligands: A :class:`LigandSet` or list of :class:`Ligand` instances.
            props: Molprops keys to run (e.g. ``["ames", "logp"]``). Duplicate names
                are ignored. Mutually exclusive with ``properties``.
            properties: Same as ``props`` but as a set; prefer ``props`` for new code.
                ``None`` for both ``props`` and ``properties`` means the full default bundle
                (:data:`~deeporigin.utils.constants.MOLPROPS_DEFAULT_PROPERTIES`).
            batch_size: For :meth:`run`, cap how many molecules are sent per
                property request. ``None`` sends all ligands in one payload per property
                (legacy behavior). Does not affect :meth:`quote` (see below).
            client: Optional API client.

        Raises:
            ValueError: If ``ligands`` is empty, both ``props`` and ``properties`` are
                passed, an unknown molprops key is given, or ``batch_size`` is not
                positive when set.
        """
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
        """Platform function keys invoked for this configuration (one per property)."""
        return tuple(
            f"{TOOL_KEYS_AND_VERSIONS['mol_props']['function_key_prefix']}-{p}"
            for p in sorted(self._properties)
        )

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
        result = molprops_quote(
            LigandSet(ligands=[self._ligands[0]]),
            properties=self._properties,
            client=self.client,
        )
        if result.estimate is not None:
            self._estimate = result.estimate * n_ligands

    @beartype
    def run(self) -> Molprops:
        """Execute molprops, mutate ligands, and set :attr:`cost` when pricing is available.

        Total USD :attr:`cost` is the sum of per-property completed runs (see
        :class:`~deeporigin.functions.result.FunctionResult`).

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
        fr = FunctionResult(raw_responses)
        if fr.cost is not None:
            self._cost = fr.cost

        for row, lig in zip(merged, self._ligands, strict=True):
            lig._apply_molprops_result(row)
        return self
