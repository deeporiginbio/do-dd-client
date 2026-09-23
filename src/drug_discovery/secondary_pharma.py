"""SecondaryPharmacology -- score ligands against a baked kinase panel.

Backed by the platform tool ``deeporigin.secondary-pharma``, which supports two
mutually exclusive scoring methods selected at construction:

- ``"ligand-ml"`` -- served, synchronous XGBoost booster scoring. Use :meth:`run`.
- ``"docking"`` -- Argo workflow, asynchronous only. Use :meth:`start` (and
  :meth:`watch` in Jupyter).

The tool schema has no ``inputs.sync`` field (unlike ``deeporigin.docking``), so
``method`` alone determines execution modality -- there is no unified blocking/
non-blocking call across both paths. :meth:`get_results` always returns a
:class:`pandas.DataFrame` regardless of method (method-aware columns), but the
two paths load from different places: ``ligand-ml`` is served/sync, so results
come back in the same response's ``jobOutputs``; ``docking`` is an async Argo
workflow, so results are only ever persisted to result-explorer (``jobOutputs``
on a polled execution is empty) -- same reason ``Docking.get_results()`` tries
result-explorer before ``jobOutputs``. Use ``get_results()``'s ``pose_score``/
``binding_energy`` columns for docking results -- pose visualization isn't
available yet (DDOS-7481).

Usage::

    from deeporigin.drug_discovery import SecondaryPharmacology, Ligand

    ligand = Ligand.from_smiles("CCO")

    ml = SecondaryPharmacology(ligands=[ligand], method="ligand-ml")
    df = ml.run()

    dock = SecondaryPharmacology(ligands=[ligand], method="docking", effort=2)
    dock.start()
    dock.wait()
    df = dock.get_results()  # pose_score, binding_energy, etc.
"""

from __future__ import annotations

from asyncio import Task
import builtins
from typing import Any, Literal, Self

from beartype import beartype
import numpy as np
import pandas as pd

from deeporigin.drug_discovery.execution import Execution, _execution_outputs_dict
from deeporigin.drug_discovery.execution_mixins import (
    AsyncExecutableMixin,
    SyncExecutableMixin,
)
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.drug_discovery.structures.pose import PoseSet
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status

_UNIPROTS_ENUM_MISSING = (
    "SecondaryPharmacology tool definition is missing a non-empty uniprots enum "
    "(inputs.properties.uniprots.items.enum)."
)

#: Row count for :meth:`SecondaryPharmacology.get_panel`'s default preview.
_PANEL_PREVIEW_ROWS = 10

#: pose_score's real dynamic range -- used as a fixed clim on its own, and
#: as the rescaling window onto 0-1 for plot_ml_vs_docking.
_POSE_SCORE_CLIM = (0.5, 0.9)


def _uniprots_from_definition(definition: dict[str, Any]) -> list[str]:
    """Return the panel's UniProt accessions from a platform tool definition.

    Reads JSON Schema ``inputs.properties.uniprots.items.enum``.

    Args:
        definition: Tool definition dict from ``client.tools.get``.

    Returns:
        UniProt accessions in definition order.

    Raises:
        ValueError: If the enum is missing, empty, or not a list of strings.
    """
    inputs = definition.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError(_UNIPROTS_ENUM_MISSING)
    schema_properties = inputs.get("properties")
    if not isinstance(schema_properties, dict):
        raise ValueError(_UNIPROTS_ENUM_MISSING)
    uniprots_field = schema_properties.get("uniprots")
    if not isinstance(uniprots_field, dict):
        raise ValueError(_UNIPROTS_ENUM_MISSING)
    items = uniprots_field.get("items")
    if not isinstance(items, dict):
        raise ValueError(_UNIPROTS_ENUM_MISSING)
    enum = items.get("enum")
    if not isinstance(enum, list) or not enum:
        raise ValueError(_UNIPROTS_ENUM_MISSING)
    names = [item for item in enum if isinstance(item, str) and item]
    if len(names) != len(enum) or len(set(names)) != len(names):
        raise ValueError(_UNIPROTS_ENUM_MISSING)
    return list(names)


def _panel_from_definition(definition: dict[str, Any]) -> list[dict[str, str]]:
    """Return ``{"uniprot_id", "gene_name"}`` rows for the panel in a tool definition.

    Gene names come from ``inputs.properties.uniprots.items.x-enum-display-names``
    (optional metadata); an accession missing from that mapping falls back to
    itself so a display-name gap can't turn into a missing panel member.
    """
    accessions = _uniprots_from_definition(definition)
    display_names = (
        definition["inputs"]["properties"]["uniprots"].get("x-enum-display-names") or {}
    )
    return [
        {"uniprot_id": accession, "gene_name": display_names.get(accession, accession)}
        for accession in accessions
    ]


def _validate_uniprots(
    uniprots: list[str],
    *,
    allowed: frozenset[str],
) -> list[str]:
    """Return a copy of *uniprots* or raise if the selection is invalid."""
    if not uniprots:
        raise ValueError("uniprots must be non-empty when provided.")
    if len(uniprots) != len(set(uniprots)):
        raise ValueError("uniprots must not contain duplicates.")
    unknown = set(uniprots) - allowed
    if unknown:
        raise ValueError(
            f"Unknown UniProt accessions {sorted(unknown)}. Allowed: {sorted(allowed)}"
        )
    return list(uniprots)


