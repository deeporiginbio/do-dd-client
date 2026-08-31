"""Synchronous ligand network generation with the Konnektor platform tool."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from beartype import beartype

from deeporigin.drug_discovery.execution import Execution, _default_execution_payload
from deeporigin.drug_discovery.execution_mixins import SyncExecutableMixin
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status

KonnektorNetworkType = Literal["star", "mst", "cyclic"]


@dataclass(frozen=True)
class KonnektorResult:
    """Result of a successful Konnektor synchronous run.

    Attributes:
        pairs: Resolved ligand pairs from the planned network edges.
        is_connected: Whether the generated network is fully connected.
        network_html: Inline interactive network visualization HTML.
    """

    pairs: list[tuple[Ligand, Ligand]]
    is_connected: bool
    network_html: str

    def show_network(self) -> None:
        """Display the network visualization in IPython."""
        from IPython.display import IFrame, display

        file_name = "network.html"
        try:
            with open(file_name, "w", encoding="utf-8") as file:
                file.write(self.network_html)
            display(IFrame(file_name, width=1000, height=1000))
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


def _ligand_display_name(ligand: Ligand, index: int) -> str:
    """Stable component name matching the Konnektor platform tool."""
    if ligand.id is not None:
        lid = str(ligand.id).strip()
        if lid:
            return lid
    if ligand.remote_path is not None:
        stem = Path(ligand.remote_path).stem.strip()
        if stem:
            return stem
    return f"ligand_{index + 1}"


def _ligand_lookup(ligands: LigandSet) -> dict[str, Ligand]:
    """Map Konnektor edge endpoint names to :class:`Ligand` instances."""
    lookup: dict[str, Ligand] = {}
    for index, ligand in enumerate(ligands):
        lookup[_ligand_display_name(ligand, index)] = ligand
    return lookup


def _resolve_ligand_endpoint(
    *,
    name: str,
    lookup: dict[str, Ligand],
    edge_idx: int,
    role: str,
) -> Ligand:
    """Resolve one Konnektor edge endpoint to an input ligand."""
    ligand = lookup.get(name)
    if ligand is None:
        raise DeepOriginException(
            title="Unknown Konnektor edge endpoint",
            message=(
                f"Edge {edge_idx} {role} {name!r} does not match any input ligand."
            ),
        ) from None
    return ligand


def _konnektor_pairs_from_edges(
    edges: list[Any],
    *,
    ligands: LigandSet,
) -> list[tuple[Ligand, Ligand]]:
    """Resolve Konnektor edge dicts to ligand pairs."""
    lookup = _ligand_lookup(ligands)
    out: list[tuple[Ligand, Ligand]] = []
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
                _resolve_ligand_endpoint(
                    name=source,
                    lookup=lookup,
                    edge_idx=idx,
                    role="source",
                ),
                _resolve_ligand_endpoint(
                    name=target,
                    lookup=lookup,
                    edge_idx=idx,
                    role="target",
                ),
            )
        )
    return out


def _konnektor_result_from_dto(
    dto: dict[str, Any],
    *,
    ligands: LigandSet,
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

    pairs = _konnektor_pairs_from_edges(edges, ligands=ligands)
    return KonnektorResult(
        pairs=pairs,
        is_connected=is_connected,
        network_html=network_html,
    )


def _ligand_tool_input_row(ligand: Ligand) -> dict[str, str]:
    """Build one ligand entry for the Konnektor ``ligands`` input array."""
    row: dict[str, str] = {}
    if ligand.remote_path is not None:
        row["file_path"] = ligand.remote_path
    if ligand.id is not None:
        row["id"] = ligand.id
    if ligand.smiles:
        row["smiles"] = ligand.smiles
    if "file_path" not in row and "id" not in row:
        raise ValueError(
            "Each Konnektor ligand must have a platform id or remote file path. "
            "Call ligand.sync() or ligand.upload() first."
        )
    return row


class Konnektor(Execution, SyncExecutableMixin):
    """Generate a ligand network with Konnektor and return a :class:`KonnektorResult`.

    Konnektor accepts at least two ligands. Each ligand is synced before execution
    so the platform can receive either a ligand entity ID or a remote SDF path.
    The synchronous :meth:`run` method returns resolved ligand pairs, connectivity,
    and inline visualization HTML suitable for :class:`~deeporigin.drug_discovery.rbfe.RBFE`.

    Attributes:
        ligands: Ligands to connect.
        network_type: Network topology planner, one of ``"star"``, ``"mst"``,
            or ``"cyclic"``. Defaults to ``"mst"``.
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["konnektor"]["tool_key"]

    @beartype
    def __init__(
        self,
        *,
        ligands: list[Ligand] | LigandSet,
        network_type: KonnektorNetworkType = "mst",
        tool_version: str = TOOL_KEYS_AND_VERSIONS["konnektor"]["tool_version"],
        client: DeepOriginClient | None = None,
        name: str | None = None,
    ) -> None:
        """Create a Konnektor execution wrapper.

        Args:
            ligands: At least two ligands. Local SDF-backed ligands are uploaded
                during :meth:`run`; registered ligands can be passed directly.
            network_type: Network topology planner, one of ``"star"``, ``"mst"``,
                or ``"cyclic"``. Defaults to ``"mst"`` so the simplest
                ``Konnektor(ligands=...)`` call works with two or more ligands.
            tool_version: Platform tool version to execute.
            client: Optional API client.
            name: Optional execution label.

        Raises:
            ValueError: If fewer than two ligands are provided.
        """
        super().__init__(client=client)
        if isinstance(ligands, LigandSet):
            self._ligands = ligands
        else:
            self._ligands = LigandSet(ligands=list(ligands))
        if len(self._ligands) < 2:
            raise ValueError("Konnektor requires at least two ligands.")

        self._network_type = network_type
        self.tool_version = tool_version
        self.name = name

    @property
    def ligands(self) -> LigandSet:
        """Ligands to connect."""
        return self._ligands

    @property
    def network_type(self) -> KonnektorNetworkType:
        """Network topology planner."""
        return self._network_type

    def _ensure_platform_inputs(self) -> None:
        """Sync ligands so Konnektor can resolve platform IDs or SDF paths."""
        for ligand in self.ligands:
            ligand.sync(lazy=True, client=self.client)

    def _make_inputs(self) -> dict[str, Any]:
        """Build Konnektor tool inputs from synced ligands."""
        return {
            "ligands": [_ligand_tool_input_row(ligand) for ligand in self.ligands],
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
            quote: Shorthand for ``approve_amount=0``. Returns ``None`` when the
                platform returns a quotation.
            approve_amount: Spend cap forwarded to the platform as ``approveAmount``.

        Returns:
            A :class:`KonnektorResult`, or ``None`` for quote-only responses.

        Raises:
            DeepOriginException: If the execution does not succeed or the response
                does not contain a valid v0.5 ``ligand_network`` output.
        """
        self._ensure_platform_inputs()
        resolved_amount = 0 if quote else approve_amount
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

        return _konnektor_result_from_dto(response, ligands=self.ligands)
