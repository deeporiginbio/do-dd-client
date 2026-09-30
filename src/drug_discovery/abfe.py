"""ABFE -- class to run and control absolute binding free energy calculations."""

from __future__ import annotations

from pathlib import Path
import posixpath
import struct
from typing import Any, Literal, Self
import xml.etree.ElementTree as ET

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import AsyncExecutableMixin
from deeporigin.drug_discovery.fep_common import (
    ABFEParams,
    _fep_params_from_inputs,
    _pose_tool_ref,
    _prepared_system_tool_ref,
    _protein_from_tool_input,
    _simulation_blocks,
)
from deeporigin.drug_discovery.notebook_watch_mixin import NotebookWatchMixin
from deeporigin.drug_discovery.structures.pose import Pose
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status

ABFEWorkflowStep = Literal["system-prep", "abfe"]


@beartype
def _protein_display_name_from_entity(*, entity: dict, fallback_id: str) -> str:
    """Resolve a display label from a protein entity record.

    Preference order matches :meth:`deeporigin.drug_discovery.structures.protein.Protein.from_id`.

    Args:
        entity: Raw protein dict from ``client.entities.get_protein``.
        fallback_id: Value to use when no suitable name field is present.

    Returns:
        Non-empty display string for the protein.
    """
    for key in ("protein_name", "pdb_id", "gene_symbol"):
        value = entity.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return fallback_id


@beartype
def _ligand_display_label_from_entity(*, entity: dict, fallback_id: str) -> str:
    """Resolve ligand label: name when set, otherwise canonical or input SMILES.

    Args:
        entity: Raw ligand dict from ``client.entities.get_ligand``.
        fallback_id: Value to use when no name or SMILES is present.

    Returns:
        Non-empty display string for the ligand.
    """
    name = entity.get("name")
    if name is not None and str(name).strip():
        return str(name).strip()
    smiles = entity.get("canonical_smiles") or entity.get("smiles")
    if smiles is not None and str(smiles).strip():
        return str(smiles).strip()
    return fallback_id


@beartype
def _abfe_default_name_from_entities(
    *,
    protein: Protein,
    pose: Pose,
    client: DeepOriginClient,
) -> str:
    """Build a short human-readable label for a combined ABFE execution.

    Args:
        protein: Protein used for system preparation.
        pose: Pose used for system preparation.
        client: API client used to resolve entities.

    Returns:
        A string such as ``ABFE: BRD4 with CCO``.
    """
    protein_id = protein.id
    ligand_id = pose.ligand_id
    protein_id_str = (
        str(protein_id).strip()
        if protein_id is not None and str(protein_id).strip()
        else ""
    )
    ligand_id_str = (
        str(ligand_id).strip() if ligand_id and str(ligand_id).strip() else ""
    )

    if protein_id_str:
        try:
            protein_label = _protein_display_name_from_entity(
                entity=client.entities.get_protein(id=protein_id_str),
                fallback_id=protein_id_str,
            )
        except Exception:
            protein_label = protein_id_str
    else:
        protein_label = protein.name or "unknown protein"

    if ligand_id_str:
        try:
            ligand_label = _ligand_display_label_from_entity(
                entity=client.entities.get_ligand(id=ligand_id_str),
                fallback_id=ligand_id_str,
            )
        except Exception:
            ligand_label = ligand_id_str
    else:
        ligand_label = pose.name or pose.smiles or pose.id or "unknown pose"

    return f"ABFE: {protein_label} with {ligand_label}"


@beartype
def _abfe_first_remote_trajectory_path(*, data: dict[str, Any]) -> str:
    """Return any remote trajectory path string from ABFE result ``data``."""
    for analysis_key in ("binding_analysis", "solvation_analysis"):
        blocks = data.get(analysis_key)
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            traj = block.get("trajectories")
            if not isinstance(traj, dict) or not traj:
                continue
            for value in traj.values():
                if isinstance(value, str) and value.strip():
                    return value.strip()
    raise DeepOriginException(
        title="No trajectory metadata in results",
        message="Results do not include binding or solvation trajectory paths yet.",
        fix="Wait for the job to finish and ensure the tool version records trajectories.",
    ) from None


@beartype
def _abfe_tool_run_root(*, remote_trajectory_path: str) -> str:
    """Return ``tool-runs/<uuid>`` prefix parsed from a trajectory remote path."""
    parts = remote_trajectory_path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "tool-runs":
        return f"{parts[0]}/{parts[1]}"
    raise DeepOriginException(
        title="Invalid trajectory path",
        message=f"Could not locate tool-runs root in {remote_trajectory_path!r}.",
        fix="Report this path to support if the job completed successfully.",
    ) from None


@beartype
def _abfe_remote_system_pdb_path(data: dict[str, Any]) -> str | None:
    """Return the remote system PDB path from merged ABFE / system-prep result ``data``."""
    pdb = data.get("system_pdb_file_path")
    if isinstance(pdb, str) and pdb.strip():
        return pdb.strip()
    binding_xml = data.get("binding_xml_file_path")
    if isinstance(binding_xml, str) and binding_xml.strip():
        return posixpath.join(
            posixpath.dirname(binding_xml.strip()),
            "system.pdb",
        )
    return None


@beartype
def _abfe_remote_system_pdb_path_from_prepared_system(
    prepared: PreparedSystem,
) -> str | None:
    """Return system PDB remote path from a :class:`PreparedSystem` (no API calls)."""
    if prepared.system_pdb_path and prepared.system_pdb_path.strip():
        return prepared.system_pdb_path.strip()
    if prepared.binding_xml_path and prepared.binding_xml_path.strip():
        return posixpath.join(
            posixpath.dirname(prepared.binding_xml_path.strip()),
            "system.pdb",
        )
    return None