def _docking_ligand_row(lig: Ligand) -> dict[str, Any]:
    """Build one ligand entry for the docking path (id and smiles only).

    Assumes ``lig.id`` is already set -- call ``self.ligands`` synced (see
    :meth:`SecondaryPharmacology._ensure_platform_inputs`) before this runs.
    Mirrors ``Docking._ligand_tool_input_row`` exactly.
    """
    return {"id": lig.id, "smiles": lig.smiles}


def _ligand_ml_ligand_rows(ligands: list[Ligand]) -> list[dict[str, Any]]:
    """Build ligand entries for the ligand-ml path (served, never synced).

    ``id`` is omitted when unset, not fabricated -- a fake id would publish
    to the platform keyed to a nonexistent Ligand. Use ``ligand_smiles`` to
    join results for an unsynced ligand.
    """
    rows: list[dict[str, Any]] = []
    for lig in ligands:
        row: dict[str, Any] = {"smiles": lig.smiles or ""}
        if lig.id is not None:
            row["id"] = lig.id
        rows.append(row)
    return rows


def _ligands_from_inputs(inputs: dict[str, Any]) -> list[Ligand]:
    """Rebuild ligands from stored secondary-pharma ``userInputs``.

    Returns an empty list (rather than raising, unlike ``Admet``'s equivalent)
    when ``ligands`` is absent -- a valid, expected shape for ``self_test`` runs.
    """
    raw = inputs.get("ligands")
    if not isinstance(raw, list) or not raw:
        return []
    ligands: list[Ligand] = []
    for idx, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(
                f"Cannot rehydrate SecondaryPharmacology: ligands[{idx}] is not an object."
            )
        smiles = row.get("smiles")
        if not smiles or not isinstance(smiles, str):
            raise ValueError(
                f"Cannot rehydrate SecondaryPharmacology: ligands[{idx}] has no SMILES."
            )
        ligand = Ligand.from_smiles(smiles)
        if row.get("id") is not None:
            ligand.id = str(row["id"])
        ligands.append(ligand)
    return ligands


# Result-explorer stores this table's rows under result_type="panelpose" --
# lowercased PanelPose (x-data-type), no separator. Same convention as the
# named result_type constants in platform/results.py (e.g. "preparedsystem"
# for PreparedSystem, "abferesult" for ABFEResult, "metabolismsite" for
# MetabolismSite) -- confirmed there rather than assumed here.
_PANEL_POSE_RESULT_TYPE = "panelpose"


