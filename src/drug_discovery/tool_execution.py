"""Experimental generic tool execution from platform tool definitions."""

from __future__ import annotations

import os
from typing import Any, Self

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import AsyncExecutableMixin, QuoteMixin
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.platform.client import DeepOriginClient

_KNOWN_MODELS: dict[str, str] = {
    "Protein": "protein",
    "Ligand": "ligands",
}


def _x_data_type_base(schema: dict[str, Any]) -> str | None:
    """Extract the top-level class name from ``x-data-type``.

    Checks both the property itself and ``items`` (for arrays of objects).
    Returns e.g. ``"Protein"``, ``"Ligand"``, or ``None`` for primitives.
    """
    xdt = schema.get("x-data-type")
    if isinstance(xdt, str) and xdt.strip():
        return xdt.split(".", 1)[0].strip()
    items = schema.get("items")
    if isinstance(items, dict):
        ixdt = items.get("x-data-type")
        if isinstance(ixdt, str) and ixdt.strip():
            return ixdt.split(".", 1)[0].strip()
    return None


def _coerce(base_type: str | None, raw: Any) -> Any:
    """Coerce *raw* into the SDK object indicated by *base_type*."""
    if raw is None:
        return None
    model = _KNOWN_MODELS.get(base_type or "")
    if model == "protein":
        return _coerce_protein(raw)
    if model == "ligands":
        return _coerce_ligands(raw)
    return raw


def _coerce_protein(raw: Any) -> Protein:
    if isinstance(raw, Protein):
        return raw
    if isinstance(raw, dict):
        return Protein(
            name=str(raw.get("name") or "protein"),
            id=raw.get("id"),
            remote_path=raw.get("file_path"),
        )
    raise TypeError(f"protein must be dict or Protein, got {type(raw).__name__}")


def _coerce_ligands(raw: Any) -> LigandSet:
    if isinstance(raw, LigandSet):
        return raw
    if isinstance(raw, Ligand):
        return LigandSet(ligands=[raw])
    if isinstance(raw, list):
        out: list[Ligand] = []
        for row in raw:
            if isinstance(row, Ligand):
                out.append(row)
            elif isinstance(row, dict):
                smiles = row.get("smiles")
                if not smiles or not isinstance(smiles, str):
                    raise TypeError(
                        "ligand dict must include a non-empty string 'smiles' key"
                    )
                ligand_kwargs: dict[str, Any] = {}
                lid = row.get("id")
                if lid is not None:
                    ligand_kwargs["id"] = lid
                out.append(Ligand.from_smiles(smiles, **ligand_kwargs))
            else:
                raise TypeError(
                    f"ligand row must be dict or Ligand, got {type(row).__name__}"
                )
        return LigandSet(ligands=out)
    raise TypeError(
        f"ligands must be list, Ligand, or LigandSet, got {type(raw).__name__}"
    )


def _serialize(base_type: str | None, value: Any) -> Any:
    """Serialize an SDK object back to a JSON-compatible dict for the tools API."""
    if value is None:
        return None
    model = _KNOWN_MODELS.get(base_type or "")
    if model == "protein" and isinstance(value, Protein):
        return {"id": value.id, "file_path": value.remote_path}
    if model == "ligands" and isinstance(value, LigandSet):
        return [{"id": lig.id, "smiles": lig.smiles} for lig in value.ligands]
    return value