@beartype
def _abfe_remote_trajectory_topology_path(
    data: dict[str, Any],
    *,
    step: Literal["md", "binding", "solvation"],
) -> str | None:
    """Return a topology whose atom count matches the selected trajectory."""
    if step == "binding":
        solute = data.get("solute_pdb_file_path")
        if isinstance(solute, str) and solute.strip():
            return solute.strip()
    if step == "solvation":
        solvation_xml = data.get("solvation_xml_ligand_file_path")
        if isinstance(solvation_xml, str) and solvation_xml.strip():
            return solvation_xml.strip()
    return _abfe_remote_system_pdb_path(data)


@beartype
def _abfe_remote_trajectory_topology_path_from_prepared_system(
    prepared: PreparedSystem,
    *,
    step: Literal["md", "binding", "solvation"],
) -> str | None:
    """Return a matching trajectory topology from prepared-system metadata."""
    if (
        step == "binding"
        and prepared.solute_pdb_path
        and prepared.solute_pdb_path.strip()
    ):
        return prepared.solute_pdb_path.strip()
    if (
        step == "solvation"
        and prepared.solvation_xml_path
        and prepared.solvation_xml_path.strip()
    ):
        return prepared.solvation_xml_path.strip()
    return _abfe_remote_system_pdb_path_from_prepared_system(prepared)


_PDB_SOLVENT_RESIDUE_NAMES = frozenset({"HOH", "SOL", "TIP3", "TIP3P", "WAT"})
_PDB_COORDINATE_RECORD_PREFIXES = ("ATOM  ", "HETATM")

_ELEMENT_SYMBOL_BY_ATOMIC_NUMBER: dict[int, str] = {
    1: "H",
    6: "C",
    7: "N",
    8: "O",
    9: "F",
    11: "Na",
    12: "Mg",
    15: "P",
    16: "S",
    17: "Cl",
    35: "Br",
    53: "I",
}


@beartype
def _abfe_element_symbol(atomic_number: int) -> str:
    return _ELEMENT_SYMBOL_BY_ATOMIC_NUMBER.get(atomic_number, "X")


_NM_TO_ANGSTROM = 10.0


def _systemprep_xml_root(path: Path) -> ET.Element:
    """Parse a SystemPrep XML file without resolving external entities."""
    parser = ET.XMLParser()
    if hasattr(parser, "resolve_entities"):
        parser.resolve_entities = False
    return ET.parse(path, parser=parser).getroot()


def _systemprep_pdb_chain_id(chain_index: int) -> str:
    """Map a 1-based SystemPrep chain index to a single-character PDB chain id."""
    return chr(ord("A") + min(max(chain_index, 1) - 1, 25))


@beartype
def _abfe_systemprep_xml_to_pdb(
    xml_path: str,
    *,
    exclude_solvent: bool = True,
    chain_types: frozenset[str] | None = None,
) -> str:
    """Write a PDB from a SystemPrep ``solvation_ligand`` / BSM XML file.

    Solvation FEP ``solute_trajectory`` files contain ligand atoms only (no
    counterions or explicit solvent). Pass ``chain_types=frozenset({"Ligand"})``
    to match those trajectories. Binding trajectories use ``solute.pdb`` instead.
    """
    path = Path(xml_path)
    root = _systemprep_xml_root(path)
    entries: list[tuple[int, str, str, str, int, float, float, float, str]] = []
    for chain in root.findall("./Chains/Chain"):
        chain_type = (chain.get("chain_type") or "").strip()
        if chain_types is not None and chain_type not in chain_types:
            continue
        chain_index_raw = (chain.get("chain_index") or "1").strip()
        chain_index = int(chain_index_raw) if chain_index_raw.isdigit() else 1
        chain_id = _systemprep_pdb_chain_id(chain_index)
        residue_serial = 0
        for residue in chain.findall("Residues/Residue"):
            residue_name = (residue.get("residue_name") or "UNK").strip()
            if exclude_solvent and residue_name.upper() in _PDB_SOLVENT_RESIDUE_NAMES:
                continue
            residue_serial += 1
            for atom in residue.findall("Atoms/Atom"):
                index_raw = atom.get("atom_index")
                if index_raw is None or not index_raw.isdigit():
                    continue
                atom_name = (atom.get("atom_name") or "X").strip()[:4]
                element_number = int(atom.get("atom_element_number") or "0")
                element = _abfe_element_symbol(element_number)
                x = float(atom.get("atom_position_x") or "0") * _NM_TO_ANGSTROM
                y = float(atom.get("atom_position_y") or "0") * _NM_TO_ANGSTROM
                z = float(atom.get("atom_position_z") or "0") * _NM_TO_ANGSTROM
                entries.append(
                    (
                        int(index_raw),
                        atom_name,
                        residue_name,
                        chain_id,
                        residue_serial,
                        x,
                        y,
                        z,
                        element,
                    )
                )

    if not entries:
        raise DeepOriginException(
            title="Empty solvation topology",
            message=f"No atoms found in SystemPrep XML {xml_path!r}.",
        ) from None

    entries.sort(key=lambda item: item[0])
    lines: list[str] = []
    for serial, (
        _index,
        atom_name,
        residue_name,
        chain_id,
        residue_serial,
        x,
        y,
        z,
        element,
    ) in enumerate(entries, start=1):
        record = "HETATM"
        resname = residue_name[:3].rjust(3)
        lines.append(
            f"{record}{serial:5d} {atom_name:>4s} {resname:>3s} {chain_id}{residue_serial:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {element:>2s}\n"
        )
    lines.append("END\n")
    suffix = "ligand" if chain_types == frozenset({"Ligand"}) else "solute"
    out_path = path.with_name(f"{path.stem}.{suffix}.pdb")
    out_path.write_text("".join(lines), encoding="utf-8")
    return str(out_path)


@beartype
def _abfe_local_trajectory_topology_path(
    local_path: str,
    *,
    step: Literal["md", "binding", "solvation"],
) -> str:
    """Return a local PDB path for Mol*, converting SystemPrep XML when needed."""
    path = Path(local_path)
    if path.suffix.lower() == ".xml":
        chain_types = frozenset({"Ligand"}) if step == "solvation" else None
        return _abfe_systemprep_xml_to_pdb(
            str(path),
            exclude_solvent=True,
            chain_types=chain_types,
        )
    return local_path


