"""Admet -- predict admet-now endpoints for ligands (served, sync-only).

Backed by the served platform tool ``deeporigin.admet-properties``. One
:class:`Admet` instance is configured with ligands, then executed with a
blocking :meth:`run`, which returns a :class:`pandas.DataFrame` of predictions
keyed by admet-now task folder names (e.g. ``hERG_classification``,
``PPB_regression``).

Construction fetches the live tool definition and copies its endpoint enum
into :attr:`properties`. Trim that list before :meth:`run` to request a
subset. ``tool_version`` stays ``"latest"``.

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
from deeporigin.drug_discovery.execution_mixins import SyncExecutableMixin
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status
from deeporigin.utils.constants import ADMET_EXECUTION_TIMEOUT_SECONDS

_ADMET_ID_COLUMNS: tuple[str, ...] = ("ligand_id", "smiles")
_ADMET_ENUM_MISSING = (
    "Admet tool definition is missing a non-empty properties enum "
    "(inputs.properties.properties.items.enum)."
)


def _endpoints_from_definition(definition: dict[str, Any]) -> list[str]:
    """Return Admet endpoint names from a platform tool definition.

    Reads JSON Schema ``inputs.properties.properties.items.enum``.

    Args:
        definition: Tool definition dict from ``client.tools.get``.

    Returns:
        Endpoint names in definition order.

    Raises:
        ValueError: If the enum is missing, empty, or not a list of strings.
    """

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
    """Return per-ligand prediction rows from an admet-properties execution DTO.

    The served tool schema wraps rows under ``admet_properties``. Older mock
    responses used ``predictions``; both keys are accepted.
    """

    job_outputs = dto.get("jobOutputs")
    if not isinstance(job_outputs, dict):
        return []
    for key in ("admet_properties", "predictions"):
        rows = job_outputs.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _ligands_from_inputs(inputs: dict[str, Any]) -> list[Ligand]:
    """Rebuild ligands from stored admet-properties ``userInputs``."""

    raw = inputs.get("ligands")
    if not isinstance(raw, list) or not raw:
        raise ValueError("Cannot rehydrate Admet: stored inputs have no ligands.")
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


def _properties_from_inputs(
    inputs: dict[str, Any],
) -> tuple[str, ...] | None:
    """Restore recorded properties, or ``None`` when the payload omitted them.

    A present ``properties`` field must be a non-empty list of unique
    non-empty strings. Omitted or ``None`` stays ``None``.
    """

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


class Admet(Execution, SyncExecutableMixin):
    """Predict admet-now ADMET endpoints for ligands via the served admet tool.

    Construction fetches the ``deeporigin.admet-properties`` tool definition
    and copies its endpoint enum into :attr:`properties`. Trim or replace that
    list before :meth:`run`. Ligands are **not** mutated in place (contrast
    with :class:`~deeporigin.drug_discovery.molprops.Molprops`).

    Attributes:
        ligands: Ligands whose SMILES are sent to the tool.
        properties: Endpoint names for this run. A list on a draft instance
            (no execution ``id``); a tuple after ``id`` is set; ``None`` on a
            past execution that omitted the field.
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
        """Configure an ADMET prediction run for one or more ligands.

        Fetches the live tool definition and fills :attr:`properties` with its
        endpoint enum. Does not pin ``tool_version``; it stays ``"latest"``.
        """
        super().__init__(client=client)
        if isinstance(ligands, LigandSet):
            self._ligands: list[Ligand] = list(ligands.ligands)
        else:
            self._ligands = list(ligands)
        if not self._ligands:
            raise ValueError("Admet requires at least one ligand.")
        endpoints = self._fetch_definition_endpoints()
        self._allowed_endpoints: frozenset[str] | None = frozenset(endpoints)
        self._properties: list[str] | tuple[str, ...] | None = list(endpoints)
        self._method = method

    @property
    def ligands(self) -> list[Ligand]:
        """Ligands targeted by this run (read-only)."""
        return self._ligands

    @property
    def method(self) -> str:
        """Selected admet-now inference method."""
        return self._method

    @property
    def properties(self) -> list[str] | tuple[str, ...] | None:
        """Endpoint names for this run.

        A mutable list on a draft instance. After an execution ``id`` is set,
        a tuple. ``None`` when a past execution omitted the field.
        """
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
        """Copy configuration into a new draft with writable ``properties``.

        ``from_dto`` does not fetch the tool definition, so a rehydrated
        instance has no allowlist. Fetch it here so the draft can assign
        ``properties`` like a constructor-built instance.
        """
        new = super().duplicate(client=client)
        if isinstance(getattr(new, "_properties", None), tuple):
            new._properties = list(new._properties)
        if getattr(new, "_allowed_endpoints", None) is None:
            endpoints = new._fetch_definition_endpoints()
            new._allowed_endpoints = frozenset(endpoints)
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

    def _make_inputs(self) -> dict[str, Any]:
        """Build tool ``inputs`` matching the admet-properties schema."""
        ligand_payloads: list[dict[str, str]] = []
        for idx, lig in enumerate(self._ligands):
            payload: dict[str, str] = {"smiles": lig.smiles or ""}
            ligand_id = lig.id if lig.id is not None else str(idx)
            payload["id"] = str(ligand_id)
            ligand_payloads.append(payload)
        inputs: dict[str, Any] = {"ligands": ligand_payloads}
        if self._method != "togo":
            inputs["method"] = self._method
        if self._properties is not None:
            inputs["properties"] = list(self._properties)
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

    @beartype
    def run(
        self,
        *,
        quote: bool = False,
        approve_amount: int | None = None,
    ) -> pd.DataFrame | Admet:
        """Execute admet-properties synchronously and return predictions.

        With ``quote=True`` (or ``approve_amount=0``), requests a cost estimate
        only, updates execution fields from the platform DTO, and returns
        ``self`` without running inference.

        Args:
            quote: Shorthand for ``approve_amount=0``.
            approve_amount: Spend cap forwarded as ``approveAmount``.

        Returns:
            A :class:`pandas.DataFrame` of predictions on a normal run, or
            ``self`` when quoting.

        Raises:
            DeepOriginException: If the execution did not complete successfully
                or no predictions could be parsed.
            ValueError: If ``properties`` is empty, has duplicates, or names
                endpoints not on the fetched definition.
        """
        self._ensure_properties_for_run()
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
                title="ADMET prediction did not complete",
                message=(
                    f"Admet execution ended in {self.status!r} state "
                    f"(execution id {self.id!r})."
                ),
            )

        cost = Execution._quotation_total(dto)
        if cost is not None and cost > 0:
            self._cost = cost

        return self.get_results(dto)

    @beartype
    def get_results(self, dto: dict[str, Any] | None = None) -> pd.DataFrame:
        """Return this execution's predictions as a :class:`pandas.DataFrame`.

        Args:
            dto: Optional execution payload from ``executions.create`` /
                ``executions.get``.

        Returns:
            DataFrame with ``ligand_id``, ``smiles``, and requested property columns.

        Raises:
            ValueError: If :attr:`id` is unset and ``dto`` is omitted.
            DeepOriginException: If no predictions could be parsed.
        """
        if dto is None:
            exec_id = self._ensure_id()
            dto = self.client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]

        rows = _execution_predictions(dto)
        if not rows:
            raise DeepOriginException(
                title="ADMET predictions missing",
                message=(
                    f"Admet execution {self.id!r} returned no admet_properties "
                    f"rows in jobOutputs."
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
        """Construct an ``Admet`` from a tools execution DTO.

        Restores ligands, method, and recorded ``properties`` from
        ``userInputs`` (falling back to ``inputs``). Does not fetch the live
        tool definition. Omitted ``properties`` stays ``None``.

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client. Uses the default if not provided.

        Returns:
            An ``Admet`` with ``id``, lifecycle fields, and domain inputs set.

        Raises:
            ValueError: If stored inputs have no ligands.
        """
        instance = super().from_dto(dto, client=client)
        inputs: dict[str, Any] = dto.get("userInputs") or dto.get("inputs") or {}
        instance._ligands = _ligands_from_inputs(inputs)
        instance._properties = _properties_from_inputs(inputs)
        instance._allowed_endpoints = None
        method = inputs.get("method")
        instance._method = method if method in ("maplight", "togo") else "togo"
        return instance
