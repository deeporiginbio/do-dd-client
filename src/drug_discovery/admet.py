"""Admet -- predict admet-now endpoints for ligands.

Backed by the platform tool ``deeporigin.admet-properties``. One :class:`Admet`
instance is configured with ligands (or an empty list for project-wide workflow
runs scoped to ``client.project_id``), then executed with a blocking
:meth:`run` (≤100 ligands) or asynchronous :meth:`start` (101+ ligands or
project-wide).

Construction fetches the live tool definition and copies its endpoint enum
into :attr:`properties`. Trim that list before :meth:`run` or :meth:`start`.
``tool_version`` is pinned to major ``"2"``.

Usage::

    from deeporigin.drug_discovery import Admet, Ligand

    ligand = Ligand.from_smiles("CCO")
    admet = Admet(ligands=[ligand])
    admet.properties = ["hERG_classification", "AMES_classification"]
    df = admet.run()
"""

from __future__ import annotations

from typing import Any, Literal, Self

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import (
    AsyncExecutableMixin,
    SyncExecutableMixin,
)
from deeporigin.drug_discovery.ligand_list_file import (
    ligand_payloads,
    ligand_rows_from_inputs,
    ligands_from_rows,
    upload_ligand_list,
)
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status
from deeporigin.platform.errors import raise_for_platform_restriction
from deeporigin.platform.project_scope import require_client_project_id
from deeporigin.utils.constants import (
    ADMET_EXECUTION_TIMEOUT_SECONDS,
    ADMET_LIGAND_LIST_UPLOAD_PREFIX,
    ADMET_MIN_BATCH_SIZE,
    ADMET_RESULT_EXPLORER_PAGE_SIZE,
    ADMET_WORKFLOW_LIGAND_THRESHOLD,
    INLINE_LIGAND_CAP,
    QUOTE_APPROVE_AMOUNT,
)

_ADMET_ID_COLUMNS: tuple[str, ...] = ("ligand_id", "smiles")
_ADMET_ENUM_MISSING = (
    "Admet tool definition is missing a non-empty properties enum "
    "(inputs.properties.properties.items.enum)."
)
_RESULT_TYPE_ADMET = "admetproperty"


def _endpoints_from_definition(definition: dict[str, Any]) -> list[str]:
    """Return Admet endpoint names from a platform tool definition."""

    inputs = definition.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError(_ADMET_ENUM_MISSING)
    schema_properties = inputs.get("properties")
    if not isinstance(schema_properties, dict):
        raise ValueError(_ADMET_ENUM_MISSING)
    properties_field = schema_properties.get("properties")
    if not isinstance(properties_field, dict):
        raise ValueError(_ADMET_ENUM_MISSING)
    items = properties_field.get("items")
    if not isinstance(items, dict):
        raise ValueError(_ADMET_ENUM_MISSING)
    enum = items.get("enum")
    if not isinstance(enum, list) or not enum:
        raise ValueError(_ADMET_ENUM_MISSING)
    names = [item for item in enum if isinstance(item, str) and item]
    if len(names) != len(enum) or len(set(names)) != len(names):
        raise ValueError(_ADMET_ENUM_MISSING)
    return list(names)


def _validate_admet_properties(
    properties: list[str] | tuple[str, ...],
    *,
    allowed: frozenset[str],
) -> list[str]:
    """Return a copy of *properties* or raise if the selection is invalid."""

    if not properties:
        raise ValueError("properties must be non-empty.")
    if len(properties) != len(set(properties)):
        raise ValueError("properties must not contain duplicates.")
    unknown = set(properties) - allowed
    if unknown:
        raise ValueError(
            f"Unknown ADMET properties {sorted(unknown)}. Allowed: {sorted(allowed)}"
        )
    return list(properties)