@beartype
def _abfe_xtc_atom_count(trajectory_path: str) -> int:
    """Read the atom count from an XTC file header."""
    with Path(trajectory_path).open("rb") as handle:
        header = handle.read(8)
    if len(header) != 8:
        raise DeepOriginException(
            title="Invalid XTC trajectory",
            message=f"Trajectory file is too short: {trajectory_path}",
        ) from None
    magic, trajectory_atoms = struct.unpack(">ii", header)
    if magic != 1995 or trajectory_atoms <= 0:
        raise DeepOriginException(
            title="Invalid XTC trajectory",
            message=f"Cannot read atom count from trajectory: {trajectory_path}",
        ) from None
    return trajectory_atoms


def _abfe_pdb_without_solvent(
    lines: list[str],
) -> tuple[list[str], set[int]]:
    """Remove solvent coordinates and their CONECT records from PDB lines."""
    removed_serials: set[int] = set()
    filtered: list[str] = []
    for line in lines:
        if line.startswith(_PDB_COORDINATE_RECORD_PREFIXES):
            residue_name = line[17:20].strip().upper()
            if residue_name in _PDB_SOLVENT_RESIDUE_NAMES:
                try:
                    removed_serials.add(int(line[6:11]))
                except ValueError:
                    pass
                continue
        filtered.append(line)

    if not removed_serials:
        return filtered, removed_serials
    filtered = [
        line
        for line in filtered
        if not (
            line.startswith("CONECT")
            and any(
                token.isdigit() and int(token) in removed_serials
                for token in line[6:].split()
            )
        )
    ]
    return filtered, removed_serials


@beartype
def _abfe_prepare_trajectory_topology(
    *,
    pdb_path: str,
    trajectory_path: str,
    step: Literal["md", "binding", "solvation"],
) -> str:
    """Return a PDB whose coordinate count matches an ABFE XTC trajectory.

    FEP ``solute_trajectory`` files omit retained crystallographic waters, while
    historical ``solute.pdb`` outputs can still contain those waters. Mol*
    requires topology and frame atom counts to match exactly.
    """
    if step == "md" or Path(trajectory_path).suffix.lower() != ".xtc":
        return pdb_path

    trajectory_atoms = _abfe_xtc_atom_count(trajectory_path)
    pdb = Path(pdb_path)
    lines = pdb.read_text(encoding="utf-8").splitlines(keepends=True)
    coordinate_lines = [
        line for line in lines if line.startswith(_PDB_COORDINATE_RECORD_PREFIXES)
    ]
    if len(coordinate_lines) == trajectory_atoms:
        return pdb_path

    filtered, _ = _abfe_pdb_without_solvent(lines)
    filtered_atom_count = sum(
        line.startswith(_PDB_COORDINATE_RECORD_PREFIXES) for line in filtered
    )
    if filtered_atom_count != trajectory_atoms:
        raise DeepOriginException(
            title="Trajectory topology mismatch",
            message=(
                f"Trajectory contains {trajectory_atoms} atoms, but topology "
                f"contains {len(coordinate_lines)} ({filtered_atom_count} after "
                "removing solvent)."
            ),
            fix="Use the solute topology generated by the same ABFE run.",
        ) from None

    prepared_path = pdb.with_name(f"{pdb.stem}.trajectory-{trajectory_atoms}.pdb")
    prepared_path.write_text("".join(filtered), encoding="utf-8")
    return str(prepared_path)


_LEGACY_ABFE_RESULT_TOOL_KEYS: frozenset[str] = frozenset(
    {"deeporigin.abfe-e2e-workflow"},
)


@beartype
def _abfe_normalize_execution_dto_tool_key(dto: dict[str, Any]) -> dict[str, Any]:
    """Map legacy ABFE workflow tool keys to the current catalog key for ``from_dto``."""
    tool = dto.get("tool")
    if not isinstance(tool, dict):
        return dto
    key = tool.get("key")
    if key not in _LEGACY_ABFE_RESULT_TOOL_KEYS:
        return dto
    canonical = TOOL_KEYS_AND_VERSIONS["abfe"]["tool_key"]
    return {**dto, "tool": {**tool, "key": canonical}}


@beartype
def _abfe_merged_result_data_for_execution(
    response: dict[str, Any],
    *,
    execution_tool_key: str,
) -> dict[str, Any] | None:
    """Merge result ``data`` payloads for one ABFE execution (all related tool keys).

    Combined runs may store paths on system-prep rows and trajectories on ABFE rows.
    ``from_id`` executions use the DTO tool key, which may differ from the catalog
    ``deeporigin.abfe-end-to-end`` constant.
    """
    sysprep_key = TOOL_KEYS_AND_VERSIONS["sysprep"]["tool_key"]
    abfe_key = TOOL_KEYS_AND_VERSIONS["abfe"]["tool_key"]
    allowed = {
        execution_tool_key,
        sysprep_key,
        abfe_key,
    } | _LEGACY_ABFE_RESULT_TOOL_KEYS
    merged: dict[str, Any] = {}
    for record in response.get("data") or []:
        if not isinstance(record, dict):
            continue
        tool_key = record.get("tool_key")
        if tool_key not in allowed:
            continue
        data = record.get("data")
        if isinstance(data, dict) and data:
            merged.update(data)
    return merged if merged else None


@beartype
def _abfe_pick_analysis_block(
    *,
    blocks: list[Any],
    repeat: int,
) -> dict[str, Any]:
    """Pick one binding or solvation analysis dict for the given repeat index."""
    if not blocks:
        raise DeepOriginException(
            title="No analysis repeats in results",
            message="The results payload has no analysis entries for this step.",
        ) from None
    for block in blocks:
        if isinstance(block, dict) and block.get("repeat") == repeat:
            return block
    if 1 <= repeat <= len(blocks):
        candidate = blocks[repeat - 1]
        if isinstance(candidate, dict):
            return candidate
    raise DeepOriginException(
        title="Invalid repeat index",
        message=f"No analysis block for repeat={repeat!r}.",
        fix=f"Use repeat between 1 and {len(blocks)} (or a repeat id present in results).",
    ) from None


