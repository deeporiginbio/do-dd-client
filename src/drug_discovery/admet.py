"""Admet -- predict admet-now endpoints for ligands (served, sync-only).

Backed by the served platform tool ``deeporigin.admet-properties``. One
:class:`Admet` instance is configured with ligands and an optional property
subset, then executed with a blocking :meth:`run`, which returns a
:class:`pandas.DataFrame` of predictions keyed by admet-now task folder names
(e.g. ``hERG_classification``, ``PPB_regression``).

Usage::

    from deeporigin.drug_discovery import Admet, Ligand

    ligand = Ligand.from_smiles("CCO")
    df = Admet(
        ligands=[ligand],
        properties=["hERG_classification", "AMES_classification"],
    ).run()
"""

from __future__ import annotations

from typing import Any, Literal

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import SyncExecutableMixin
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status
from deeporigin.utils.constants import (
    ADMET_EXECUTION_TIMEOUT_SECONDS,
    ADMET_PROPERTY_KEYS,
)

_ADMET_ID_COLUMNS: tuple[str, ...] = ("ligand_id", "smiles")


def _validate_admet_properties(properties: list[str] | None) -> list[str] | None:
    """Return validated property names or raise if any key is unknown."""

    if properties is None:
        return None
    if not properties:
        raise ValueError("properties must be non-empty when provided.")
    unknown = set(properties) - ADMET_PROPERTY_KEYS
    if unknown:
        raise ValueError(
            f"Unknown ADMET properties {sorted(unknown)}. "
            f"Allowed: {sorted(ADMET_PROPERTY_KEYS)}"
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


class Admet(Execution, SyncExecutableMixin):
    """Predict admet-now ADMET endpoints for ligands via the served admet tool.

    Configure the instance with one or more :class:`~deeporigin.drug_discovery.structures.ligand.Ligand`
    objects and an optional ``properties`` list, then call :meth:`run` to execute
    synchronously and receive a :class:`pandas.DataFrame`. Ligands are **not**
    mutated in place (contrast with :class:`~deeporigin.drug_discovery.molprops.Molprops`).

    When ``properties`` is omitted, the platform predicts all wired admet-now
    endpoints. When provided, only those task folder names are requested.

    Attributes:
        ligands: Ligands whose SMILES are sent to the tool.
        properties: Optional admet-now property keys to request, or ``None`` for all.
        method: Inference path — ``togo`` (default) or ``maplight``.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["admet"]["tool_key"]
    tool_version: str = TOOL_KEYS_AND_VERSIONS["admet"]["tool_version"]

    @beartype
    def __init__(
        self,
        *,
        ligands: list[Ligand] | LigandSet,
        properties: list[str] | None = None,
        method: Literal["maplight", "togo"] = "togo",
        client: DeepOriginClient | None = None,
    ) -> None:
        """Configure an ADMET prediction run for one or more ligands."""
        super().__init__(client=client)
        if isinstance(ligands, LigandSet):
            self._ligands: list[Ligand] = list(ligands.ligands)
        else:
            self._ligands = list(ligands)
        if not self._ligands:
            raise ValueError("Admet requires at least one ligand.")
        self._properties = _validate_admet_properties(properties)
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
    def properties(self) -> tuple[str, ...] | None:
        """Selected admet-now keys, or ``None`` when all endpoints are requested."""
        if self._properties is None:
            return None
        return tuple(self._properties)

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
            inputs["properties"] = self._properties
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
        """
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
        property_cols: list[str] = []
        if self._properties is not None:
            property_cols = list(self._properties)
        else:
            property_cols = sorted(
                col for col in df.columns if col not in _ADMET_ID_COLUMNS
            )
        ordered = [c for c in _ADMET_ID_COLUMNS if c in df.columns] + property_cols
        extra = [c for c in df.columns if c not in ordered]
        return df[ordered + extra]
