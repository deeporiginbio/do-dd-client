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

import json
import os
from pathlib import Path
import tempfile
from typing import Any, Literal, Self
import uuid

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
from deeporigin.platform.errors import raise_for_platform_restriction
from deeporigin.platform.project_scope import require_client_project_id
from deeporigin.utils.constants import (
    ADMET_EXECUTION_TIMEOUT_SECONDS,
    ADMET_INLINE_LIGAND_CAP,
    ADMET_LIGAND_LIST_UPLOAD_PREFIX,
    ADMET_RESULT_EXPLORER_PAGE_SIZE,
    ADMET_WORKFLOW_LIGAND_THRESHOLD,
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
        k.endswith("_classification") or k.endswith("_regression") for k in payload
    ):
        return [payload]
    return []


def _ligand_payloads(ligands: list[Ligand]) -> list[dict[str, str]]:
    """Build ``{smiles, id?}`` dicts for tool inputs or a Ligand list file."""

    ligand_payloads: list[dict[str, str]] = []
    for idx, lig in enumerate(ligands):
        smiles = lig.smiles or ""
        if not smiles:
            raise ValueError(f"ligands[{idx}] has no SMILES.")
        payload: dict[str, str] = {"smiles": smiles}
        if lig.id is not None:
            payload["id"] = str(lig.id)
        ligand_payloads.append(payload)
    return ligand_payloads


def _ligands_from_payload_rows(raw: list[Any]) -> list[Ligand]:
    """Rebuild ligands from inline or file JSON ligand rows."""

    ligands: list[Ligand] = []
    for idx, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(
                f"Cannot rehydrate Admet: ligands[{idx}] is not an object."
            )
        smiles = row.get("smiles")
        if not smiles or not isinstance(smiles, str):
            raise ValueError(f"Cannot rehydrate Admet: ligands[{idx}] has no SMILES.")
        ligand = Ligand.from_smiles(smiles)
        if row.get("id") is not None:
            ligand.id = str(row["id"])
        ligands.append(ligand)
    return ligands


def _ligands_from_list_file_bytes(payload: bytes) -> list[Ligand]:
    """Parse a Ligand list file body into ligands."""

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Cannot rehydrate Admet: ligands_file is not valid UTF-8: {exc}"
        ) from exc
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Cannot rehydrate Admet: ligands_file is not valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(parsed, list) or not parsed:
        raise ValueError(
            "Cannot rehydrate Admet: ligands_file must be a non-empty JSON array."
        )
    return _ligands_from_payload_rows(parsed)


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

    raw = inputs.get("ligands")
    if isinstance(raw, list) and raw:
        return _ligands_from_payload_rows(raw)

    remote = inputs.get("ligands_file")
    if isinstance(remote, str) and remote.strip():
        if client is None or client.files is None:
            raise ValueError(
                "Cannot rehydrate Admet: client with files is required "
                "to download ligands_file."
            )
        try:
            local_path = client.files.download(remote.strip(), direct=True)
            payload = Path(local_path).read_bytes()
        except Exception as exc:
            raise ValueError(
                f"Cannot rehydrate Admet: failed to download ligands_file "
                f"{remote!r}: {exc}"
            ) from exc
        return _ligands_from_list_file_bytes(payload)

    raise ValueError(
        "Cannot rehydrate Admet: stored inputs have no ligands, ligands_file, "
        "or project."
    )


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
    :data:`~deeporigin.utils.constants.ADMET_INLINE_LIGAND_CAP` ligands
    (blocking served path). For larger batches, call :meth:`start`, then
    :meth:`wait` or :meth:`watch`, then :meth:`get_results`. Project-wide runs
    use :class:`Admet` with ``ligands=[]`` and ``client.project_id`` set; call
    :meth:`start` only.

    Attributes:
        ligands: Ligands whose SMILES are sent to the tool (empty for project runs).
        properties: Endpoint names for this run.
        method: Inference path — ``togo`` (default) or ``maplight``.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["admet"]["tool_key"]
    tool_version: str = TOOL_KEYS_AND_VERSIONS["admet"]["tool_version"]

    @beartype
    def __init__(
        self,
        *,
        ligands: list[Ligand] | LigandSet,
        method: Literal["maplight", "togo"] = "togo",
        client: DeepOriginClient | None = None,
    ) -> None:
        """Configure an ADMET prediction run.

        Fetches the live tool definition and fills :attr:`properties` with its
        endpoint enum. Pass ``ligands=[]`` for a project-wide workflow run
        (requires ``client.project_id``).
        """
        super().__init__(client=client)
        if isinstance(ligands, LigandSet):
            self._ligands: list[Ligand] = list(ligands.ligands)
        else:
            self._ligands = list(ligands)
        endpoints = self._fetch_definition_endpoints()
        self._allowed_endpoints: frozenset[str] | None = frozenset(endpoints)
        self._properties: list[str] | tuple[str, ...] | None = list(endpoints)
        self._method = method
        self._remote_ligands_file: str | None = None

    @property
    def ligands(self) -> list[Ligand]:
        """Ligands targeted by this run (read-only)."""
        return self._ligands

    @property
    def method(self) -> str:
        """Selected admet-now inference method."""
        return self._method

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
        """Upload ligands JSON to UFA and return the remote path."""

        if self._remote_ligands_file is not None:
            return self._remote_ligands_file
        if self.client.files is None:
            raise ValueError(
                "Cannot upload Ligand list file: client.files is not available."
            )

        payloads = _ligand_payloads(self._ligands)
        remote_path = f"{ADMET_LIGAND_LIST_UPLOAD_PREFIX}{uuid.uuid4().hex}.json"
        fd, tmp_name = tempfile.mkstemp(suffix=".json", prefix="admet-ligands-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payloads, handle, allow_nan=False)
            self.client.files.upload(tmp_name, remote_path)
        finally:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

        self._remote_ligands_file = remote_path
        return remote_path

    def _make_inputs(self) -> dict[str, Any]:
        """Build tool ``inputs`` matching the admet-properties schema."""

        inputs: dict[str, Any] = {}
        if self._method != "togo":
            inputs["method"] = self._method
        if self._properties is not None:
            inputs["properties"] = list(self._properties)

        if self._is_project_run():
            project_id = require_client_project_id(self.client)
            inputs["project"] = {"id": project_id}
            return inputs

        n = len(self._ligands)
        if n > ADMET_INLINE_LIGAND_CAP:
            remote = self._ensure_ligands_file_uploaded()
            inputs["ligands_file"] = remote
            inputs["ligands_count"] = n
            return inputs

        inputs["ligands"] = _ligand_payloads(self._ligands)
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
                f"run() supports at most {ADMET_INLINE_LIGAND_CAP} ligands "
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
        remote = inputs.get("ligands_file")
        if isinstance(remote, str) and remote.strip():
            instance._remote_ligands_file = remote.strip()
        return instance