def _load_panel_pose_rows(
    exec_id: str,
    *,
    client: DeepOriginClient,
    dto: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Load ``panel_poses`` rows from result-explorer, falling back to ``jobOutputs``.

    Mirrors :func:`~deeporigin.drug_discovery.docking_common.load_docking_poses_from_execution`'s
    shape: the docking path is an async Argo workflow, which usually persists
    rows only in result-explorer, not in a polled execution's ``jobOutputs``.

    Args:
        exec_id: Platform execution ID.
        client: API client.
        dto: Optional execution payload, consulted only if result-explorer
            has no rows yet (avoids an extra GET when one is already at hand).

    Returns:
        Flattened ``panel_poses`` row dicts (each result-explorer record's
        nested ``data`` merged with its ``id``).

    Raises:
        DeepOriginException: If no rows could be loaded from either source.
    """
    errors: list[str] = []

    try:
        response = client.results.get(
            compute_job_id=exec_id,
            result_type=_PANEL_POSE_RESULT_TYPE,
            limit=None,
        )
        records = [rec for rec in response.get("data", []) if isinstance(rec, dict)]
        rows: list[dict[str, Any]] = []
        for rec in records:
            data = rec.get("data")
            if not isinstance(data, dict):
                continue
            row = dict(data)
            if rec.get("id") is not None:
                row["id"] = str(rec["id"])
            rows.append(row)
        if rows:
            return rows
        errors.append("result-explorer returned zero panelpose rows")
    except Exception as exc:
        errors.append(f"result-explorer: {exc}")

    try:
        if dto is None:
            dto = client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
        outputs = _execution_outputs_dict(dto)
        raw = outputs.get("panel_poses")
        rows = (
            [dict(item) for item in raw if isinstance(item, dict)]
            if isinstance(raw, list)
            else []
        )
        if rows:
            return rows
        errors.append("jobOutputs.panel_poses is empty")
    except Exception as exc:
        errors.append(f"jobOutputs: {exc}")

    detail = "; ".join(errors)
    raise DeepOriginException(
        title="SecondaryPharmacology results missing",
        message=(
            f"No panel_poses rows could be loaded for execution {exec_id!r}. {detail}."
        ),
    )


def _ligand_plot_labels(ligands: list[Ligand]) -> dict[str, str]:
    """Map each ligand's smiles to a short, unique plot label.

    Shared by :meth:`SecondaryPharmacology._ligand_plot_labels` and
    :meth:`SecondaryPharmacology.plot_ml_vs_docking`. Dedupes by smiles
    first so a ligand reused across both runs doesn't collide with itself.
    """
    labels: dict[str, str] = {}
    seen_labels: set[str] = set()
    for i, lig in enumerate(ligands):
        if lig.smiles in labels:
            continue
        base = lig.name or (f"...{lig.id[-6:]}" if lig.id else f"ligand {i}")
        label = base
        n = 2
        while label in seen_labels:
            label = f"{base} ({n})"
            n += 1
        seen_labels.add(label)
        labels[lig.smiles] = label
    return labels


def _secondary_pharma_default_name(
    *,
    method: str,
    ligands: list[Ligand],
    uniprots: list[str] | tuple[str, ...] | None,
    self_test: bool,
) -> str:
    """Build a short human-readable label, e.g. ``SecondaryPharma (docking): 12 ligands vs full panel``."""
    if self_test:
        target = "self-test"
    else:
        n = len(ligands)
        target = f"{n} ligand" + ("" if n == 1 else "s")
    if uniprots:
        n_panel = len(uniprots)
        panel = f"{n_panel} panel target" + ("" if n_panel == 1 else "s")
    else:
        panel = "full panel"
    return f"SecondaryPharma ({method}): {target} vs {panel}"


class SecondaryPharmacology(
    Execution, SyncExecutableMixin, AsyncExecutableMixin, NotebookWatchMixin
):
    """Score ligands against a baked secondary-pharmacology kinase panel.

    Attributes:
        ligands: Ligands to score. Empty only when :attr:`self_test` is ``True``.
        method: Scoring path for this instance -- ``"docking"`` (async workflow,
            use :meth:`start`) or ``"ligand-ml"`` (served, use :meth:`run`).
        uniprots: Panel accessions to restrict scoring to, or ``None`` for the
            whole panel. Validated against the live tool definition's enum.
        effort: Docking effort level (1 = fastest, 5 = most thorough). Ignored
            on the ligand-ml path.
        self_test: When ``True``, runs the selected method against the full
            panel with a baked test ligand and ignores :attr:`ligands`.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["secondary_pharma"]["tool_key"]
    effort: int = 1

    @beartype
    def __init__(
        self,
        *,
        ligands: list[Ligand] | LigandSet | None = None,
        method: Literal["docking", "ligand-ml"] | None = None,
        uniprots: list[str] | None = None,
        effort: int = 1,
        self_test: bool = False,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["secondary_pharma"]["tool_version"],
        client: DeepOriginClient | None = None,
        name: str | None = None,
    ) -> None:
        """Configure a secondary-pharmacology panel run for one or more ligands.

        Args:
            ligands: Ligands to score. Required unless ``self_test=True``.
            method: ``"docking"`` (async, use :meth:`start`) or ``"ligand-ml"``
                (served, use :meth:`run`). No default -- pick deliberately.
            uniprots: Panel accessions to restrict to. Validated against the
                live tool definition. ``None`` or empty scores the whole panel.
            effort: Docking effort level (1-5). Ignored on the ligand-ml path.
            self_test: When ``True``, ``ligands`` is not required; the platform
                runs the selected method against the full panel with a baked
                test ligand.
            tool_version: Platform tool version. Defaults to the pinned major
                version in :data:`TOOL_KEYS_AND_VERSIONS`.
            client: Optional API client.
            name: Optional execution label. When omitted, generated from
                ``method``, ligand count (or ``self_test``), and ``uniprots``.

        Raises:
            ValueError: If ``method`` is omitted, if ``ligands`` is
                empty/omitted and ``self_test`` is ``False``, if
                ``self_test`` is ``True`` and ``ligands`` is also given, or
                if ``uniprots`` names accessions outside the live panel.
        """
        if method is None:
            raise ValueError("method is required: 'docking' or 'ligand-ml'.")

        if isinstance(ligands, LigandSet):
            resolved_ligands: list[Ligand] = list(ligands.ligands)
        elif ligands is not None:
            resolved_ligands = list(ligands)
        else:
            resolved_ligands = []

        if not resolved_ligands and not self_test:
            raise ValueError("ligands is required unless self_test=True.")
        if resolved_ligands and self_test:
            raise ValueError(
                "ligands is ignored when self_test=True (the platform scores "
                "a baked test ligand instead) -- pass one or the other, not both."
            )

        super().__init__(client=client)
        self.tool_version = tool_version
        self.effort = effort
        self._method = method
        self._self_test = self_test
        self._ligands = resolved_ligands

        allowed = self._fetch_definition_uniprots()
        self._allowed_uniprots: frozenset[str] | None = frozenset(allowed)
        self._uniprots: list[str] | tuple[str, ...] | None = (
            _validate_uniprots(uniprots, allowed=self._allowed_uniprots)
            if uniprots
            else None
        )
        self.name = (
            name
            if name is not None
            else _secondary_pharma_default_name(
                method=self._method,
                ligands=self._ligands,
                uniprots=self._uniprots,
                self_test=self._self_test,
            )
        )

    @property
    def ligands(self) -> list[Ligand]:
        """Ligands targeted by this run (read-only)."""
        return self._ligands

    @property
    def method(self) -> str:
        """Scoring path for this instance (``"docking"`` or ``"ligand-ml"``)."""
        return self._method

    @property
    def self_test(self) -> bool:
        """Whether this run scores the baked test ligand against the full panel."""
        return self._self_test

    @property
    def uniprots(self) -> list[str] | tuple[str, ...] | None:
        """Panel accessions this run is restricted to, or ``None`` for the whole panel.

        A mutable list on a draft instance. After an execution ``id`` is set, a
        tuple. ``None`` when unset or a rehydrated execution omitted the field.
        """
        return self._uniprots

    @uniprots.setter
    def uniprots(self, value: list[str] | None) -> None:
        """Replace the draft accession list, or clear it with ``None``."""
        if getattr(self, "_id", None) is not None:
            raise AttributeError(
                "cannot assign to 'uniprots': execution id is already set"
            )
        if value is None:
            self._uniprots = None
            return
        allowed = getattr(self, "_allowed_uniprots", None)
        if allowed is None:
            raise ValueError(
                "uniprots can only be set on a SecondaryPharmacology that "
                "loaded a tool definition."
            )
        self._uniprots = _validate_uniprots(value, allowed=allowed)

    def __repr__(self) -> str:
        """Return a concise summary of this secondary-pharma execution's configuration."""
        parts = ["SecondaryPharmacology("]
        parts.append(f"  method={self._method!r},")
        if self._self_test:
            parts.append("  self_test=True,")
        else:
            parts.append(f"  ligands={len(self._ligands)},")
        if self._uniprots:
            parts.append(f"  uniprots={list(self._uniprots)!r},")
        else:
            parts.append("  uniprots=full panel,")
        if self._method == "docking":
            parts.append(f"  effort={self.effort},")
        hint = (
            "call start() to execute asynchronously"
            if self._method == "docking"
            else "call run() to execute synchronously"
        )
        parts.append(f")  # {hint}")
        return "\n".join(parts)

    @classmethod
    def get_panel(
        cls,
        *,
        full: bool = False,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["secondary_pharma"]["tool_version"],
        client: DeepOriginClient | None = None,
    ) -> pd.DataFrame:
        """Return the current scoring panel, no ligand or instance required.

        Both methods validate ``uniprots`` against this same panel today --
        docking and ligand-ml are expected to grow independent, differently
        sized catalogs later, which this method will need to account for then.

        Args:
            full: Return every member instead of just a preview.
            tool_version: Platform tool version to look up. Defaults to the
                pinned major version in :data:`TOOL_KEYS_AND_VERSIONS`.
            client: Optional API client. Uses the default if not provided.

        Returns:
            A :class:`pandas.DataFrame` with one row per panel member
            (``uniprot_id``, ``gene_name``).
        """
        if client is None:
            client = DeepOriginClient()
        if client.tools is None:
            raise RuntimeError("DeepOriginClient has no tools API")
        definition = client.tools.get(tool_key=cls.tool_key, tool_version=tool_version)
        members = _panel_from_definition(definition)
        df = pd.DataFrame(members, columns=["uniprot_id", "gene_name"])
        if full or len(df) <= _PANEL_PREVIEW_ROWS:
            return df
        print(
            f"Showing {_PANEL_PREVIEW_ROWS} of {len(df)} panel members -- "
            "call get_panel(full=True) for the complete table."
        )
        return df.head(_PANEL_PREVIEW_ROWS)

    def _fetch_definition_uniprots(self) -> list[str]:
        """Return panel accessions from the live secondary-pharma tool definition."""
        if self.client.tools is None:
            raise RuntimeError("DeepOriginClient has no tools API")
        definition = self.client.tools.get(
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )
        return _uniprots_from_definition(definition)

    def update_from_dto(self, dto: dict[str, Any]) -> None:
        """Apply execution fields from ``dto`` and freeze ``uniprots``."""
        super().update_from_dto(dto)
        uniprots = getattr(self, "_uniprots", None)
        if self._id is not None and isinstance(uniprots, list):
            self._uniprots = tuple(uniprots)

    def _ensure_method(self, expected: str, *, alternative_call: str) -> None:
        """Raise if this instance's :attr:`method` does not match *expected*."""
        if self._method != expected:
            raise ValueError(
                f"method={self._method!r}: use {alternative_call}() instead."
            )

    def _ensure_platform_inputs(self) -> None:
        """Sync ligands to the data platform for the docking path.

        Only the docking path is a workflow that needs persisted ligand ids
        (mirrors ``Docking._ensure_platform_inputs``); the ligand-ml path is
        served directly from SMILES like ``Admet`` and is never synced.
        """
        LigandSet(ligands=self._ligands).sync(lazy=True, client=self.client)

    def _validate_effort(self) -> None:
        """Raise if :attr:`effort` is outside 1-5.

        The schema declares ``effort`` as a plain top-level input with no
        conditional relaxation for the ligand-ml path, so an out-of-range
        value is rejected there too, even though the tool ignores it once
        it's within range -- checked on both :meth:`run` and :meth:`start`.
        """
        if not 1 <= self.effort <= 5:
            raise DeepOriginException(
                f"effort must be between 1 and 5 inclusive, got {self.effort}"
            )

    def _ensure_uniprots_for_run(self) -> None:
        """Re-validate ``uniprots`` immediately before submission.

        The :attr:`uniprots` getter returns the live list, so an in-place
        edit (``job.uniprots.append(...)``) bypasses the setter's
        validation; this re-checks right before the payload is built,
        mirroring ``Admet._ensure_properties_for_run``.
        """
        if self._uniprots is None:
            return
        values = list(self._uniprots)
        allowed = getattr(self, "_allowed_uniprots", None)
        if allowed is not None:
            self._uniprots = _validate_uniprots(values, allowed=allowed)
            return
        if not values:
            raise ValueError("uniprots must be non-empty when provided.")
        if len(values) != len(set(values)):
            raise ValueError("uniprots must not contain duplicates.")

    def _make_inputs(self) -> dict[str, Any]:
        """Build tool ``inputs`` matching the secondary-pharma schema."""
        inputs: dict[str, Any] = {
            "methods": [self._method],
            "effort": self.effort,
            "self_test": self._self_test,
        }
        if self._ligands:
            if self._method == "docking":
                inputs["ligands"] = [_docking_ligand_row(lig) for lig in self._ligands]
            else:
                inputs["ligands"] = _ligand_ml_ligand_rows(self._ligands)
        if self._uniprots:
            inputs["uniprots"] = list(self._uniprots)
        return inputs

    def _make_payload(
        self,
        *,
        approve_amount: int | None,
        sync: bool,
    ) -> dict[str, Any]:
        """Build the body dict for ``client.executions.create``.

        No ``batchSize``: unlike ``deeporigin.docking``, this tool's Argo
        workflow (``tools/secondary-pharma/workflow/workflow.yaml``) is a
        single DAG task with no ligand fan-out -- there is nothing on the
        platform side to batch into today.
        """
        payload: dict[str, Any] = {
            "inputs": self._make_inputs(),
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
    def run(
        self,
        *,
        quote: bool = False,
        approve_amount: int | None = None,
    ) -> pd.DataFrame | SecondaryPharmacology:
        """Execute the ligand-ml path synchronously and return predictions.

        Valid only when :attr:`method` is ``"ligand-ml"``; use :meth:`start`
        for the docking path.

        With ``quote=True`` (or ``approve_amount=0``), requests a cost
        estimate only, updates execution fields from the platform DTO, and
        returns ``self`` without running inference.

        Args:
            quote: Shorthand for ``approve_amount=0``.
            approve_amount: Spend cap forwarded as ``approveAmount``.

        Returns:
            A :class:`pandas.DataFrame` of ligand-ml predictions, or ``self``
            when quoting.

        Raises:
            ValueError: If :attr:`method` is not ``"ligand-ml"``, or if
                ``uniprots`` was mutated in place into an invalid selection.
            DeepOriginException: If ``effort`` is outside 1-5, or the
                execution did not complete successfully.
        """
        self._ensure_method("ligand-ml", alternative_call="start")
        self._validate_effort()
        self._ensure_uniprots_for_run()
        resolved_amount = 0 if quote else approve_amount
        sync = resolved_amount is None
        dto = self._create_execution(
            data=self._make_payload(approve_amount=resolved_amount, sync=sync),
        )
        self.update_from_dto(dto)

        if quote or resolved_amount == 0:
            return self

        if not is_success_status(self.status):
            raise DeepOriginException(
                title="SecondaryPharmacology run did not succeed",
                message=(f"Execution {self.id!r} ended in {self.status!r} state."),
            )

        return self.get_results(dto)

    def _start_impl(self, *, approve_amount: int | None = None, **kwargs: Any) -> None:
        """Submit the docking path as a persisted async execution."""
        self._ensure_method("docking", alternative_call="run")
        self._validate_effort()
        self._ensure_uniprots_for_run()
        self._ensure_platform_inputs()
        payload = self._make_payload(approve_amount=approve_amount, sync=False)
        execution_dto = self._create_execution(data=payload)
        self._id = execution_dto.get("executionId")
        self.status = execution_dto.get("status")

    @beartype
    async def watch(
        self,
        *,
        interval: float = 5.0,
        blocking: bool = False,
    ) -> Task | None:
        """Live notebook updates for the docking path only.

        Valid only when :attr:`method` is ``"docking"`` -- the ligand-ml path
        is synchronous (:meth:`run` blocks until done), so there is never an
        in-flight async job to poll.

        See :meth:`~deeporigin.drug_discovery.notebook_watch_mixin.NotebookWatchMixin.watch`
        for the full parameter/return contract.

        Raises:
            ValueError: If :attr:`method` is not ``"docking"``.
        """
        self._ensure_method("docking", alternative_call="run")
        return await super().watch(interval=interval, blocking=blocking)

    @beartype
    def get_results(self, dto: dict[str, Any] | None = None) -> pd.DataFrame:
        """Return this execution's results as a :class:`pandas.DataFrame`.

        Method-aware, and the two paths load from different places:

        - ``ligand-ml`` is served/sync, so ``jobOutputs`` is populated in the
          same response that completed the run -- read directly, like
          :meth:`Admet.get_results <deeporigin.drug_discovery.admet.Admet.get_results>`.
        - ``docking`` is an async Argo workflow with no synchronous response
          to embed results into, so it only ever persists rows to
          result-explorer; ``jobOutputs`` on a polled execution is empty.
          Loaded via :func:`_load_panel_pose_rows`, mirroring
          :func:`~deeporigin.drug_discovery.docking_common.load_docking_poses_from_execution`'s
          result-explorer-first, ``jobOutputs``-fallback shape.

        The docking-path DataFrame includes ``pose_score``, ``binding_energy``,
        and ``file_path`` per pose. Every row also carries a ``method``
        column (``"ligand-ml"`` or ``"docking"``).

        Args:
            dto: Optional execution payload (``executions.create`` /
                ``executions.get``). On the ligand-ml path, used directly
                instead of an extra GET. On the docking path, only consulted
                as a fallback if result-explorer has no rows yet.

        Returns:
            A DataFrame of ``ligand_ml_predictions`` or ``panel_poses`` rows.

        Raises:
            ValueError: If :attr:`id` is unset and ``dto`` is omitted.
            DeepOriginException: If no rows could be loaded.
        """
        if self._method == "ligand-ml":
            if dto is None:
                exec_id = self._ensure_id()
                dto = self.client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
            outputs = _execution_outputs_dict(dto)
            rows = outputs.get("ligand_ml_predictions")
            if not isinstance(rows, list) or not rows:
                raise DeepOriginException(
                    title="SecondaryPharmacology results missing",
                    message=(
                        f"Execution {self.id!r} returned no "
                        "'ligand_ml_predictions' rows in jobOutputs."
                    ),
                )
            df = pd.DataFrame([row for row in rows if isinstance(row, dict)])
            df = self._backfill_ligand_ids(df)
            df.insert(0, "method", self._method)
            return df

        exec_id = self._ensure_id()
        rows = _load_panel_pose_rows(exec_id, client=self.client, dto=dto)
        df = pd.DataFrame(rows)
        df.insert(0, "method", self._method)
        return df

    def _backfill_ligand_ids(self, df: pd.DataFrame) -> pd.DataFrame:
        """Sync unregistered ligands (a no-op if already synced) so results
        carry a real ``ligand_id`` instead of ``None``."""
        if not self._ligands:
            return df
        LigandSet(ligands=self._ligands).sync(lazy=True, client=self.client)
        by_smiles = {lig.smiles: lig.id for lig in self._ligands}
        df["ligand_id"] = df["ligand_smiles"].map(by_smiles)
        return df

    def _ligand_plot_labels(self) -> dict[str, str]:
        """Map each ligand's smiles to a short, unique plot label."""
        return _ligand_plot_labels(self._ligands)

    def plot(
        self,
        *,
        dto: dict[str, Any] | None = None,
        metric: Literal["binding_energy", "pose_score"] = "binding_energy",
        clim: tuple[float, float] | None = None,
    ) -> None:
        """Visualize this run's results -- method-aware.

        ``ligand-ml``: heatmap colored by ``p_active`` (or ``p_affinity``).
        ``docking``: heatmap colored by ``metric``. No combined
        pose_score-vs-binding_energy view -- different scales, not directly
        comparable.

        Args:
            dto: Optional execution payload, forwarded to :meth:`get_results`.
            metric: Docking only. Which column to color the heatmap by.
            clim: Override the default color range (``(0.0, 1.0)`` for
                ligand-ml, :data:`_POSE_SCORE_CLIM` for ``pose_score``,
                auto-scaled for ``binding_energy``). A value outside the
                chosen range still renders, clipped to the nearest edge
                color -- a console note reports how many, if any.
        """
        df = self.get_results(dto)
        if self._method == "ligand-ml":
            from deeporigin.plots import WHITE_RED_HAZARD_PALETTE, plot_grid_heatmap

            labels = self._ligand_plot_labels()
            score = df["p_active"].fillna(df["p_affinity"])
            ligand_label = df["ligand_smiles"].map(lambda s: labels.get(s, s))
            pivot = df.assign(score=score, ligand_label=ligand_label).pivot_table(
                index="ligand_label", columns="gene_name", values="score"
            )
            plot_grid_heatmap(
                pivot.to_numpy(),
                row_labels=list(pivot.index),
                col_labels=list(pivot.columns),
                title="Secondary pharmacology: P(active/affinity)",
                value_label="score",
                palette=WHITE_RED_HAZARD_PALETTE,
                clim=clim if clim is not None else (0.0, 1.0),
            )
        else:
            from deeporigin.plots import WHITE_RED_HAZARD_PALETTE, plot_grid_heatmap

            labels = self._ligand_plot_labels()
            ligand_label = df["ligand_smiles"].map(lambda s: labels.get(s, s))
            pivot = df.assign(ligand_label=ligand_label).pivot_table(
                index="ligand_label", columns="gene_name", values=metric
            )
            # Same white-to-red hazard palette as ligand-ml for both
            # metrics. pose_score's default fixed range is _POSE_SCORE_CLIM
            # rather than (0, 1); binding_energy auto-scales unless clim=
            # overrides it.
            if metric == "pose_score":
                palette, default_clim, label = (
                    WHITE_RED_HAZARD_PALETTE,
                    _POSE_SCORE_CLIM,
                    "pose score",
                )
            else:
                palette, default_clim, label = (
                    list(reversed(WHITE_RED_HAZARD_PALETTE)),
                    None,
                    "binding energy (kcal/mol)",
                )
            plot_grid_heatmap(
                pivot.to_numpy(),
                row_labels=list(pivot.index),
                col_labels=list(pivot.columns),
                title=f"Secondary pharmacology docking: {label}",
                value_label=metric,
                palette=palette,
                clim=clim if clim is not None else default_clim,
            )

    def _get_poses(self, *, dto: dict[str, Any] | None = None) -> PoseSet:
        """Load and download docking-path panel poses as a :class:`PoseSet`.

        Underscore-prefixed: no receptor structure in the same coordinate
        frame as these poses is available yet to visualize them against
        (DDOS-7481). Use ``pose_score``/``binding_energy`` from
        :meth:`get_results` instead.

        Valid only when :attr:`method` is ``"docking"``. Loads the same
        ``panel_poses`` rows as :meth:`get_results` (result-explorer first,
        ``jobOutputs`` fallback -- see :func:`_load_panel_pose_rows`) and
        builds poses via
        :meth:`Pose.from_json <deeporigin.drug_discovery.structures.pose.Pose.from_json>`,
        which is generic over row dicts and not tied to the platform's
        ``result_type="pose"`` result group that ``panel_poses`` rows do not
        belong to (they are ``result_type="panelpose"``), then downloads the
        SDFs -- matching
        :meth:`Docking.get_poses <deeporigin.drug_discovery.docking.Docking.get_poses>`'s
        behavior exactly.

        Not available for a ``self_test`` run: the platform's baked test
        ligand has no ligand id, so the platform publishes no panel-pose
        rows for it at all (unidentified rows are filtered before
        publishing) -- there is nothing for :meth:`get_results` to return
        either in this case, so it isn't a usable fallback here.

        Args:
            dto: Optional execution payload, forwarded to :func:`_load_panel_pose_rows`.

        Returns:
            A :class:`PoseSet` of downloaded docked panel poses.

        Raises:
            ValueError: If :attr:`method` is not ``"docking"``, or if this is
                a ``self_test`` run.
        """
        self._ensure_method("docking", alternative_call="get_results")
        if self._self_test:
            raise ValueError(
                "_get_poses() is not available for self_test runs: the "
                "platform's baked test ligand has no ligand id, so no panel "
                "poses are published for it (get_results() has nothing to "
                "return either, for the same reason)."
            )
        exec_id = self._ensure_id()
        rows = _load_panel_pose_rows(exec_id, client=self.client, dto=dto)
        poses = PoseSet.from_json(rows, client=self.client)
        poses.download(client=self.client, lazy=True)
        return poses

    def _expected_panel_pairs(self) -> set[tuple[str, str]]:
        """Every (ligand id, uniprot) pair this run should have docked."""
        uniprots = self.uniprots or self._allowed_uniprots
        if not uniprots:
            uniprots = self._fetch_definition_uniprots()
        return {
            (lig.id, uniprot)
            for lig in self._ligands
            for uniprot in uniprots
            if lig.id is not None
        }

    def get_undocked_ligands(self) -> LigandSet | None:
        """Ligands with zero docked poses, or ``None`` if none. Docking only.

        A ligand with at least one docked pose won't appear here, even if
        it's missing poses for other targets -- use :meth:`get_missing_pairs`
        for that.
        """
        self._ensure_method("docking", alternative_call="get_results")
        rows = _load_panel_pose_rows(self._ensure_id(), client=self.client)
        docked_ids = {row.get("ligand_id") for row in rows}
        missing = [lig for lig in self._ligands if lig.id not in docked_ids]
        return LigandSet(ligands=missing) if missing else None

    def get_missing_pairs(self) -> list[tuple[Ligand, str]] | None:
        """(ligand, uniprot) pairs with no docked pose, or ``None`` if complete.

        Valid only when :attr:`method` is ``"docking"``.
        """
        self._ensure_method("docking", alternative_call="get_results")
        rows = _load_panel_pose_rows(self._ensure_id(), client=self.client)
        docked_pairs = {(row.get("ligand_id"), row.get("uniprot_id")) for row in rows}
        missing_keys = self._expected_panel_pairs() - docked_pairs
        by_id = {lig.id: lig for lig in self._ligands}
        missing = [
            (by_id[lig_id], uniprot)
            for lig_id, uniprot in missing_keys
            if lig_id in by_id
        ]
        return missing or None

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct a ``SecondaryPharmacology`` from a tools execution DTO.

        Restores ligands, method, uniprots, effort, and self_test from
        ``userInputs``. Does not fetch the live tool definition, so a
        rehydrated instance's ``uniprots`` is read-only until :meth:`duplicate`
        is called.

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client. Uses the default if not provided.

        Returns:
            A ``SecondaryPharmacology`` with ``id``, lifecycle fields, and
            domain inputs set.
        """
        instance = super().from_dto(dto, client=client)
        inputs: dict[str, Any] = dto.get("userInputs") or dto.get("inputs") or {}
        instance._ligands = _ligands_from_inputs(inputs)
        methods = inputs.get("methods")
        instance._method = (
            methods[0] if isinstance(methods, list) and methods else "docking"
        )
        instance._self_test = bool(inputs.get("self_test", False))
        raw_effort = inputs.get("effort")
        instance.effort = int(raw_effort) if raw_effort is not None else cls.effort
        raw_uniprots = inputs.get("uniprots")
        instance._uniprots = (
            tuple(raw_uniprots)
            if isinstance(raw_uniprots, list) and raw_uniprots
            else None
        )
        instance._allowed_uniprots = None
        return instance

    @classmethod
    def from_id(
        cls, id: str, *, client: DeepOriginClient | None = None, quiet: bool = True
    ) -> Self:
        """Same as :meth:`Execution.from_id`, but ``quiet`` defaults to True.

        Rebuilding ``ligands`` from stored inputs can emit chemistry
        normalization warnings (naming the raw SMILES) -- not useful noise
        when you're just reloading a run you already know about. Pass
        ``quiet=False`` to see them.
        """
        return super().from_id(id, client=client, quiet=quiet)

    @classmethod
    def from_last_run(
        cls, *, client: DeepOriginClient | None = None, quiet: bool = True
    ) -> Self:
        """Same as :meth:`Execution.from_last_run`, but ``quiet`` defaults to True."""
        return super().from_last_run(client=client, quiet=quiet)

    @classmethod
    def list(
        cls,
        *,
        client: DeepOriginClient | None = None,
        status: builtins.list[str] | None = None,
        project_id: str | None = None,
        quiet: bool = True,
    ) -> builtins.list[Self]:
        """Same as :meth:`Execution.list`, but ``quiet`` defaults to True."""
        return super().list(
            client=client, status=status, project_id=project_id, quiet=quiet
        )

    def duplicate(self, *, client: DeepOriginClient | None = None) -> Self:
        """Copy configuration into a new draft with a writable ``uniprots``.

        ``from_dto`` does not fetch the tool definition, so a rehydrated
        instance has no allowlist. Fetch it here so the draft can assign
        ``uniprots`` like a constructor-built instance.
        """
        new = super().duplicate(client=client)
        if isinstance(getattr(new, "_uniprots", None), tuple):
            new._uniprots = list(new._uniprots)
        if getattr(new, "_allowed_uniprots", None) is None:
            allowed = new._fetch_definition_uniprots()
            new._allowed_uniprots = frozenset(allowed)
        return new

    @staticmethod
    def plot_ml_vs_docking(
        ml_job: SecondaryPharmacology,
        dock_job: SecondaryPharmacology,
        *,
        ml_dto: dict[str, Any] | None = None,
        dock_dto: dict[str, Any] | None = None,
        pose_score_clim: tuple[float, float] | None = None,
        coverage: Literal["union", "intersection"] = "union",
    ) -> None:
        """Compare a ligand-ml run against a docking run on one heatmap.

        Each cell splits diagonally (top-left to bottom-right): upper =
        ``p_active`` (or ``p_affinity``), lower = ``pose_score``. Grey
        where a run has no data for that cell. The colorbar is labeled
        "No hit"/"Hit" rather than 0/1.

        Rows/columns are sorted so the strongest dual-agreement cells
        (``min(p_active, pose_score)``) land top-left.

        Args:
            ml_job: A completed ``method="ligand-ml"`` run.
            dock_job: A completed ``method="docking"`` run.
            ml_dto: Optional execution payload for ``ml_job.get_results()``.
            dock_dto: Optional execution payload for ``dock_job.get_results()``.
            pose_score_clim: Override the window :data:`_POSE_SCORE_CLIM`
                used to rescale ``pose_score`` onto 0-1. A ``pose_score``
                outside this window still renders, clipped to 0 or 1 -- a
                console note reports how many, if any.
            coverage: ``"union"`` (default) shows every ligand and target
                either run covered, grey where only one has data.
                ``"intersection"`` shows only ligands and targets both
                runs covered -- no grey cells from a target/ligand only
                one method ever looked at.

        Raises:
            ValueError: If either job isn't the expected method, or
                ``coverage="intersection"`` leaves nothing to plot.
        """
        if ml_job.method != "ligand-ml":
            raise ValueError(
                "plot_ml_vs_docking()'s first argument must be a method='ligand-ml' run."
            )
        if dock_job.method != "docking":
            raise ValueError(
                "plot_ml_vs_docking()'s second argument must be a method='docking' run."
            )

        ml_df = ml_job.get_results(ml_dto)
        dock_df = dock_job.get_results(dock_dto)

        labels = _ligand_plot_labels(list(ml_job.ligands) + list(dock_job.ligands))
        ml_label = ml_df["ligand_smiles"].map(lambda s: labels.get(s, s))
        dock_label = dock_df["ligand_smiles"].map(lambda s: labels.get(s, s))

        ml_score = ml_df["p_active"].fillna(ml_df["p_affinity"])
        ml_pivot = ml_df.assign(score=ml_score, ligand_label=ml_label).pivot_table(
            index="ligand_label", columns="gene_name", values="score"
        )
        # Rescale pose_score from its real observed range onto 0-1, so it's
        # on the same scale as p_active rather than compressed into a
        # narrow band of it.
        pose_lo, pose_hi = pose_score_clim or _POSE_SCORE_CLIM
        dock_score_unclipped = (dock_df["pose_score"] - pose_lo) / (pose_hi - pose_lo)
        n_clipped = int(
            ((dock_score_unclipped < 0.0) | (dock_score_unclipped > 1.0)).sum()
        )
        if n_clipped:
            print(
                f"Note: {n_clipped} of {len(dock_score_unclipped)} pose_score "
                f"value(s) fell outside the ({pose_lo}, {pose_hi}) rescaling "
                "window and were clipped to 0 or 1."
            )
        dock_score = dock_score_unclipped.clip(0.0, 1.0)
        dock_pivot = dock_df.assign(
            score=dock_score, ligand_label=dock_label
        ).pivot_table(index="ligand_label", columns="gene_name", values="score")

        if coverage == "intersection":
            dock_rows = set(dock_pivot.index)
            dock_cols = set(dock_pivot.columns)
            row_labels = [r for r in ml_pivot.index if r in dock_rows]
            col_labels = [c for c in ml_pivot.columns if c in dock_cols]
            if not row_labels or not col_labels:
                raise ValueError(
                    "coverage='intersection': ml_job and dock_job share no "
                    "ligand/target in common -- nothing to plot."
                )
        else:
            row_labels = list(dict.fromkeys([*ml_pivot.index, *dock_pivot.index]))
            col_labels = list(dict.fromkeys([*ml_pivot.columns, *dock_pivot.columns]))

        matrix_a = ml_pivot.reindex(index=row_labels, columns=col_labels).to_numpy()
        matrix_b = dock_pivot.reindex(index=row_labels, columns=col_labels).to_numpy()

        # Sort so the strongest dual-agreement cells land top-left. -inf (not
        # 0) for a missing half: a cell docking never touched shouldn't rank
        # as a confirmed non-hit, it should just not compete for the corner.
        agreement = np.where(
            np.isnan(matrix_a) | np.isnan(matrix_b),
            -np.inf,
            np.minimum(matrix_a, matrix_b),
        )
        row_order = np.argsort(-agreement.max(axis=1), kind="stable")
        col_order = np.argsort(-agreement.max(axis=0), kind="stable")

        matrix_a = matrix_a[row_order][:, col_order]
        matrix_b = matrix_b[row_order][:, col_order]
        row_labels = [row_labels[i] for i in row_order]
        col_labels = [col_labels[j] for j in col_order]

        from deeporigin.plots import plot_split_heatmap

        plot_split_heatmap(
            matrix_a,
            matrix_b,
            row_labels=row_labels,
            col_labels=col_labels,
            title="Secondary pharmacology: ligand-ML vs docking",
            label_a="p_active",
            label_b="pose_score (rescaled)",
            clim_labels=("No hit", "Hit"),
        )
