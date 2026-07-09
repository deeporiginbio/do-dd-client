"""Unit tests for generic tool execution helpers and ToolExecution."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.drug_discovery.tool_execution import (
    ToolExecution,
    _build_inputs_from_schema,
    _coerce,
    _coerce_ligands,
    _coerce_protein,
    _repr_value,
    _serialize,
    _x_data_type_base,
)

SAMPLE_DEF: dict[str, Any] = {
    "key": "deeporigin.test",
    "version": "1.0.0",
    "inputs": {
        "properties": {
            "protein": {"x-data-type": "Protein"},
            "ligands": {"items": {"x-data-type": "Ligand"}},
            "effort": {"default": 1},
            "note": {"type": "string"},
        }
    },
}


def test_x_data_type_base_property_level() -> None:
    """Read x-data-type from a property schema."""
    assert _x_data_type_base({"x-data-type": "Protein"}) == "Protein"


def test_x_data_type_base_items_level() -> None:
    """Read x-data-type from array items schema."""
    schema = {"items": {"x-data-type": "Ligand"}}
    assert _x_data_type_base(schema) == "Ligand"


def test_x_data_type_base_missing() -> None:
    """Return None when no x-data-type is declared."""
    assert _x_data_type_base({}) is None
    assert _x_data_type_base({"x-data-type": "  "}) is None


def test_coerce_protein_passthrough() -> None:
    """_coerce_protein returns an existing Protein unchanged."""
    protein = Protein(name="pdb", id="pid")
    assert _coerce_protein(protein) is protein


def test_coerce_protein_from_dict() -> None:
    """_coerce_protein builds a Protein from a dict payload."""
    protein = _coerce_protein(
        {"name": "my-protein", "id": "p1", "file_path": "/remote/a.pdb"}
    )

    assert protein.name == "my-protein"
    assert protein.id == "p1"
    assert protein.remote_path == "/remote/a.pdb"


def test_coerce_protein_invalid_type() -> None:
    """_coerce_protein rejects unsupported types."""
    with pytest.raises(TypeError, match="protein must be dict or Protein"):
        _coerce_protein(42)


def test_coerce_ligands_from_smiles_dicts() -> None:
    """_coerce_ligands builds a LigandSet from dict rows."""
    ligands = _coerce_ligands([{"smiles": "CCO", "id": "l1"}, {"smiles": "c1ccccc1"}])

    assert isinstance(ligands, LigandSet)
    assert len(ligands.ligands) == 2
    assert ligands.ligands[0].smiles == "CCO"
    assert ligands.ligands[0].id == "l1"


def test_coerce_ligands_missing_smiles_raises() -> None:
    """_coerce_ligands requires a non-empty smiles key on dict rows."""
    with pytest.raises(TypeError, match="non-empty string 'smiles'"):
        _coerce_ligands([{"id": "l1"}])


def test_coerce_ligands_single_ligand() -> None:
    """_coerce_ligands wraps a single Ligand in a LigandSet."""
    ligand = Ligand.from_smiles("CCO")
    ligands = _coerce_ligands(ligand)

    assert len(ligands.ligands) == 1
    assert ligands.ligands[0] is ligand


def test_coerce_known_and_unknown_types() -> None:
    """_coerce maps Protein/Ligand types and passes through primitives."""
    protein = _coerce("Protein", {"name": "p"})
    assert isinstance(protein, Protein)

    assert _coerce(None, "plain") == "plain"
    assert _coerce("String", None) is None


def test_serialize_protein_and_ligands() -> None:
    """_serialize converts SDK objects to API dict shapes."""
    protein = Protein(name="p", id="pid", remote_path="/remote/a.pdb")
    ligands = LigandSet(ligands=[Ligand.from_smiles("CCO", id="l1")])

    assert _serialize("Protein", protein) == {
        "id": "pid",
        "file_path": "/remote/a.pdb",
    }
    assert _serialize("Ligand", ligands) == [{"id": "l1", "smiles": "CCO"}]


def test_build_inputs_from_schema_defaults_and_overrides() -> None:
    """_build_inputs_from_schema merges kwargs, defaults, and None."""
    inputs = _build_inputs_from_schema(
        SAMPLE_DEF,
        {
            "protein": {"name": "p", "id": "pid"},
            "ligands": [{"smiles": "CCO"}],
            "note": "custom",
        },
    )

    assert isinstance(inputs["protein"], Protein)
    assert isinstance(inputs["ligands"], LigandSet)
    assert inputs["effort"] == 1
    assert inputs["note"] == "custom"


def test_repr_value_truncates_long_values() -> None:
    """_repr_value shortens very long repr strings."""
    long_text = "x" * 200
    rendered = _repr_value(long_text)

    assert rendered.endswith("...")
    assert len(rendered) == 120


def test_repr_value_protein_and_ligand_set() -> None:
    """_repr_value formats Protein and LigandSet compactly."""
    protein = Protein(name="p", id="pid")
    ligands = LigandSet(ligands=[Ligand.from_smiles("CCO")])

    assert "Protein" in _repr_value(protein)
    assert "LigandSet(1 ligand)" in _repr_value(ligands)


def test_tool_execution_attr_access_and_mutation() -> None:
    """ToolExecution proxies schema fields through __getattr__ and __setattr__."""
    execution = ToolExecution(
        definition=SAMPLE_DEF,
        inputs={"effort": 2, "note": "a"},
        client=MagicMock(),
    )

    assert execution.effort == 2
    execution.effort = 5
    assert execution.effort == 5

    with pytest.raises(AttributeError):
        _ = execution.missing_field


def test_tool_execution_repr() -> None:
    """ToolExecution __repr__ includes tool metadata and inputs."""
    execution = ToolExecution(
        definition=SAMPLE_DEF,
        inputs={"effort": 1},
        client=MagicMock(),
    )

    text = repr(execution)

    assert "deeporigin.test" in text
    assert "effort=1" in text


def test_tool_execution_serialize_inputs() -> None:
    """_serialize_inputs converts coerced inputs back to JSON-friendly dicts."""
    protein = Protein(name="p", id="pid", remote_path="/a.pdb")
    ligands = LigandSet(ligands=[Ligand.from_smiles("CCO", id="l1")])
    execution = ToolExecution(
        definition=SAMPLE_DEF,
        inputs={"protein": protein, "ligands": ligands, "effort": 2},
        client=MagicMock(),
    )

    serialized = execution._serialize_inputs()

    assert serialized["protein"] == {"id": "pid", "file_path": "/a.pdb"}
    assert serialized["ligands"] == [{"id": "l1", "smiles": "CCO"}]
    assert serialized["effort"] == 2


def test_tool_execution_build_tool_inputs_metadata() -> None:
    """_build_tool_inputs includes protein metadata from the first Protein input."""
    protein = Protein(name="p", id="pid", remote_path="/remote/protein.pdb")
    execution = ToolExecution(
        definition=SAMPLE_DEF,
        inputs={"protein": protein, "effort": 1},
        client=MagicMock(),
    )

    params, metadata = execution._build_tool_inputs()

    assert params["protein"]["id"] == "pid"
    assert metadata["protein_file"] == "protein.pdb"
    assert metadata["protein_hash"] == ""


def test_tool_execution_resolve_quote_mode_and_payload() -> None:
    """_make_payload builds async quote payload with optional approve amount."""
    execution = ToolExecution(
        definition=SAMPLE_DEF,
        inputs={"effort": 1, "note": "run"},
        client=MagicMock(),
    )
    execution.name = "my-run"

    assert execution._resolve_quote_mode(None) == "async"
    payload = execution._make_payload(approve_amount=0, mode="async")

    assert payload["inputs"]["effort"] == 1
    assert payload["name"] == "my-run"
    assert payload["approveAmount"] == 0


def test_tool_execution_from_definition() -> None:
    """from_definition fetches the tool definition and coerces inputs."""
    client = MagicMock()
    client.tools.get.return_value = SAMPLE_DEF

    execution = ToolExecution.from_definition(
        tool_key="deeporigin.test",
        tool_version="1.0.0",
        client=client,
        effort=3,
        protein={"name": "p", "id": "pid"},
    )

    assert execution.tool_key == "deeporigin.test"
    assert execution.effort == 3
    assert isinstance(execution.protein, Protein)
    client.tools.get.assert_called_once_with(
        tool_key="deeporigin.test",
        tool_version="1.0.0",
    )


def test_tool_execution_from_dto() -> None:
    """from_dto rehydrates inputs from an execution DTO."""
    client = MagicMock()
    client.tools.get.return_value = SAMPLE_DEF
    dto = {
        "executionId": "exec-1",
        "status": "Running",
        "tool": {"key": "deeporigin.test", "version": "1.0.0"},
        "userInputs": {
            "effort": 2,
            "ligands": [{"smiles": "CCO", "id": "l1"}],
        },
    }

    with patch.object(ToolExecution, "tool_key", "deeporigin.test"):
        execution = ToolExecution.from_dto(dto, client=client)

    assert execution.id == "exec-1"
    assert execution.effort == 2
    assert isinstance(execution.ligands, LigandSet)


def test_tool_execution_ensure_platform_inputs() -> None:
    """_ensure_platform_inputs calls sync(lazy=True) on syncable inputs."""
    syncable = MagicMock()
    execution = ToolExecution(
        definition=SAMPLE_DEF,
        inputs={"protein": syncable},
        client=MagicMock(),
    )

    execution._ensure_platform_inputs()

    syncable.sync.assert_called_once_with(lazy=True, client=execution.client)


def test_tool_execution_start_impl_creates_execution() -> None:
    """_start_impl posts a payload via _create_execution."""
    client = MagicMock()
    client.executions.create.return_value = {
        "executionId": "exec-99",
        "status": "Running",
    }
    execution = ToolExecution(
        definition=SAMPLE_DEF,
        inputs={"effort": 1},
        client=client,
    )
    execution._create_execution = MagicMock(
        return_value={"executionId": "exec-99", "status": "Running"}
    )

    execution._start_impl(approve_amount=10)

    execution._create_execution.assert_called_once()
    assert execution.id == "exec-99"
    assert execution.status == "Running"


def test_tool_execution_from_definition_requires_tools_api() -> None:
    """from_definition raises when the client has no tools API."""
    client = MagicMock()
    client.tools = None

    with pytest.raises(RuntimeError, match="no tools API"):
        ToolExecution.from_definition(
            tool_key="deeporigin.test",
            tool_version="1.0.0",
            client=client,
        )


def test_tool_execution_from_definition_default_client() -> None:
    """from_definition uses DeepOriginClient when client is omitted."""
    client = MagicMock()
    client.tools.get.return_value = SAMPLE_DEF

    with patch(
        "deeporigin.drug_discovery.tool_execution.DeepOriginClient",
        return_value=client,
    ):
        execution = ToolExecution.from_definition(
            tool_key="deeporigin.test",
            tool_version="1.0.0",
            effort=1,
        )

    assert execution.effort == 1