def _execution_predictions(dto: dict[str, Any]) -> list[dict[str, Any]]:
    """Return per-ligand prediction rows from an admet-properties execution DTO."""

    job_outputs = dto.get("jobOutputs")
    if not isinstance(job_outputs, dict):
        return []
    for key in ("admet_properties", "predictions"):
        rows = job_outputs.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _job_output_admet_rows(dto: dict[str, Any]) -> list[dict[str, Any]]:
    """Return prediction dict rows from ``jobOutputs`` on *dto*."""

    return _execution_predictions(dto)


def _rows_from_result_explorer(response: Any) -> list[dict[str, Any]]:
    """Extract flat ADMET prediction rows from a result-explorer response."""

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
            rows.extend(_expand_admet_payload(data))
    return rows


def _expand_admet_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return flat ADMET rows from a result-explorer ``data`` payload."""

    nested = payload.get("admetproperties")
    if isinstance(nested, list):
        return [item for item in nested if isinstance(item, dict)]
    if "ligand_id" in payload or any(
        k.endswith(("_classification", "_regression")) for k in payload
    ):
        return [payload]
    return []


def _properties_from_inputs(
    inputs: dict[str, Any],
) -> tuple[str, ...] | None:
    """Restore recorded properties, or ``None`` when the payload omitted them."""

    if "properties" not in inputs or inputs.get("properties") is None:
        return None
    raw = inputs.get("properties")
    if not isinstance(raw, list):
        raise ValueError("Cannot rehydrate Admet: stored properties is not a list.")
    if not raw:
        raise ValueError("Cannot rehydrate Admet: stored properties is empty.")
    names: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item:
            raise ValueError(
                "Cannot rehydrate Admet: stored properties must be non-empty strings."
            )
        names.append(item)
    if len(names) != len(set(names)):
        raise ValueError(
            "Cannot rehydrate Admet: stored properties must not contain duplicates."
        )
    return tuple(names)


def _ligands_from_inputs(
    inputs: dict[str, Any],
    *,
    client: DeepOriginClient | None = None,
) -> list[Ligand]:
    """Rebuild ligands from stored admet ``userInputs``."""

    project = inputs.get("project")
    if isinstance(project, dict) and project.get("id"):
        return []

    rows = ligand_rows_from_inputs(inputs, client=client, label="Admet")
    if not rows:
        raise ValueError(
            "Cannot rehydrate Admet: stored inputs have no ligands, ligands_file, "
            "or project."
        )
    return ligands_from_rows(rows, label="Admet")


class Admet(
    Execution,
    SyncExecutableMixin,
    AsyncExecutableMixin,
    NotebookWatchMixin,
):
    """Predict admet-now ADMET endpoints via ``deeporigin.admet-properties``.

    ADMET prediction fields are **not** written onto ligands (contrast with
    :class:`~deeporigin.drug_discovery.molprops.Molprops`). ``run()`` and
    ``start()`` may register ligands on the platform (assigning ``id`` /
    ``project``) via :meth:`_ensure_platform_inputs`, except quote-only
    ``run(quote=True)`` which sends SMILES without syncing first.

    Use :meth:`run` for at most
    :data:`~deeporigin.utils.constants.INLINE_LIGAND_CAP` ligands
    (blocking served path). For larger batches, call :meth:`start`, then
    :meth:`wait` or :meth:`watch`, then :meth:`get_results`. Project-wide runs
    use :class:`Admet` with ``ligands=[]`` and ``client.project_id`` set; call
    :meth:`start` only.

    Attributes:
        ligands: Ligands whose SMILES are sent to the tool (empty for project runs).
        properties: Endpoint names for this run.
        method: Inference path — ``togo`` (default) or ``maplight``.
        batch_size: Ligands per workflow pod on file and project runs, or
            ``None`` for the tool default.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["admet"]["tool_key"]
    tool_version: str = TOOL_KEYS_AND_VERSIONS["admet"]["tool_version"]

    @beartype
    def __init__(
        self,
        *,
        ligands: list[Ligand] | LigandSet,
        method: Literal["maplight", "togo"] = "togo",
        batch_size: int | None = None,
        client: DeepOriginClient | None = None,
    ) -> None:
        """Configure an ADMET prediction run.

        Fetches the live tool definition and fills :attr:`properties` with its
        endpoint enum. Pass ``ligands=[]`` for a project-wide workflow run
        (requires ``client.project_id``).

        ``batch_size`` sets ligands per workflow pod (``batchSize``) on file
        and project runs; a smaller value fans out to more pods. It is ignored
        on inline runs, which never fan out. ``None`` uses the tool default.

        Raises:
            ValueError: If ``batch_size`` is below the tool minimum (50).
        """
        if batch_size is not None and batch_size < ADMET_MIN_BATCH_SIZE:
            raise ValueError(
                f"batch_size must be at least {ADMET_MIN_BATCH_SIZE} (got {batch_size})."
            )
        super().__init__(client=client)
        if isinstance(ligands, LigandSet):
            self._ligands: list[Ligand] = list(ligands.ligands)
        else:
            self._ligands = list(ligands)
        endpoints = self._fetch_definition_endpoints()
        self._allowed_endpoints: frozenset[str] | None = frozenset(endpoints)
        self._properties: list[str] | tuple[str, ...] | None = list(endpoints)
        self._method = method
        self._batch_size = batch_size
        self._remote_ligands_file: str | None = None

    @property
    def ligands(self) -> list[Ligand]:
        """Ligands targeted by this run (read-only)."""
        return self._ligands

    @property
    def method(self) -> str:
        """Selected admet-now inference method."""
        return self._method

    @property
    def batch_size(self) -> int | None:
        """Ligands per workflow pod, or ``None`` for the tool default."""
        return self._batch_size

    def _is_project_run(self) -> bool:
        """True when this instance targets all ligands in ``client.project_id``."""

        return len(self._ligands) == 0

    @property
    def properties(self) -> list[str] | tuple[str, ...] | None:
        """Endpoint names for this run."""
        return self._properties

    @properties.setter
    def properties(self, value: list[str]) -> None:
        """Replace the draft endpoint list with a non-empty unique subset."""
        if getattr(self, "_id", None) is not None:
            raise AttributeError(
                "cannot assign to 'properties': execution id is already set"
            )
        allowed = getattr(self, "_allowed_endpoints", None)
        if allowed is None:
            raise ValueError(
                "properties can only be set on an Admet that loaded a tool definition."
            )
        self._properties = _validate_admet_properties(value, allowed=allowed)

    def _fetch_definition_endpoints(self) -> list[str]:
        """Return endpoint names from the live admet-properties tool definition."""
        if self.client.tools is None:
            raise RuntimeError("DeepOriginClient has no tools API")
        definition = self.client.tools.get(
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )
        return _endpoints_from_definition(definition)

    def update_from_dto(self, dto: dict[str, Any]) -> None:
        """Apply execution fields from ``dto`` and freeze ``properties``."""
        super().update_from_dto(dto)
        properties = getattr(self, "_properties", None)
        if self._id is not None and isinstance(properties, list):
            self._properties = tuple(properties)

    def duplicate(self, *, client: DeepOriginClient | None = None) -> Self:
        """Copy configuration into a new draft with writable ``properties``."""
        new = super().duplicate(client=client)
        if isinstance(getattr(new, "_properties", None), tuple):
            new._properties = list(new._properties)
        if getattr(new, "_allowed_endpoints", None) is None:
            endpoints = new._fetch_definition_endpoints()
            new._allowed_endpoints = frozenset(endpoints)
            if new._properties is None:
                new._properties = list(endpoints)
        new._remote_ligands_file = None
        if not hasattr(new, "status"):
            new.status = None
        return new

    def _ensure_properties_for_run(self) -> None:
        """Validate in-place edits before submitting the execution."""
        if self._properties is None:
            return
        values = list(self._properties)
        allowed = getattr(self, "_allowed_endpoints", None)
        if allowed is not None:
            self._properties = _validate_admet_properties(values, allowed=allowed)
            return
        if not values:
            raise ValueError("properties must be non-empty.")
        if len(values) != len(set(values)):
            raise ValueError("properties must not contain duplicates.")

    def _ensure_platform_inputs(self) -> None:
        """Register ligands on the data platform when a ligand list is present."""

        if not self._ligands:
            return
        LigandSet(ligands=self._ligands).sync(lazy=True, client=self.client)

    def _ensure_ligands_file_uploaded(self) -> str:
        """Upload ligands JSON to UFA once and return the remote path."""

        if self._remote_ligands_file is None:
            self._remote_ligands_file = upload_ligand_list(
                ligand_payloads(self._ligands),
                client=self.client,
                prefix=ADMET_LIGAND_LIST_UPLOAD_PREFIX,
            )
        return self._remote_ligands_file

    def _make_inputs(self) -> dict[str, Any]:
        """Build tool ``inputs`` matching the admet-properties schema."""

        inputs: dict[str, Any] = {}
        if self._method != "togo":
            inputs["method"] = self._method
        if self._properties is not None:
            inputs["properties"] = list(self._properties)
        workflow_run = self._is_project_run() or len(self._ligands) > INLINE_LIGAND_CAP
        if workflow_run and self._batch_size is not None:
            inputs["batchSize"] = self._batch_size

        if self._is_project_run():
            project_id = require_client_project_id(self.client)
            inputs["project"] = {"id": project_id}
            return inputs

        n = len(self._ligands)
        if n > INLINE_LIGAND_CAP:
            remote = self._ensure_ligands_file_uploaded()
            inputs["ligands_file"] = remote
            inputs["ligands_count"] = n
            return inputs

        inputs["ligands"] = ligand_payloads(self._ligands)
        return inputs

    def _make_payload(
        self,
        *,
        approve_amount: int | None,
        sync: bool,
    ) -> dict[str, Any]:
        """Build the body dict for ``client.executions.create``."""
        payload: dict[str, Any] = {
            "inputs": self._make_inputs(),
            "outputs": {},
            "metadata": {},
            "sync": sync,
        }
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount
        return payload

    def _create_execution(
        self,
        *,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Submit ``data`` with the extended ADMET POST timeout."""
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
            timeout=ADMET_EXECUTION_TIMEOUT_SECONDS,
        )

    def _ensure_run_ligand_count(self) -> None:
        """Raise if :meth:`run` is used with a workflow-scale batch."""

        if self._is_project_run():
            raise ValueError(
                "run() cannot target a project-wide ADMET job. "
                "Use start() with ligands=[] and client.project_id set."
            )
        n = len(self._ligands)
        if n >= ADMET_WORKFLOW_LIGAND_THRESHOLD:
            raise ValueError(
                f"run() supports at most {INLINE_LIGAND_CAP} ligands "
                f"(got {n}). Use start() then wait() or watch()."
            )

    def _ensure_start_preconditions(self) -> None:
        """Raise if :meth:`start` is not valid for this configuration."""

        if self._is_project_run():
            require_client_project_id(self.client)
            return
        n = len(self._ligands)
        if n >= ADMET_WORKFLOW_LIGAND_THRESHOLD:
            return
        raise ValueError(
            f"start() requires at least {ADMET_WORKFLOW_LIGAND_THRESHOLD} ligands "
            f"or ligands=[] for a project-wide run (got {n}). Use run() for smaller "
            f"batches."
        )

    def _fetch_output_rows(
        self,
        *,
        dto: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Load ADMET rows from result-explorer, else ``jobOutputs``."""

        exec_id = getattr(self, "_id", None)

        if exec_id is not None:
            try:
                response = super().get_results(
                    result_type=_RESULT_TYPE_ADMET,
                    limit=None,
                    page_size=ADMET_RESULT_EXPLORER_PAGE_SIZE,
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
        return _job_output_admet_rows(dto)

    @beartype
    def run(
        self,
        *,
        quote: bool = False,
        approve_amount: int | None = None,
    ) -> pd.DataFrame | Admet | None:
        """Execute admet-properties synchronously and return predictions.

        With ``quote=True`` (or ``approve_amount=-1``), requests a cost estimate
        only, updates execution fields from the platform DTO, and returns
        ``self`` without running inference.

        When the platform responds with ``Quoted`` status, updates this instance
        and returns ``None``. Call :meth:`~deeporigin.drug_discovery.execution.Execution.confirm`
        to proceed, then :meth:`get_results`.

        Returns:
            A :class:`pandas.DataFrame` on success, ``self`` when quoting, or
            ``None`` when the run is waiting for confirmation.
        """
        self._ensure_run_ligand_count()
        self._ensure_properties_for_run()
        resolved_amount = QUOTE_APPROVE_AMOUNT if quote else approve_amount
        if resolved_amount != QUOTE_APPROVE_AMOUNT:
            self._ensure_platform_inputs()
        dto = self._create_execution(
            data=self._make_payload(approve_amount=resolved_amount, sync=True),
        )
        self.update_from_dto(dto)

        if quote or resolved_amount == QUOTE_APPROVE_AMOUNT:
            return self

        if self.status == "Quoted":
            return None

        if not is_success_status(self.status):
            raise_for_platform_restriction(dto)
            raise DeepOriginException(
                title="ADMET prediction did not complete",
                message=(
                    f"Admet execution ended in {self.status!r} state "
                    f"(execution id {self.id!r}). When status is Quoted, call "
                    f"confirm() then get_results()."
                ),
            )

        cost = Execution._quotation_total(dto)
        if cost is not None and cost > 0:
            self._cost = cost

        return self.get_results(dto)

    def _start_impl(self, *, approve_amount: int | None = None, **kwargs: Any) -> None:
        """Submit admet-properties as a persisted async execution."""

        del kwargs
        self._ensure_start_preconditions()
        self._ensure_properties_for_run()
        self._ensure_platform_inputs()
        execution_dto = self._create_execution(
            data=self._make_payload(approve_amount=approve_amount, sync=False),
        )
        if execution_dto.get("executionId") is None:
            raise ValueError("Execution response must contain 'executionId'") from None

        self.update_from_dto(execution_dto)

    @beartype
    def get_results(self, dto: dict[str, Any] | None = None) -> pd.DataFrame:
        """Return this execution's predictions as a :class:`pandas.DataFrame`."""

        rows = self._fetch_output_rows(dto=dto)
        if not rows:
            raise DeepOriginException(
                title="ADMET predictions missing",
                message=(
                    f"Admet execution {self.id!r} returned no admet_properties "
                    f"rows from the data platform or jobOutputs."
                ),
            )

        df = pd.DataFrame(rows)
        if self._properties is not None:
            property_cols = list(self._properties)
        else:
            property_cols = sorted(
                col for col in df.columns if col not in _ADMET_ID_COLUMNS
            )
        ordered = [c for c in _ADMET_ID_COLUMNS if c in df.columns] + property_cols
        extra = [c for c in df.columns if c not in ordered]
        return df[ordered + extra]

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct an ``Admet`` from a tools execution DTO."""

        instance = super().from_dto(dto, client=client)
        inputs: dict[str, Any] = dto.get("userInputs") or dto.get("inputs") or {}
        instance._ligands = _ligands_from_inputs(inputs, client=instance.client)
        instance._properties = _properties_from_inputs(inputs)
        instance._allowed_endpoints = None
        method = inputs.get("method")
        instance._method = method if method in ("maplight", "togo") else "togo"
        raw_batch = inputs.get("batchSize")
        instance._batch_size = raw_batch if isinstance(raw_batch, int) else None
        remote = inputs.get("ligands_file")
        if isinstance(remote, str) and remote.strip():
            instance._remote_ligands_file = remote.strip()
        return instance
