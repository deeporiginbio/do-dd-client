"""Tests for interactive docking box SDK integration."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR
from deeporigin.drug_discovery.constrained_docking import ConstrainedDocking
from deeporigin.drug_discovery.docking import Docking
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.utils.iframe_comm_bridge import (
    _WIDGET_ESM,
    DOCKING_BOX_COMMIT_ACK_MESSAGE_TYPE,
    DOCKING_BOX_COMMIT_MESSAGE_TYPE,
    IframeCommHandle,
    render_interactive_html_with_comm,
)


def test_docking_commit_docking_box_stores_geometry_and_rotation(
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """_commit_docking_box stores committed geometry and normalized rotation."""
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
    assert docking.pocket.center == [0.0, 0.0, 0.0]
    assert docking.pocket.box_size_x == 15.0
    assert docking.pocket.box_size_y == 15.0
    assert docking.pocket.box_size_z == 15.0
    assert docking.rotation_deg == [0.0, 45.0, 0.0]


def test_docking_tool_inputs_forward_committed_geometry_and_rotation(
    client,
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """_build_tool_inputs includes committed geometry and rotation."""
    docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
        client=client,
    )
    docking._commit_docking_box(
        {
            "center": [1.0, 2.0, 3.0],
            "box_size": [16.0, 18.0, 20.0],
            "rotation_deg": [0.0, 30.0, 0.0],
        }
    )
    params, _ = docking._build_tool_inputs()
    assert params["pocket"]["center"] == [1.0, 2.0, 3.0]
    assert params["pocket"]["box_size_x"] == 16.0
    assert params["pocket"]["box_size_y"] == 18.0
    assert params["pocket"]["box_size_z"] == 20.0
    assert params["pocket"]["rotation_deg"] == [0.0, 30.0, 0.0]


def _pocket_with_box_fixture() -> Pocket:
    brd_pdb = Path(BRD_DATA_DIR) / "brd.pdb"
    return Pocket.from_json(
        [
            {
                "file_path": str(brd_pdb),
                "protein_id": "prot_1",
                "volume": 300.0,
                "pocket_center": [1.0, 2.0, 3.0],
                "box_size_x": 25.0,
                "box_size_y": 24.0,
                "box_size_z": 25.0,
                "box": {
                    "box_size_x": 22.0,
                    "box_size_y": 20.0,
                    "box_size_z": 21.0,
                    "rotation_deg": [5.0, 10.0, 15.0],
                },
            }
        ]
    )[0]


def test_session_rotation_overrides_inferred_on_tool_inputs(
    client,
    registered_protein,
    registered_ligand,
) -> None:
    """Committed session rotation wins over pocket.box inferred orientation."""
    docking = Docking(
        protein=registered_protein,
        pocket=_pocket_with_box_fixture(),
        ligand=registered_ligand,
        client=client,
    )
    docking._rotation_deg = [0.0, 45.0, 0.0]

    params, _ = docking._build_tool_inputs()

    assert params["pocket"]["rotation_deg"] == [0.0, 45.0, 0.0]


def test_commit_updates_nested_box_sizes(
    registered_protein,
    registered_ligand,
) -> None:
    """Interactive size commits sync nested pocket.box extents."""
    pocket = _pocket_with_box_fixture()
    docking = Docking(
        protein=registered_protein,
        pocket=pocket,
        ligand=registered_ligand,
    )
    docking._commit_docking_box(
        {
            "center": [1.0, 2.0, 3.0],
            "box_size": [18.0, 19.0, 20.0],
            "rotation_deg": [5.0, 10.0, 15.0],
        }
    )

    assert pocket.box is not None
    assert pocket.box.box_size_x == 18.0
    assert pocket.box.box_size_y == 19.0
    assert pocket.box.box_size_z == 20.0

    params, _ = docking._build_tool_inputs()
    assert params["pocket"]["box_size_x"] == 18.0
    assert params["pocket"]["box_size_y"] == 19.0
    assert params["pocket"]["box_size_z"] == 20.0


def test_identity_rotation_commit_overrides_inferred(
    client,
    registered_protein,
    registered_ligand,
) -> None:
    """Resetting rotation to identity suppresses pocket-finder inferred angle."""
    docking = Docking(
        protein=registered_protein,
        pocket=_pocket_with_box_fixture(),
        ligand=registered_ligand,
        client=client,
    )
    docking._commit_docking_box(
        {
            "center": [1.0, 2.0, 3.0],
            "box_size": [22.0, 20.0, 21.0],
            "rotation_deg": [0.0, 0.0, 0.0],
        }
    )

    assert docking.rotation_deg == [0.0, 0.0, 0.0]
    params, _ = docking._build_tool_inputs()
    assert "rotation_deg" not in params["pocket"]


def test_constrained_docking_uses_parent_aabb_for_nested_box(
    client,
    registered_protein,
    registered_ligand,
) -> None:
    """Constrained docking v1 uses lab-frame sizes when rotation is omitted."""
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
        pocket=_pocket_with_box_fixture(),
        reference_ligand=reference_ligand,
        reference_pose=reference_pose,
        ligands=[test_a, test_b],
        client=client,
    )

    params, _ = constrained._build_tool_inputs()

    assert params["pocket"]["box_size_x"] == 25.0
    assert params["pocket"]["box_size_y"] == 24.0
    assert params["pocket"]["box_size_z"] == 25.0
    assert "rotation_deg" not in params["pocket"]


def test_show_box_interactive_session_overrides_inferred_rotation(
    registered_protein,
    registered_ligand,
) -> None:
    """Interactive show_box uses session rotation instead of pocket.box default."""
    docking = Docking(
        protein=registered_protein,
        pocket=_pocket_with_box_fixture(),
        ligand=registered_ligand,
    )
    docking._rotation_deg = [0.0, 45.0, 0.0]
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
        patch(
            "deeporigin.viz.molstar_html.render_interactive_docking_box_html",
            return_value="<html></html>",
        ) as mock_html,
    ):
        docking.show_box(interactive=True)
        html_builder = mock_bridge.call_args.args[0]
        html_builder("bridge-id")

    assert mock_html.call_args.kwargs["rotation_deg"] == [0.0, 45.0, 0.0]


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


def test_show_box_interactive_forwards_session_rotation(
    registered_protein,
    unregistered_pocket,
    registered_ligand,
) -> None:
    """interactive show_box hydrates HTML with session rotation used by run()."""
    docking = Docking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        ligand=registered_ligand,
    )
    docking._rotation_deg = [0.0, 45.0, 0.0]
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
        patch(
            "deeporigin.viz.molstar_html.render_interactive_docking_box_html",
            return_value="<html></html>",
        ) as mock_html,
    ):
        docking.show_box(interactive=True)
        html_builder = mock_bridge.call_args.args[0]
        html_builder("bridge-id")

    assert mock_html.call_args.kwargs["rotation_used_by_run"] is True
    assert mock_html.call_args.kwargs["rotation_deg"] == [0.0, 45.0, 0.0]


def test_constrained_show_box_interactive_is_visualization_only(
    registered_protein,
    unregistered_pocket,
) -> None:
    """ConstrainedDocking interactive overlay is visualization-only."""
    from tests.test_constrained_docking import _make_reference_pair

    reference_ligand, reference_pose = _make_reference_pair()
    reference_ligand.remote_path = "testing/brd-2.sdf"
    reference_ligand.id = "brd-2"
    reference_pose.remote_path = "testing/docked-pose.sdf"
    reference_pose.id = "brd-2-pose"

    constrained = ConstrainedDocking(
        protein=registered_protein,
        pocket=unregistered_pocket,
        reference_ligand=reference_ligand,
        reference_pose=reference_pose,
        ligand=Ligand.from_smiles("CCO"),
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
        patch(
            "deeporigin.viz.molstar_html.render_interactive_docking_box_html",
            return_value="<html></html>",
        ) as mock_html,
    ):
        constrained.show_box(interactive=True)
        html_builder = mock_bridge.call_args.args[0]
        html_builder("bridge-id")

    assert mock_html.call_args.kwargs["rotation_used_by_run"] is False


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
) -> None:
    """Interactive HTML commits geometry on molstar gesture-end."""
    from deeporigin.viz.molstar_html import render_interactive_docking_box_html

    protein_file = registered_protein._dump_state()
    html = render_interactive_docking_box_html(
        pdb_path=protein_file,
        box_center=[0.0, 0.0, 0.0],
        box_size=[15.0, 15.0, 15.0],
        bridge_id="bridge-123",
        rotation_deg=[0.0, 45.0, 0.0],
    )
    assert "getDockingBox" in html
    assert "onDockingBoxChange" in html
    assert "applyDockingBoxRotation" in html
    assert "setRotation" in html
    assert "proto-rot-x" not in html
    assert "Apply to notebook" not in html
    assert "do-box-apply" not in html
    assert "Syncing box geometry..." in html
    assert "Synced box geometry:" in html
    assert "Visualization only" not in html
    assert "do-box-hint" not in html
    assert "Session rotation syncs" not in html
    assert "rgba(20, 24, 32, 0.92)" not in html
    assert "calc(100vh" not in html
    assert "deeporigin:docking-box-commit-ack" in html
    assert Path(protein_file).is_file()


def test_render_interactive_docking_box_html_constrained_warns(
    registered_protein,
) -> None:
    """Constrained overlay warns that run() ignores rotation."""
    from deeporigin.viz.molstar_html import render_interactive_docking_box_html

    protein_file = registered_protein._dump_state()
    html = render_interactive_docking_box_html(
        pdb_path=protein_file,
        box_center=[0.0, 0.0, 0.0],
        box_size=[15.0, 15.0, 15.0],
        bridge_id="bridge-123",
        rotation_used_by_run=False,
    )
    assert "Visualization only" in html
    assert "ConstrainedDocking.run() ignores rotation" in html
    assert "Apply to notebook" not in html