@beartype
def _abfe_sorted_window_numbers(*, trajectories: dict[str, Any]) -> list[int]:
    """Sorted lambda-window indices from a ``trajectories`` mapping."""
    out: list[int] = []
    for key in trajectories:
        if not isinstance(key, str) or not key.startswith("window_"):
            continue
        suffix = key.removeprefix("window_")
        if suffix.isdigit():
            out.append(int(suffix))
    return sorted(out)


@beartype
def _abfe_filtered_records(
    response: dict[str, Any],
    *,
    tool_key: str,
) -> list[dict[str, Any]]:
    """Return result records whose ``tool_key`` matches the ABFE tool."""
    records = response.get("data") or []
    return [
        record
        for record in records
        if isinstance(record, dict) and record.get("tool_key") == tool_key
    ]


@beartype
def _abfe_merged_result_data(
    response: dict[str, Any],
    *,
    tool_key: str,
) -> dict[str, Any] | None:
    """Merge ``data`` payloads from all ABFE result records in page order.

    Combined ``system-prep`` + ``abfe`` workflows may emit multiple rows under
    the same ``tool_key`` (for example prepared-system paths in an early row
    and FEP energies / ``binding_analysis`` in a later row).
    """
    merged: dict[str, Any] = {}
    for record in _abfe_filtered_records(response, tool_key=tool_key):
        data = record.get("data")
        if isinstance(data, dict) and data:
            merged.update(data)
    return merged if merged else None


@beartype
def _abfe_results_dataframe(
    response: dict[str, Any],
    *,
    tool_key: str,
) -> pd.DataFrame | None:
    """Build a one-row summary table from ABFE result records.

    Combined workflow executions may store multiple ABFE rows; payloads are merged.
    """
    data = _abfe_merged_result_data(response, tool_key=tool_key)
    if data is None:
        return None
    df = pd.json_normalize([data])
    drop_roots = frozenset({"binding_analysis", "solvation_analysis"})
    to_drop = [
        c for c in df.columns if c in drop_roots or c.split(".", 1)[0] in drop_roots
    ]
    if to_drop:
        df = df.drop(columns=to_drop)
    priority = ["protein_id", "ligand1_id", "total", "unit"]
    head = [c for c in priority if c in df.columns]
    tail = [c for c in df.columns if c not in head]
    return df[head + tail]


def _pose_from_tool_input(ref: dict[str, Any]) -> Pose:
    """Rehydrate a pose from an ABFE ``pose1`` reference."""
    pose_id = ref.get("id")
    file_path = ref.get("file_path")
    if pose_id is None and not file_path:
        msg = "Pose input must include 'id' or 'file_path'."
        raise ValueError(msg)
    return Pose(
        ligand_id=str(ref.get("ligand_id") or ""),
        id=str(pose_id) if pose_id is not None else None,
        remote_path=str(file_path) if file_path else None,
        name=ref.get("name"),
        smiles=ref.get("smiles"),
        protein_id=str(ref["protein_id"]) if ref.get("protein_id") else None,
    )


