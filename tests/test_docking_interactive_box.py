"""Tests for interactive docking box SDK integration."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from deeporigin.drug_discovery.constrained_docking import ConstrainedDocking
from deeporigin.drug_discovery.docking import Docking
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.utils.iframe_comm_bridge import (
    _WIDGET_ESM,
    DOCKING_BOX_COMMIT_ACK_MESSAGE_TYPE,
    DOCKING_BOX_COMMIT_MESSAGE_TYPE,
    IframeCommHandle,
    render_interactive_html_with_comm,
)


def test_docking_commit_docking_box_stores_rotation(
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """_commit_docking_box stores normalized rotation on the Docking instance."""
    docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
    )
    docking._commit_docking_box(
        {
            "center": [0.0, 0.0, 0.0],
            "box_size": [15.0, 15.0, 15.0],
            "rotation_deg": [0.0, 45.0, 0.0],
        }
    )
    assert docking.rotation_deg == [0.0, 45.0, 0.0]


def test_docking_tool_inputs_forward_rotation_deg(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """_build_tool_inputs includes rotation_deg after interactive commit."""
    docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
        client=client,
    )
    docking._rotation_deg = [0.0, 30.0, 0.0]
    params, _ = docking._build_tool_inputs()
    assert params["pocket"]["rotation_deg"] == [0.0, 30.0, 0.0]


def test_constrained_docking_tool_inputs_omit_rotation_deg(
    client,
    registered_protein,
    unregistered_pocket,
) -> None:
    """Constrained docking v1 does not forward rotation_deg to the tool."""
    from tests.test_constrained_docking import _make_reference_pair

    reference_ligand, reference_pose = _make_reference_pair()
    reference_ligand.remote_path = "testing/brd-2.sdf"
    reference_ligand.id = "brd-2"
    reference_pose.remote_path = "testing/docked-pose.sdf"
    reference_pose.id = "brd-2-pose"

    test_a = Ligand.from_smiles("CCO")
    test_a.id = "test-a"
    test_b = Ligand.from_smiles("CC(C)O")
    test_b.id = "test-b"

    constrained = ConstrainedDocking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        reference_ligand=reference_ligand,
        reference_pose=reference_pose,
        ligands=[test_a, test_b],
        client=client,
    )
    constrained._rotation_deg = [0.0, 45.0, 0.0]
    params, _ = constrained._build_tool_inputs()
    assert "rotation_deg" not in params["pocket"]


def test_show_box_interactive_uses_comm_bridge(
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """show_box(interactive=True) wires the iframe Comm bridge."""
    docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
    )
    handle = IframeCommHandle(bridge_id="test-bridge")

    with (
        patch(
            "deeporigin.utils.notebook.get_notebook_environment",
            return_value="jupyter",
        ),
        patch(
            "deeporigin.utils.iframe_comm_bridge.render_interactive_html_with_comm",
            return_value=handle,
        ) as mock_bridge,
    ):
        result = docking.show_box(interactive=True)

    assert result is handle
    mock_bridge.assert_called_once()
    on_commit = mock_bridge.call_args.kwargs["on_commit"]
    assert on_commit.__func__ is docking._commit_docking_box.__func__
    assert on_commit.__self__ is docking


def test_show_box_interactive_rejects_pose_overlay(
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """interactive=True cannot be combined with pose overlays in v1."""
    docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
    )
    with pytest.raises(ValueError, match="pose overlays"):
        docking.show_box(interactive=True, poses=registered_ligand)


def test_render_interactive_html_with_comm_round_trips_commit() -> None:
    """AnyWidget bridge forwards a commit to Python and acknowledges it."""
    displayed: list[Any] = []
    committed: list[dict[str, Any]] = []
    payload = {
        "center": [0.0, 0.0, 0.0],
        "box_size": [15.0, 15.0, 15.0],
        "rotation_deg": [0.0, -98.0, 0.0],
    }

    def _capture(obj: Any) -> None:
        displayed.append(obj)

    with (
        patch(
            "deeporigin.utils.iframe_comm_bridge.get_notebook_environment",
            return_value="jupyter",
        ),
        patch(
            "deeporigin.utils.iframe_comm_bridge.display",
            side_effect=_capture,
        ),
    ):
        handle = render_interactive_html_with_comm(
            lambda bridge_id: f"<html>bridge={bridge_id}</html>",
            on_commit=committed.append,
            height=500,
        )

    assert isinstance(handle, IframeCommHandle)
    assert handle.bridge_id
    assert displayed == [handle.widget]
    assert handle.widget.height == 500
    assert handle.widget.iframe_src.startswith("data:text/html")
    assert "model.send" in _WIDGET_ESM
    assert 'model.on("msg:custom"' in _WIDGET_ESM

    with patch.object(handle.widget, "send") as send:
        handle.widget._handle_custom_msg(
            {
                "type": DOCKING_BOX_COMMIT_MESSAGE_TYPE,
                "payload": payload,
            },
            [],
        )

    assert handle.committed == payload
    assert committed == [payload]
    send.assert_called_once_with(
        {
            "type": DOCKING_BOX_COMMIT_ACK_MESSAGE_TYPE,
            "bridge_id": handle.bridge_id,
            "payload": payload,
        }
    )


def test_render_interactive_docking_box_html_uses_get_docking_box(
    registered_protein,
    unregistered_pocket,
) -> None:
    """Interactive HTML uses molstar getDockingBox readback without prototype sliders."""
    from deeporigin.viz.molstar_html import render_interactive_docking_box_html

    protein_file = registered_protein._dump_state()
    html = render_interactive_docking_box_html(
        pdb_path=protein_file,
        box_center=[0.0, 0.0, 0.0],
        box_size=[15.0, 15.0, 15.0],
        bridge_id="bridge-123",
    )
    assert "getDockingBox" in html
    assert "proto-rot-x" not in html
    assert "Apply to notebook" in html
    assert "Applying rotation_deg=" in html
    assert "deeporigin:docking-box-commit-ack" in html
    assert Path(protein_file).is_file()
