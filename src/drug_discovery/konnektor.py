"""Synchronous pose network generation with the Konnektor platform tool."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from beartype import beartype

from deeporigin.drug_discovery.execution import Execution, _default_execution_payload
from deeporigin.drug_discovery.execution_mixins import SyncExecutableMixin
from deeporigin.drug_discovery.fep_common import _pose_tool_ref
from deeporigin.drug_discovery.structures.pose import Pose, PoseSet
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status
from deeporigin.utils.constants import QUOTE_APPROVE_AMOUNT

KonnektorNetworkType = Literal["star", "mst", "cyclic"]


@dataclass(frozen=True)
class KonnektorResult:
    """Result of a successful Konnektor synchronous run.

    Attributes:
        pairs: Resolved pose pairs from the planned network edges.
        is_connected: Whether the generated network is fully connected.
        network_html: Inline interactive network visualization HTML.
    """

    pairs: list[tuple[Pose, Pose]]
    is_connected: bool
    network_html: str

    def show_network(self) -> Any:
        """Display the network visualization in IPython.

        Embeds ``network_html`` in a sandboxed iframe (same helper as Mol*
        views) so server-supplied markup cannot write to the working directory
        or run with the notebook page origin.
        """
        from deeporigin.utils.notebook import render_html

        try:
            return render_html(self.network_html, height=1000)
        except Exception as exc:
            raise DeepOriginException(
                title="Failed to display Konnektor network",
                message=str(exc),
            ) from exc


def _execution_outputs_dict(dto: dict[str, Any]) -> dict[str, Any]:
    """Return ``jobOutputs`` from a Konnektor execution DTO as a dict."""
    outputs = dto.get("jobOutputs")
    if isinstance(outputs, dict):
        return outputs
    if isinstance(outputs, list) and outputs and isinstance(outputs[0], dict):
        return outputs[0]
    return {}


def _resolve_pose_endpoint(
    *,
    pose_id: str,
    lookup: dict[str, Pose],
    edge_idx: int,
    role: str,
) -> Pose:
    """Resolve one Konnektor edge endpoint to an input pose."""
    pose = lookup.get(pose_id)
    if pose is None:
        raise DeepOriginException(
            title="Unknown Konnektor edge endpoint",
            message=(
                f"Edge {edge_idx} {role} {pose_id!r} does not match any input pose."
            ),
        ) from None
    return pose


def _konnektor_pairs_from_edges(
    edges: list[Any],
    *,
    poses: list[Pose],
) -> list[tuple[Pose, Pose]]:
    """Resolve Konnektor edge dicts (Pose ids) to pose pairs."""
    lookup = {str(pose.id): pose for pose in poses}
    out: list[tuple[Pose, Pose]] = []
    for idx, edge in enumerate(edges):
        if not isinstance(edge, dict):
            raise DeepOriginException(
                title="Invalid Konnektor edge",
                message=f"Expected edge {idx} to be a dict, got {type(edge).__name__}.",
            ) from None
        source = edge.get("source")
        target = edge.get("target")
        if not isinstance(source, str) or not isinstance(target, str):
            raise DeepOriginException(
                title="Invalid Konnektor edge",
                message=f"Expected edge {idx} to contain string source and target.",
            ) from None
        out.append(
            (
                _resolve_pose_endpoint(
                    pose_id=source, lookup=lookup, edge_idx=idx, role="source"
                ),
                _resolve_pose_endpoint(
                    pose_id=target, lookup=lookup, edge_idx=idx, role="target"
                ),
            )
        )
    return out


def _konnektor_result_from_dto(
    dto: dict[str, Any],
    *,
    poses: list[Pose],
) -> KonnektorResult:
    """Extract a :class:`KonnektorResult` from a v0.5+ execution DTO."""
    outputs = _execution_outputs_dict(dto)
    ligand_network = outputs.get("ligand_network")
    if not isinstance(ligand_network, dict):
        raise DeepOriginException(
            title="Konnektor response missing ligand_network",
            message="Expected jobOutputs.ligand_network to be a dict.",
        ) from None

    edges = ligand_network.get("edges")
    if not isinstance(edges, list):
        raise DeepOriginException(
            title="Konnektor response missing edges",
            message="Expected jobOutputs.ligand_network.edges to be a list.",
        ) from None

    is_connected = ligand_network.get("is_connected")
    if not isinstance(is_connected, bool):
        raise DeepOriginException(
            title="Konnektor response missing is_connected",
            message="Expected jobOutputs.ligand_network.is_connected to be a bool.",
        ) from None

    network_html = outputs.get("network_html")
    if not isinstance(network_html, str) or not network_html:
        raise DeepOriginException(
            title="Konnektor response missing network_html",
            message="Expected jobOutputs.network_html to be a non-empty string.",
        ) from None

    pairs = _konnektor_pairs_from_edges(edges, poses=poses)
    return KonnektorResult(
        pairs=pairs,
        is_connected=is_connected,
        network_html=network_html,
    )


class Konnektor(Execution, SyncExecutableMixin):
    """Plan an RBFE network over poses with Konnektor and return a :class:`KonnektorResult`.

    Konnektor accepts at least two poses, one per ligand. The synchronous
    :meth:`run` method returns resolved pose pairs, connectivity, and inline
    visualization HTML; pass ``result.pairs`` to
    :class:`~deeporigin.drug_discovery.rbfe.RBFE` as ``pairs``.

    Attributes:
        poses: Poses to connect.
        network_type: Network topology planner, one of ``"star"``, ``"mst"``,
            or ``"cyclic"``. Defaults to ``"mst"``.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["konnektor"]["tool_key"]

    @beartype
    def __init__(
        self,
        *,
        poses: list[Pose] | PoseSet,
        network_type: KonnektorNetworkType = "mst",
        tool_version: str = TOOL_KEYS_AND_VERSIONS["konnektor"]["tool_version"],
        client: DeepOriginClient | None = None,
        name: str | None = None,
    ) -> None:
        """Create a Konnektor execution wrapper.

        Args:
            poses: At least two poses, one per ligand (for example docked poses).
                Unregistered poses are registered during :meth:`run`.
            network_type: Network topology planner, one of ``"star"``, ``"mst"``,
                or ``"cyclic"``. Defaults to ``"mst"`` so the simplest
                ``Konnektor(poses=...)`` call works with two or more poses.
            tool_version: Platform tool version to execute.
            client: Optional API client.
            name: Optional execution label.

        Raises:
            ValueError: If fewer than two poses are provided.
        """
        super().__init__(client=client)
        self._poses = list(poses)
        if len(self._poses) < 2:
            raise ValueError("Konnektor requires at least two poses.")

        self._network_type = network_type
        self.tool_version = tool_version
        self.name = name

    @property
    def poses(self) -> list[Pose]:
        """Poses to connect."""
        return self._poses

    @property
    def network_type(self) -> KonnektorNetworkType:
        """Network topology planner."""
        return self._network_type

    def _ensure_platform_inputs(self) -> None:
        """Sync poses so each has a platform id and remote SDF path."""
        for pose in self.poses:
            pose.sync(lazy=True, client=self.client)
            pose.ensure_remote_path(client=self.client, label="Pose")

    def _make_inputs(self) -> dict[str, Any]:
        """Build Konnektor tool inputs from synced poses."""
        return {
            "poses": [_pose_tool_ref(pose) for pose in self.poses],
            "network_type": self.network_type,
        }

    def _make_payload(
        self,
        *,
        approve_amount: int | None,
        sync: bool,
    ) -> dict[str, Any]:
        """Build the body dict for ``client.executions.create``."""
        return _default_execution_payload(
            self._make_inputs(),
            name=self.name,
            approve_amount=approve_amount,
            sync=sync,
        )

    def run(
        self,
        *,
        quote: bool = False,
        approve_amount: int | None = None,
    ) -> KonnektorResult | None:
        """Run Konnektor synchronously and return the network result.

        Args:
            quote: Shorthand for ``approve_amount=-1``. Returns ``None`` when the
                platform returns a quotation.
            approve_amount: Spend cap forwarded to the platform as ``approveAmount``.

        Returns:
            A :class:`KonnektorResult`, or ``None`` for quote-only responses.

        Raises:
            DeepOriginException: If the execution does not succeed or the response
                does not contain a valid v0.5 ``ligand_network`` output.
        """
        self._ensure_platform_inputs()
        resolved_amount = QUOTE_APPROVE_AMOUNT if quote else approve_amount
        response = self._create_execution(
            data=self._make_payload(approve_amount=resolved_amount, sync=not quote),
        )
        self.update_from_dto(response)

        if self.status == "Quoted":
            return None

        final_status = response.get("status")
        if not is_success_status(final_status):
            eid = response.get("executionId")
            reason = response.get("statusReason") or final_status
            raise DeepOriginException(
                title="Konnektor run did not succeed",
                message=(
                    f"Execution {eid!r} ended with status {final_status!r}: {reason!r}."
                ),
            ) from None

        return _konnektor_result_from_dto(response, poses=self.poses)