class ABFE(Execution, AsyncExecutableMixin, NotebookWatchMixin):
    """ABFE workflow (``deeporigin.abfe-end-to-end``).

    Platform ``steps`` are inferred from constructor inputs (see :meth:`_post_init`):

    - ``["system-prep", "abfe"]``: ``protein`` + ``pose`` / ``pose1``
    - ``["abfe"]``: ``prepared_system``

    Attributes:
        steps: Ordered workflow steps forwarded to the platform tool.
        name: Optional execution label (auto-generated for combined mode).
    """

    tool_key: str = TOOL_KEYS_AND_VERSIONS["abfe"]["tool_key"]

    @beartype
    def __init__(
        self,
        *,
        protein: Protein | None = None,
        pose: Pose | None = None,
        pose1: Pose | None = None,
        prepared_system: PreparedSystem | None = None,
        params: ABFEParams | None = None,
        add_h_atoms: bool = False,
        protonate_protein: bool = False,
        retain_waters: bool = True,
        padding: float = 1.0,
        tool_version: str = TOOL_KEYS_AND_VERSIONS["abfe"]["tool_version"],
        client: DeepOriginClient | None = None,
        name: str | None = None,
    ) -> None:
        """Create an ABFE workflow execution.

        Platform ``steps`` are inferred in :meth:`_post_init`:

        - ``prepared_system`` -> ``["abfe"]`` (FEP on existing system)
        - ``protein`` + ``pose`` / ``pose1`` -> ``["system-prep", "abfe"]``

        Exactly one of ``prepared_system`` or (``protein`` + pose) must be
        provided. ``pose`` and ``pose1`` are mutually exclusive aliases.

        Args:
            protein: Protein for combined system-prep + ABFE mode.
            pose: Pose for combined mode (alias for ``pose1``).
            pose1: Pose for combined mode.
            prepared_system: Prepared system for ABFE-only steps.
            params: FEP simulation parameters.
            add_h_atoms: Add hydrogens to pose during prep.
            protonate_protein: Protonate protein during prep.
            retain_waters: Retain crystal waters during prep.
            padding: Solvation box padding (nm) during prep.
            tool_version: Platform tool version pin.
            client: Optional API client.
            name: Optional execution label. Auto-generated for combined mode.

        Raises:
            ValueError: When inputs are missing or mutually exclusive.
        """
        super().__init__(client=client)
        self.tool_version = tool_version
        self.protein = protein
        if pose is not None and pose1 is not None:
            raise ValueError("Provide only one of pose or pose1, not both.")
        self.pose1 = pose if pose is not None else pose1
        self.prepared_system = prepared_system
        self._params = params if params is not None else ABFEParams()
        self.add_h_atoms = add_h_atoms
        self.protonate_protein = protonate_protein
        self.retain_waters = retain_waters
        self.padding = padding
        self.name = name
        self._post_init()

    def _post_init(self) -> None:
        """Infer platform ``steps`` from constructor inputs and validate."""
        has_prep = self.prepared_system is not None
        has_combined = self.protein is not None and self.pose1 is not None
        mode_count = sum([has_prep, has_combined])

        if mode_count != 1:
            raise ValueError(
                "Exactly one of prepared_system or (protein and pose/pose1) "
                "must be provided."
            )
        if has_prep:
            self.steps: list[ABFEWorkflowStep] = ["abfe"]
        else:
            self.steps = ["system-prep", "abfe"]
        self._validate_step_inputs()

        if has_combined and self.name is None:
            assert self.protein is not None
            assert self.pose1 is not None
            self.name = _abfe_default_name_from_entities(
                protein=self.protein,
                pose=self.pose1,
                client=self.client,
            )

    @property
    def params(self) -> ABFEParams:
        """FEP calculation parameters (read-only)."""
        return self._params

    @params.setter
    def params(self, value: ABFEParams) -> None:
        """Prevent modification of params after construction."""
        raise AttributeError("params can only be set in the constructor")

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct an ABFE instance from an execution DTO.

        Rehydrates ``steps``, prep inputs, ``prepared_system``, and ``_params`` from
        stored ``userInputs`` (falling back to ``inputs`` for older payloads).

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client. Uses the default if not provided.

        Returns:
            A fully-hydrated ABFE instance with status from the DTO.

        Raises:
            ValueError: When ``steps`` is missing or unsupported.
        """
        instance = super().from_dto(dto, client=client)
        inputs: dict[str, Any] = (
            instance._dto.get("userInputs")  # ty:ignore[unresolved-attribute]
            or instance._dto.get("inputs")  # ty:ignore[unresolved-attribute]
            or {}
        )

        raw_steps = inputs.get("steps")
        if not raw_steps:
            msg = "Missing 'steps' in execution userInputs."
            raise ValueError(msg)
        instance.steps = list(raw_steps)

        if instance.steps == ["system-prep"]:
            msg = (
                "Legacy steps=['system-prep'] executions are no longer supported "
                "by ABFE.from_dto()."
            )
            raise ValueError(msg)

        instance.protein = None
        instance.pose1 = None
        instance.prepared_system = None
        instance.add_h_atoms = bool(inputs.get("add_H_atoms", False))
        instance.protonate_protein = bool(inputs.get("protonate_protein", False))
        instance.retain_waters = bool(inputs.get("retain_waters", True))
        instance.padding = float(inputs.get("padding", 1.0))
        instance._params = (
            _fep_params_from_inputs(inputs)
            if "abfe" in instance.steps
            else ABFEParams()
        )

        if "system-prep" in instance.steps:
            protein_input = inputs.get("protein", {})
            if isinstance(protein_input, dict) and protein_input:
                instance.protein = _protein_from_tool_input(
                    protein_input,
                    client=instance.client,
                )

            pose_input = inputs.get("pose1") or inputs.get("ligand1") or {}
            if pose_input:
                instance.pose1 = _pose_from_tool_input(pose_input)

        if instance.steps == ["abfe"]:
            prepared_system_input = inputs.get("prepared_system", {})
            instance.prepared_system = PreparedSystem(
                binding_xml_path=prepared_system_input.get("binding_xml_file_path", ""),
                solvation_xml_path=prepared_system_input.get(
                    "solvation_xml_ligand_file_path", ""
                ),
                system_pdb_path="",
                solute_pdb_path=prepared_system_input.get("solute_pdb_file_path"),
                protein_id=prepared_system_input.get("protein_id"),
                ligand1_id=prepared_system_input.get("ligand1_id"),
                ligand2_id=prepared_system_input.get("ligand2_id"),
            )

        return instance

    @classmethod
    def from_id(
        cls,
        id: str,
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct an ABFE instance from an existing platform execution ID.

        Fetches the execution record via the API and delegates to :meth:`from_dto`.
        When the execution DTO includes ``projectId``, :attr:`client.project_id`
        is updated to match so result and file lookups use the same scope as the
        run (set ``client.project_id = None`` before calling when the notebook
        project should not filter results).

        Args:
            id: Platform execution ID.
            client: Optional API client. Uses the default if not provided.

        Returns:
            A fully-hydrated ABFE instance with status synced from the platform.
        """
        if client is None:
            client = DeepOriginClient()
        dto = client.executions.get(id)  # ty:ignore[unresolved-attribute]
        dto = _abfe_normalize_execution_dto_tool_key(dto)
        return cls._from_dto_maybe_quiet(dto, client=client, quiet=False)

    def _validate_step_inputs(self) -> None:
        """Validate constructor arguments for the selected workflow steps."""
        if "system-prep" in self.steps:
            if self.protein is None:
                raise ValueError(f"protein is required for steps={self.steps!r}.")
            if self.pose1 is None:
                raise ValueError(f"pose/pose1 is required for steps={self.steps!r}.")
        if self.steps == ["abfe"] and self.prepared_system is None:
            raise ValueError("prepared_system is required for steps=['abfe'].")

    def _ensure_synced_inputs(self) -> None:
        """Sync protein and pose before submission."""
        client = self.client
        if self.protein is not None:
            self.protein.sync(lazy=True, client=client)
            self.protein.ensure_remote_path(client=client, label="Protein")
        if self.pose1 is not None and "system-prep" in self.steps:
            self.pose1.sync(lazy=True, client=client)
            self.pose1.ensure_remote_path(client=client, label="Pose")

    def _build_params(self) -> dict[str, Any]:
        """Construct workflow input parameters for ``deeporigin.abfe-end-to-end``."""
        out: dict[str, Any] = {"steps": self.steps}
        if "system-prep" in self.steps:
            assert self.protein is not None
            assert self.pose1 is not None
            out["protein"] = {
                "id": self.protein.id,
                "file_path": self.protein.remote_path,
            }
            out["pose1"] = _pose_tool_ref(self.pose1)
            out.update(
                {
                    "add_H_atoms": self.add_h_atoms,
                    "protonate_protein": self.protonate_protein,
                    "retain_waters": self.retain_waters,
                    "padding": self.padding,
                }
            )
        if self.steps == ["abfe"]:
            assert self.prepared_system is not None
            out["prepared_system"] = _prepared_system_tool_ref(self.prepared_system)
        if "abfe" in self.steps:
            out.update(_simulation_blocks(self._params))
        return out

    def _make_payload(
        self,
        *,
        approve_amount: int | None,
        sync: bool,  # noqa: ARG002
    ) -> dict[str, Any]:
        """Build create payload for ``executions.create``."""
        payload: dict[str, Any] = {
            "inputs": self._build_params(),
            "outputs": {},
        }
        if approve_amount is not None:
            payload["approveAmount"] = approve_amount
        if self.name is not None:
            payload["name"] = self.name
        return payload

    @beartype
    def _start_impl(self, *, approve_amount: int | None = None, **kwargs: Any) -> None:
        """Submit the ABFE workflow execution to the platform.

        Args:
            approve_amount: Spend cap forwarded to the platform. ``0`` requests
                a quote only; ``None`` runs immediately.
        """
        self._ensure_synced_inputs()
        payload = self._make_payload(approve_amount=approve_amount, sync=False)
        execution_dto = self._create_execution(data=payload)

        if execution_dto.get("executionId") is None:
            msg = "Execution response must contain 'executionId'"
            raise ValueError(msg)

        self.update_from_dto(execution_dto)

    def get_results(self, **_kwargs: Any) -> pd.DataFrame | None:
        """Retrieve ABFE results as a DataFrame.

        Uses :meth:`~deeporigin.drug_discovery.execution.Execution.get_results`
        (results for this execution by id), then builds a one-row table from the
        first ``deeporigin.abfe-end-to-end`` record's ``data`` payload. System-prep rows
        from combined runs are excluded. Keyword arguments are accepted for
        signature compatibility with the base class but are not forwarded.

        Returns:
            A DataFrame with ABFE results, or ``None`` if not yet available.

        Raises:
            ValueError: If no execution has been started.
        """
        self.sync()
        if not is_success_status(self.status):
            return None

        response = super().get_results()
        return _abfe_results_dataframe(response, tool_key=self.tool_key)

    @beartype
    def get_prepared_system(
        self,
        *,
        ligand1_id: str | None = None,
        sync: bool = True,
    ) -> PreparedSystem:
        """Load a :class:`PreparedSystem` from system-prep results for this execution.

        Fetches prepared-system rows scoped to this ABFE execution via
        :meth:`~deeporigin.drug_discovery.structures.prepared_system.PreparedSystem.from_result`.
        When multiple rows match, returns the first.

        Args:
            ligand1_id: Optional ligand ID to filter by.
            sync: When ``True`` (default), refresh execution status from the
                platform before loading prepared-system rows. Pass ``False`` when
                the caller already synced or only needs paths from results.

        Returns:
            A :class:`PreparedSystem` with paths and metadata from the result row.

        Raises:
            ValueError: If no execution has been started.
            DeepOriginException: If no matching system-prep results exist yet.
        """
        if self.id is None:
            raise ValueError(
                "Cannot get prepared system: no execution has been started (id is None)."
            )

        if sync:
            self.sync()

        try:
            systems = PreparedSystem.from_result(
                compute_job_id=self.id,
                ligand1_id=ligand1_id,
                client=self.client,
            )
        except ValueError as exc:
            raise DeepOriginException(
                title="No system-prep results found",
                message=(
                    "No system-prep results found for this ABFE execution. "
                    "Wait for the system-prep step to complete, or pass "
                    "ligand1_id to disambiguate."
                ),
            ) from exc

        if not systems:
            raise DeepOriginException(
                title="No system-prep results found",
                message=(
                    "No system-prep results found for this ABFE execution. "
                    "Wait for the system-prep step to complete, or pass "
                    "ligand1_id to disambiguate."
                ),
            )

        return systems[0]

    def _resolved_prepared_system(self) -> PreparedSystem:
        """Return ``prepared_system`` or load it from execution results."""
        if self.prepared_system is not None:
            return self.prepared_system
        return self.get_prepared_system()

    def _fetch_merged_abfe_result_data(self) -> dict[str, Any]:
        """Load merged ABFE + system-prep result payloads for this execution id."""
        if self.id is None:
            raise ValueError(
                "Cannot fetch ABFE results: no execution has been started (id is None)."
            )
        response = self.client.results.get(compute_job_id=self.id)
        data = _abfe_merged_result_data_for_execution(
            response,
            execution_tool_key=self.tool_key,
        )
        if data is not None:
            return data
        response = self.client.results.get(
            compute_job_id=self.id,
            filter_dict={"tool_key": {"eq": self.tool_key}},
        )
        data = _abfe_merged_result_data(response, tool_key=self.tool_key)
        if data is None:
            raise DeepOriginException(
                title="No ABFE results for this execution",
                message=(
                    "The data platform returned no ABFE or system-prep result rows "
                    "for this job."
                ),
            ) from None
        return data

    @beartype
    def show_trajectory(
        self,
        *,
        step: Literal["md", "binding", "solvation"],
        window: int = 1,
        repeat: int = 1,
        show_progress: bool | None = None,
    ) -> Any:
        """Visualize an ABFE trajectory in a notebook using Mol*.

        Trajectory remote paths are read from this execution's data-platform
        results (same payload as ``client.results.get(compute_job_id=abfe.id)``):
        for ``binding`` or ``solvation``, the per-window
        ``solute_trajectory_20ps.xtc`` paths under ``binding_analysis`` /
        ``solvation_analysis``. For ``md``, the equilibration/production MD path
        under ``tool-runs/<id>/protein/ligand/simple_md/...`` is derived from
        those paths.

        Args:
            step: ``md`` for the post-prep MD segment; ``binding`` or
                ``solvation`` for a lambda window from the corresponding leg.
            window: Lambda window index (1-based). Ignored when ``step`` is
                ``md``.
            repeat: Repeat index from the tool results (matched to the
                ``repeat`` field when present, otherwise 1-based index into the
                analysis list).
            show_progress: In Jupyter, show a compact step progress bar while
                paths are resolved and files are downloaded. ``None`` enables
                progress only in notebook environments; pass ``False`` to disable.

        Returns:
            Notebook display output from :func:`deeporigin.utils.notebook.render_html`.

        Raises:
            ValueError: If the execution has not been started (no id).
            DeepOriginException: If the job is not succeeded, results lack paths,
                ``window`` is invalid, or no system PDB can be resolved.
        """
        if self.id is None:
            raise ValueError(
                "Cannot show trajectory: no execution has been started (id is None)."
            )

        if window < 1:
            raise DeepOriginException(
                title="Invalid window number",
                message="Window number must be greater than 0",
                fix="Please specify a window number greater than 0",
            ) from None

        from deeporigin.drug_discovery.import_dataset_sync_display import (
            import_dataset_sync_progress_for_abfe_trajectory,
        )

        progress = import_dataset_sync_progress_for_abfe_trajectory(
            show_progress=show_progress,
        )
        step_index = 0

        try:
            progress.start_step(
                step_index,
                detail=f"{step} · window {window}" if step != "md" else step,
            )
            if not is_success_status(self.status):
                self.sync()
            if not is_success_status(self.status):
                raise DeepOriginException(
                    title="Job not complete",
                    message=(
                        "Trajectory is only available after a successful run. "
                        f"Current status is {self.status!r}."
                    ),
                    fix="Wait until the execution status is Completed, then try again.",
                ) from None

            data = self._fetch_merged_abfe_result_data()

            remote_pdb = _abfe_remote_trajectory_topology_path(data, step=step)
            if remote_pdb is None and self.prepared_system is not None:
                remote_pdb = _abfe_remote_trajectory_topology_path_from_prepared_system(
                    self.prepared_system,
                    step=step,
                )
            if remote_pdb is None:
                prepared = self.get_prepared_system(sync=False)
                remote_pdb = _abfe_remote_trajectory_topology_path_from_prepared_system(
                    prepared,
                    step=step,
                )
            if not remote_pdb:
                raise DeepOriginException(
                    title="No trajectory topology path",
                    message=(
                        "Cannot locate a PDB topology matching this trajectory in "
                        "ABFE results or prepared-system metadata."
                    ),
                    fix=(
                        "Ensure the run recorded solute_pdb_file_path for binding/"
                        "solvation trajectories or system_pdb_file_path for MD."
                    ),
                ) from None

            if step in ("binding", "solvation"):
                analysis_key = (
                    "binding_analysis" if step == "binding" else "solvation_analysis"
                )
                blocks = data.get(analysis_key)
                if not isinstance(blocks, list):
                    raise DeepOriginException(
                        title="Missing analysis in results",
                        message=f"Results do not contain a list at {analysis_key!r}.",
                    ) from None

                block = _abfe_pick_analysis_block(blocks=blocks, repeat=repeat)
                traj = block.get("trajectories")
                if not isinstance(traj, dict):
                    raise DeepOriginException(
                        title="Missing trajectories",
                        message=f"No trajectories map in results for {analysis_key!r}.",
                    ) from None

                window_key = f"window_{window}"
                if window_key not in traj:
                    valid = _abfe_sorted_window_numbers(trajectories=traj)
                    raise DeepOriginException(
                        title="Invalid window number",
                        message=f"Valid windows are: {valid}",
                    ) from None

                remote_xtc = traj[window_key]
                if not isinstance(remote_xtc, str) or not remote_xtc.strip():
                    raise DeepOriginException(
                        title="Invalid trajectory path",
                        message=(
                            f"Results entry {window_key!r} is missing or not a path string."
                        ),
                    ) from None
                remote_xtc = remote_xtc.strip()
            else:
                sample_path = _abfe_first_remote_trajectory_path(data=data)
                root = _abfe_tool_run_root(remote_trajectory_path=sample_path)
                remote_xtc = (
                    f"{root}/protein/ligand/simple_md/simple_md/prod/"
                    "_allatom_trajectory_40ps.xtc"
                )

            progress.finish_step(step_index, detail=Path(remote_xtc).name)
            step_index += 1

            progress.start_step(step_index, detail=Path(remote_pdb).name)
            local_pdb = self.client.files.download(remote_pdb, lazy=True)
            local_pdb = _abfe_local_trajectory_topology_path(local_pdb, step=step)
            progress.finish_step(step_index)
            step_index += 1

            progress.start_step(step_index, detail=Path(remote_xtc).name)
            local_xtc = self.client.files.download(remote_xtc, lazy=True)
            progress.finish_step(step_index)
            step_index += 1

            from deeporigin.utils.notebook import render_html
            from deeporigin.viz.molstar_html import render_trajectory_html

            progress.start_step(step_index)
            local_pdb = _abfe_prepare_trajectory_topology(
                pdb_path=local_pdb,
                trajectory_path=local_xtc,
                step=step,
            )
            viewer_html = render_trajectory_html(
                pdb_path=local_pdb,
                trajectory_path=local_xtc,
            )
            progress.finish_step(step_index)

            return render_html(viewer_html)
        except Exception as exc:
            progress.fail_step(step_index, message=str(exc))
            raise
        finally:
            progress.close()

    @beartype
    def show_overlap_matrix(
        self,
        *,
        run: Literal["binding", "solvation"] = "binding",
        repeat: int = 1,
    ) -> None:
        """Display the overlap-matrix PNG for this execution in Jupyter.

        Reads merged data-platform result rows for this job (same payload as
        ``client.results.get(compute_job_id=abfe.id)``), takes
        ``overlap_matrix_plot`` from ``binding_analysis`` or
        ``solvation_analysis`` for the chosen repeat, downloads via
        :meth:`deeporigin.platform.files.Files.download`, and renders with
        :class:`IPython.display.Image`.

        Args:
            run: Which leg of the calculation to show: ``"binding"`` or
                ``"solvation"``.
            repeat: Repeat index from the tool results (matched to the
                ``repeat`` field when present, otherwise 1-based index into the
                analysis list). Same semantics as :meth:`show_trajectory`.

        Raises:
            ValueError: If the execution has no platform id yet.
            DeepOriginException: If the run is not complete, results are missing,
                or no overlap-matrix plot path is present for the chosen leg.
        """
        if self.id is None:
            raise ValueError(
                "Cannot show overlap matrix: no execution has been started (id is None)."
            )

        self.sync()
        if not is_success_status(self.status):
            raise DeepOriginException(
                title="ABFE run is not complete",
                message=(
                    "Overlap matrices are only available after a successful run. "
                    f"Current status is {self.status!r}."
                ),
            ) from None

        response = self.client.results.get(
            compute_job_id=self.id,
            filter_dict={"tool_key": {"eq": self.tool_key}},
        )
        data = _abfe_merged_result_data(response, tool_key=self.tool_key)
        if data is None:
            raise DeepOriginException(
                title="No overlap matrix found for this run",
                message=(
                    "Unable to show overlap matrix because there are no ABFE result "
                    "records for this execution."
                ),
            ) from None

        analysis_key = "binding_analysis" if run == "binding" else "solvation_analysis"
        blocks = data.get(analysis_key)
        if not isinstance(blocks, list):
            raise DeepOriginException(
                title="No overlap matrix found for this run",
                message=f"Results do not contain a list at {analysis_key!r}.",
            ) from None

        block = _abfe_pick_analysis_block(blocks=blocks, repeat=repeat)

        remote_path = block.get("overlap_matrix_plot")
        if not isinstance(remote_path, str) or not remote_path.strip():
            raise DeepOriginException(
                title="No overlap matrix found for this run",
                message=(
                    "Unable to show overlap matrix because overlap_matrix_plot is "
                    f"not set for the {run} leg."
                ),
            ) from None

        local_path = self.client.files.download(remote_path.strip(), lazy=True)

        from IPython.display import Image, display

        display(Image(local_path))

    @beartype
    def show_convergence_time(
        self,
        *,
        run: Literal["binding", "solvation"] = "binding",
        repeat: int = 1,
    ) -> None:
        """Display the time-convergence PNG for this execution in Jupyter.

        Reads merged data-platform result rows for this job (same payload as
        ``client.results.get(compute_job_id=abfe.id)``), takes ``convergence_plot``
        from ``binding_analysis`` or ``solvation_analysis`` for the chosen
        repeat, downloads via :meth:`deeporigin.platform.files.Files.download`,
        and renders with :class:`IPython.display.Image`.

        Args:
            run: Which leg of the calculation to show: ``"binding"`` or
                ``"solvation"``.
            repeat: Repeat index from the tool results (matched to the
                ``repeat`` field when present, otherwise 1-based index into the
                analysis list). Same semantics as :meth:`show_trajectory`.

        Raises:
            ValueError: If the execution has no platform id yet.
            DeepOriginException: If the run is not complete, results are missing,
                or no convergence plot path is present for the chosen leg.
        """
        if self.id is None:
            raise ValueError(
                "Cannot show convergence plot: no execution has been started (id is None)."
            )

        self.sync()
        if not is_success_status(self.status):
            raise DeepOriginException(
                title="ABFE run is not complete",
                message=(
                    "Convergence plots are only available after a successful run. "
                    f"Current status is {self.status!r}."
                ),
            ) from None

        response = self.client.results.get(
            compute_job_id=self.id,
            filter_dict={"tool_key": {"eq": self.tool_key}},
        )
        data = _abfe_merged_result_data(response, tool_key=self.tool_key)
        if data is None:
            raise DeepOriginException(
                title="No convergence plot found for this run",
                message=(
                    "Unable to show convergence plot because there are no ABFE result "
                    "records for this execution."
                ),
            ) from None

        analysis_key = "binding_analysis" if run == "binding" else "solvation_analysis"
        blocks = data.get(analysis_key)
        if not isinstance(blocks, list):
            raise DeepOriginException(
                title="No convergence plot found for this run",
                message=f"Results do not contain a list at {analysis_key!r}.",
            ) from None

        block = _abfe_pick_analysis_block(blocks=blocks, repeat=repeat)

        remote_path = block.get("convergence_plot")
        if not isinstance(remote_path, str) or not remote_path.strip():
            raise DeepOriginException(
                title="No convergence plot found for this run",
                message=(
                    "Unable to show convergence plot because convergence_plot is "
                    f"not set for the {run} leg."
                ),
            ) from None

        local_path = self.client.files.download(remote_path.strip(), lazy=True)

        from IPython.display import Image, display

        display(Image(local_path))

    def __repr__(self) -> str:
        """Return a concise multi-line representation."""
        parts = ["ABFE("]
        if self.id is not None:
            parts.append(f"  id={self.id!r},")
        if self.status is not None:
            parts.append(f"  status={self.status!r},")
        ps = getattr(self, "prepared_system", None)
        parts.extend(
            [
                f"  steps={self.steps!r},",
                f"  tool_key={self.tool_key!r},",
                f"  has_prepared_system={ps is not None},",
                f"  has_protein={getattr(self, 'protein', None) is not None},",
                ")",
            ]
        )
        return "\n".join(parts)


__all__ = ["ABFE", "ABFEParams", "ABFEWorkflowStep"]