def _build_inputs_from_schema(
    definition: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """Walk ``inputs.properties`` and build the full inputs dict.

    For each top-level property in the tool definition schema:
    - Use the caller-supplied override if present.
    - Else use the JSON Schema ``default`` if declared.
    - Else ``None``.

    Values whose ``x-data-type`` maps to a known SDK class (Protein, Ligand)
    are coerced; everything else is stored as-is.
    """
    schema = definition.get("inputs") or {}
    properties = schema.get("properties") or {}
    out: dict[str, Any] = {}
    for name, prop_schema in properties.items():
        ps = prop_schema if isinstance(prop_schema, dict) else {}
        base = _x_data_type_base(ps)
        if name in overrides:
            raw = overrides[name]
        elif "default" in ps:
            raw = ps["default"]
        else:
            raw = None
        out[name] = _coerce(base, raw)
    return out


def _repr_value(val: Any) -> str:
    if isinstance(val, LigandSet):
        n = len(val.ligands)
        return f"LigandSet({n} ligand{'s' if n != 1 else ''})"
    if isinstance(val, Protein):
        return f"Protein(name={val.name!r}, id={val.id!r})"
    text = repr(val)
    if len(text) > 120:
        return f"{text[:117]}..."
    return text


def _apply_dto_common_fields(
    instance: Any,
    dto: dict[str, Any],
    client: DeepOriginClient,
) -> None:
    instance.client = client
    instance._id = dto["executionId"]
    instance._estimate = None
    instance._cost = None
    instance.status = dto.get("status")
    instance.progress = dto.get("progressReport")
    instance.app = dto.get("app")
    instance.approve_amount = dto.get("approveAmount")
    instance.created_at = dto.get("createdAt")
    instance.created_by = dto.get("createdBy")
    instance.started_at = dto.get("startedAt")
    instance.completed_at = dto.get("completedAt")
    instance.session = dto.get("session")
    instance._execution_dto = dto
    instance._name = dto.get("name")
    instance._watch_task = None
    instance._display_id = None
    instance._last_html = None
    quotation = dto.get("quotationResult") or {}
    successful = quotation.get("successfulQuotations", [])
    if not successful:
        return
    price = successful[0].get("priceTotal")
    if price is None:
        return
    instance._estimate = float(price)
    if instance.status == "Succeeded":
        instance._cost = float(price)


class ToolExecution(Execution, QuoteMixin, AsyncExecutableMixin, NotebookWatchMixin):
    """Generic tool execution driven by a platform tool definition.

    Instead of a hand-written constructor per tool, this class reads
    ``inputs.properties`` from the tool definition JSON, maps each top-level
    property to an instance attribute (coercing known ``x-data-type`` values
    like ``Protein`` and ``Ligand`` into SDK objects), and exposes
    ``quote()`` / ``start()`` / ``sync()`` via the standard mixins.
    """

    tool_key: str = ""
    tool_version: str = ""

    def __init__(
        self,
        *,
        definition: dict[str, Any],
        inputs: dict[str, Any],
        client: DeepOriginClient | None = None,
    ) -> None:
        super().__init__(client=client)
        self._definition = definition
        self._inputs = inputs
        self.tool_key = str(definition.get("key") or "")
        self.tool_version = str(definition.get("version") or "")

    def __getattr__(self, name: str) -> Any:
        """Proxy attribute access to ``_inputs`` for schema-derived fields."""
        inputs = self.__dict__.get("_inputs")
        if inputs is not None and name in inputs:
            return inputs[name]
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute {name!r}"
        )

    def __setattr__(self, name: str, value: Any) -> None:
        """Write schema-derived fields into ``_inputs``; everything else to ``__dict__``."""
        inputs = self.__dict__.get("_inputs")
        if inputs is not None and name in inputs:
            inputs[name] = value
        else:
            super().__setattr__(name, value)

    def __repr__(self) -> str:
        bits: list[str] = [
            f"tool_key={self.tool_key!r}",
            f"tool_version={self.tool_version!r}",
        ]
        for name, val in self._inputs.items():
            bits.append(f"{name}={_repr_value(val)}")
        return "ToolExecution(\n  " + ",\n  ".join(bits) + "\n)"

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_definition(
        cls,
        *,
        tool_key: str,
        tool_version: str,
        client: DeepOriginClient | None = None,
        **kwargs: Any,
    ) -> Self:
        """Build a ToolExecution from a platform tool definition.

        Fetches the definition via ``client.tools.get``, then walks
        ``inputs.properties``.  Each property becomes an attribute on the
        instance, populated from *kwargs* → schema ``default`` → ``None``.
        """
        if client is None:
            client = DeepOriginClient()
        if client.tools is None:
            raise RuntimeError("DeepOriginClient has no tools API")
        definition = client.tools.get(tool_key=tool_key, tool_version=tool_version)
        inputs = _build_inputs_from_schema(definition, kwargs)
        return cls(definition=definition, inputs=inputs, client=client)

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Rehydrate from an execution DTO (e.g. ``client.executions.get``)."""
        if client is None:
            client = DeepOriginClient()
        if client.tools is None:
            raise RuntimeError("DeepOriginClient has no tools API")
        tool_info = dto["tool"]
        definition = client.tools.get(
            tool_key=tool_info["key"],
            tool_version=tool_info["version"],
        )
        user_inputs = dto.get("userInputs") or {}
        inputs = _build_inputs_from_schema(definition, user_inputs)
        instance = object.__new__(cls)
        instance._definition = definition
        instance._inputs = inputs
        instance.tool_key = tool_info["key"]
        instance.tool_version = tool_info["version"]
        _apply_dto_common_fields(instance, dto, client)
        return instance

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def _serialize_inputs(self) -> dict[str, Any]:
        """Convert ``_inputs`` back to JSON-serializable form for the tools API."""
        schema = self._definition.get("inputs") or {}
        properties = schema.get("properties") or {}
        out: dict[str, Any] = {}
        for name, value in self._inputs.items():
            ps = properties.get(name, {})
            ps = ps if isinstance(ps, dict) else {}
            out[name] = _serialize(_x_data_type_base(ps), value)
        return out

    def _ensure_platform_inputs(self) -> None:
        """Call ``.sync(lazy=True)`` on any input value that supports it."""
        for v in self._inputs.values():
            if v is None:
                continue
            sync = getattr(v, "sync", None)
            if callable(sync):
                sync(lazy=True, client=self.client)

    def _build_tool_inputs(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return ``(params, metadata)`` for ``client.executions.create``."""
        meta: dict[str, Any] = {}
        for val in self._inputs.values():
            if isinstance(val, Protein):
                ref = val.local_path or val.remote_path
                meta["protein_file"] = os.path.basename(str(ref)) if ref else ""
                meta["protein_hash"] = (
                    val.to_hash() if val.structure is not None else ""
                )
                break
        return self._serialize_inputs(), meta

    # ------------------------------------------------------------------
    # Execution lifecycle (QuoteMixin / AsyncExecutableMixin hooks)
    # ------------------------------------------------------------------

    def _get_quote(self) -> dict[str, Any]:
        self._ensure_platform_inputs()
        params, metadata = self._build_tool_inputs()
        payload: dict[str, Any] = {
            "inputs": params,
            "outputs": {},
            "metadata": metadata,
        }
        if self.name is not None:
            payload["name"] = self.name
        payload["approveAmount"] = 0
        return self.client.executions.create(
            data=payload,
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )

    def _start_impl(self, *, approve_amount: int | None = None) -> None:
        self._ensure_platform_inputs()
        params, metadata = self._build_tool_inputs()
        payload: dict[str, Any] = {
            "inputs": params,
            "outputs": {},
            "metadata": metadata,
        }
        if self.name is not None:
            payload["name"] = self.name
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount
        execution_dto = self.client.executions.create(
            data=payload,
            tool_key=self.tool_key,
            tool_version=self.tool_version,
        )
        self._id = execution_dto.get("executionId")
        self.status = execution_dto.get("status")
