"""Tests for :class:`~deeporigin.drug_discovery.konnektor.Konnektor`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from deeporigin.drug_discovery import Konnektor, KonnektorResult, Pose
from deeporigin.drug_discovery.konnektor import _konnektor_result_from_dto
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient


def _pose(n: int) -> Pose:
    """Registered pose stub with platform id and remote path."""
    return Pose(
        ligand_id=f"lig-{n}",
        id=f"pose-{n}",
        remote_path=f"poses/pose-{n}.sdf",
    )


def test_konnektor_requires_two_poses(client: DeepOriginClient) -> None:
    """Konnektor rejects a single pose."""
    with pytest.raises(ValueError, match="at least two poses"):
        Konnektor(poses=[_pose(1)], client=client)


def test_konnektor_make_payload_sends_pose_refs(client: DeepOriginClient) -> None:
    """Payload rows are ``{id, file_path}`` Pose references."""
    job = Konnektor(
        poses=[_pose(1), _pose(2)],
        network_type="star",
        client=client,
        name="test network",
    )

    payload = job._make_payload(approve_amount=5, sync=True)

    assert payload["inputs"] == {
        "poses": [
            {"id": "pose-1", "file_path": "poses/pose-1.sdf"},
            {"id": "pose-2", "file_path": "poses/pose-2.sdf"},
        ],
        "network_type": "star",
    }
    assert payload["name"] == "test network"
    assert payload["sync"] is True
    assert payload["approveAmount"] == 5


def _konnektor_v05_dto(
    *,
    edges: list[dict[str, str]],
    is_connected: bool = True,
    network_html: str = "<html><body>network</body></html>",
) -> dict[str, object]:
    """Build a v0.5 Konnektor execution DTO for unit tests."""
    return {
        "jobOutputs": {
            "ligand_network": {
                "edges": edges,
                "is_connected": is_connected,
                "network": {},
                "network_html_file": "tool-runs/test/network.html",
            },
            "network_html": network_html,
        }
    }


def test_konnektor_result_from_dto_resolves_pose_pairs() -> None:
    """Edges name Pose ids and resolve to the input poses."""
    p1, p2 = _pose(1), _pose(2)
    dto = _konnektor_v05_dto(edges=[{"source": "pose-1", "target": "pose-2"}])

    result = _konnektor_result_from_dto(dto, poses=[p1, p2])

    assert isinstance(result, KonnektorResult)
    assert result.pairs == [(p1, p2)]
    assert result.is_connected is True
    assert result.network_html == "<html><body>network</body></html>"


def test_konnektor_result_from_dto_rejects_unknown_pose() -> None:
    """An edge naming a pose that was not sent is an error."""
    dto = _konnektor_v05_dto(edges=[{"source": "pose-1", "target": "pose-9"}])

    with pytest.raises(DeepOriginException, match="pose-9"):
        _konnektor_result_from_dto(dto, poses=[_pose(1), _pose(2)])


def test_konnektor_result_from_dto_rejects_flat_edges() -> None:
    """Flat ``jobOutputs.edges`` (v0.4) is rejected."""
    dto = {
        "jobOutputs": {
            "edges": [{"source": "pose-1", "target": "pose-2"}],
            "is_connected": True,
            "network": {},
        }
    }

    with pytest.raises(DeepOriginException, match="ligand_network"):
        _konnektor_result_from_dto(dto, poses=[_pose(1), _pose(2)])


def test_konnektor_run_returns_konnektor_result(client: DeepOriginClient) -> None:
    """``run`` returns pose pairs suitable for RBFE ``pairs``."""
    if client.env != "local":
        pytest.skip("Konnektor run integration requires the local mock server.")

    p1, p2 = _pose(1), _pose(2)
    job = Konnektor(poses=[p1, p2], client=client)
    result = job.run()

    assert isinstance(result, KonnektorResult)
    assert result.pairs == [(p1, p2)]
    assert result.is_connected is True
    assert result.network_html
    assert job.status == "Completed"
    assert job.id is not None


def test_konnektor_run_quote_returns_none(client: DeepOriginClient) -> None:
    """``quote=True`` requests a quotation and does not extract edges."""
    if client.env != "local":
        pytest.skip("Konnektor run integration requires the local mock server.")

    job = Konnektor(poses=[_pose(1), _pose(2)], client=client)

    assert job.run(quote=True) is None
    assert job.status == "Quoted"
    assert job.estimate == 1.23


def test_konnektor_show_network_uses_sandboxed_render_html(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """show_network embeds via render_html and does not write network.html to CWD."""
    monkeypatch.chdir(tmp_path)
    result = KonnektorResult(
        pairs=[],
        is_connected=True,
        network_html="<html><body>Konnektor network</body></html>",
    )
    with patch(
        "deeporigin.utils.notebook.render_html",
        return_value=None,
    ) as mock_render:
        result.show_network()

    mock_render.assert_called_once_with(result.network_html, height=1000)
    assert not (tmp_path / "network.html").exists()
