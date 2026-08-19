"""Pose and PoseSet — 3D conformations registered in the platform pose result table."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Optional, Self

from beartype import beartype
import pandas as pd
from rdkit import Chem

from deeporigin.drug_discovery.structures.entity import Entity
from deeporigin.drug_discovery.structures.ligand import (
    Ligand,
    LigandSet,
    _first_valid_mol_from_sdf,
)
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS

_POSE_JSON_RESERVED: frozenset[str] = frozenset(
    {
        "file_path",
        "local_path",
        "remote_path",
        "smiles",
        "canonical_smiles",
        "ligand_smiles",
        "ligand_id",
        "name",
        "project_id",
        "id",
        "protein_id",
        "compute_job_id",
        "pose_score",
        "binding_energy",
        "best_pose",
        "origin",
    }
)


def _strip_nonempty_str(value: Any) -> str | None:
    """Return stripped string if ``value`` is a non-empty str, else None."""

    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _path_points_to_existing_local_file(path: str) -> bool:
    """Return True if ``path`` refers to an existing regular file on disk."""

    try:
        return Path(path).expanduser().is_file()
    except (OSError, ValueError):
        return False


def _apply_file_path_to_paths(
    *,
    remote_path: str | None,
    file_path: str,
) -> tuple[str | None, str | None]:
    """Set local and/or remote path from a ``file_path`` field (pose / API shape)."""

    local_path: str | None = None
    out_remote = remote_path
    is_local_file = _path_points_to_existing_local_file(file_path)
    if out_remote is None:
        if is_local_file:
            local_path = file_path
        else:
            out_remote = file_path
    elif is_local_file:
        local_path = file_path
    return local_path, out_remote


def _resolve_pose_entry_paths(
    entry: dict[str, Any], idx: int
) -> tuple[str | None, str | None]:
    """Extract ``(local_path, remote_path)`` from a pose dict.

    Args:
        entry: Single pose dict (``file_path``, ``local_path``, and/or ``remote_path``).
        idx: Index in the pose list (for error messages).

    Returns:
        At least one of ``local_path`` or ``remote_path`` is non-``None``.

    Raises:
        ValueError: If no usable path is present.
    """

    remote_path = _strip_nonempty_str(entry.get("remote_path"))
    file_path = _strip_nonempty_str(entry.get("file_path"))
    explicit_local = _strip_nonempty_str(entry.get("local_path"))

    local_path: str | None = None

    if file_path is not None:
        local_path, remote_path = _apply_file_path_to_paths(
            remote_path=remote_path,
            file_path=file_path,
        )
    elif explicit_local is not None:
        local_path = explicit_local

    if local_path is None and remote_path is None:
        raise ValueError(
            f"Pose at index {idx} needs a valid 'file_path', 'local_path', or "
            f"'remote_path' (got file_path={entry.get('file_path')!r}, "
            f"remote_path={entry.get('remote_path')!r}): {entry}"
        )

    return local_path, remote_path


def _optional_float(value: Any) -> float | None:
    """Coerce a value to float when possible."""

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    """Coerce a value to bool when possible."""

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


@dataclass
@beartype
class Pose(Entity):
    """A 3D ligand conformation backed by an SDF in the platform pose result table.

    A :class:`Pose` holds the platform **pose result id** (:attr:`id`) and the
    parent **ligand id** (:attr:`ligand_id`). These are distinct from
    :class:`~deeporigin.drug_discovery.structures.ligand.Ligand` identity.

    Attributes:
        ligand_id: Parent ligand id in the ligands table.
        smiles: Canonical or input SMILES when known without loading the SDF.
        name: Optional pose or ligand name.
        protein_id: Optional protein the pose is associated with.
        compute_job_id: Optional compute job that produced this pose.
        pose_score: Docking pose score when present.
        binding_energy: Docking binding energy when present.
        best_pose: Whether this row is the best pose for its ligand in a run.
        origin: Provenance string (for example ``registered`` or ``docking``).
        props: Additional metadata from the platform row.
    """

    ligand_id: str
    smiles: str | None = None
    name: str | None = None
    protein_id: str | None = None
    compute_job_id: str | None = None
    pose_score: float | None = None
    binding_energy: float | None = None
    best_pose: bool | None = None
    origin: str | None = None
    props: dict[str, Any] = field(default_factory=dict)
    _mol: Chem.Mol | None = field(default=None, repr=False, compare=False)

    _remote_path_base: ClassVar[str] = "entities/poses/"
    _preferred_ext: ClassVar[str] = ".sdf"

    @property
    def mol(self) -> Chem.Mol | None:
        """Return the RDKit molecule, loading from disk when needed."""

        if self._mol is not None:
            return self._mol
        if self.local_path is not None:
            path = Path(self.local_path)
            if not path.is_file():
                return None
            try:
                supplier = Chem.SDMolSupplier(str(path), removeHs=False)
                for candidate in supplier:
                    if candidate is not None:
                        self._mol = candidate
                        return self._mol
            except (OSError, RuntimeError, IndexError):
                return None
        return None

    def to_hash(self) -> str:
        """Return a stable hash string for remote path generation."""

        if self.id is not None:
            return self.id
        if self.remote_path:
            return Path(self.remote_path).stem
        if self.local_path:
            return Path(self.local_path).stem
        if self.ligand_id:
            return self.ligand_id
        if self.smiles:
            return Ligand.from_smiles(self.smiles).to_hash()
        raise DeepOriginException(
            title="Pose has no hash identity",
            message="Cannot derive remote path: set id, remote_path, local_path, "
            "ligand_id, or smiles.",
        )

    def to_file(self, file_path: str | Path | None = None) -> str:
        """Write this pose to an SDF file.

        Args:
            file_path: Destination path. When omitted, writes a temp file.

        Returns:
            Path to the written SDF file.

        Raises:
            DeepOriginException: If no local structure is available.
        """

        if self.local_path is not None and file_path is None:
            return self.local_path
        self._assert_rehydrated_for_file_export(entity_label="Pose", format_name="SDF")
        mol = self.mol
        if mol is None:
            raise DeepOriginException(
                title="Pose has no structure",
                message="Cannot write SDF: load a local or remote pose file first.",
            )
        if file_path is None:
            lig = Ligand.from_rdkit_mol(mol, name=self.name or "")
            return lig.to_sdf()
        out = Path(file_path)
        writer = Chem.SDWriter(str(out))
        writer.write(mol)
        writer.close()
        self.local_path = str(out)
        return str(out)

    def sync(
        self,
        *,
        lazy: bool = False,
        client: Optional[DeepOriginClient] = None,
        remote_path: Optional[str] = None,
    ) -> None:
        """Upload the pose SDF when a local file exists.

        Pose registration (platform pose id) is handled by :meth:`from_sdf`.
        This method only uploads bytes when ``local_path`` is set.

        Args:
            lazy: Skip upload when :attr:`remote_path` is already set.
            client: Optional platform client.
            remote_path: Optional explicit remote key.
        """

        if lazy and self.remote_path is not None:
            return
        if self.local_path is None:
            return
        self.upload(client=client, remote_path=remote_path)

    @classmethod
    def from_json(
        cls,
        data: list[dict[str, Any]],
        *,
        client: Optional[DeepOriginClient] = None,
        sanitize: bool = True,
        remove_hydrogens: bool = False,
    ) -> list[Self]:
        """Build :class:`Pose` objects from pose metadata dicts.

        Args:
            data: Pose rows (for example result-explorer ``data`` payloads).
            client: Optional client for ``project_id`` fallback.
            sanitize: Passed to :meth:`Ligand.from_sdf` for local SDF paths.
            remove_hydrogens: Passed to :meth:`Ligand.from_sdf` for local paths.

        Returns:
            One pose per dict, in input order.

        Raises:
            ValueError: If a row is invalid or lacks required fields.
        """

        poses: list[Self] = []
        for idx, raw in enumerate(data):
            if not isinstance(raw, dict):
                raise ValueError(
                    f"Pose at index {idx} must be a dict, got {type(raw)!r}."
                )
            poses.append(
                cls._pose_from_dict(
                    dict(raw),
                    idx,
                    client=client,
                    sanitize=sanitize,
                    remove_hydrogens=remove_hydrogens,
                )
            )
        return poses

    @classmethod
    def _pose_from_dict(
        cls,
        entry: dict[str, Any],
        idx: int,
        *,
        client: Optional[DeepOriginClient],
        sanitize: bool,
        remove_hydrogens: bool,
    ) -> Self:
        """Materialize one :class:`Pose` from a metadata dict."""

        local_path, remote_path = _resolve_pose_entry_paths(entry, idx)
        ligand_id = entry.get("ligand_id")
        if ligand_id is None or not str(ligand_id).strip():
            raise ValueError(
                f"Pose at index {idx} must include a non-empty 'ligand_id'."
            )

        smiles: str | None = None
        mol: Chem.Mol | None = None
        name = entry.get("name")
        if local_path is not None:
            lig = Ligand.from_sdf(
                local_path,
                sanitize=sanitize,
                remove_hydrogens=remove_hydrogens,
            )
            mol = lig.mol
            smiles = lig.smiles or lig.canonical_smiles
            if name is None:
                name = lig.name
        else:
            raw_smiles = (
                entry.get("smiles")
                or entry.get("canonical_smiles")
                or entry.get("ligand_smiles")
            )
            if isinstance(raw_smiles, str) and raw_smiles.strip():
                smiles = raw_smiles.strip()

        pose_id = entry.get("id")
        proj = _strip_nonempty_str(entry.get("project_id"))
        if proj is None and client is not None:
            proj = getattr(client, "project_id", None)

        props = {
            str(key): val
            for key, val in entry.items()
            if str(key) not in _POSE_JSON_RESERVED
        }

        return cls(
            id=str(pose_id) if pose_id is not None else None,
            ligand_id=str(ligand_id),
            local_path=local_path,
            remote_path=remote_path,
            project_id=proj,
            smiles=smiles,
            name=str(name) if name is not None else None,
            protein_id=_strip_nonempty_str(entry.get("protein_id")),
            compute_job_id=_strip_nonempty_str(entry.get("compute_job_id")),
            pose_score=_optional_float(entry.get("pose_score")),
            binding_energy=_optional_float(entry.get("binding_energy")),
            best_pose=_optional_bool(entry.get("best_pose")),
            origin=_strip_nonempty_str(entry.get("origin")),
            props=props,
            _mol=mol,
        )

    @classmethod
    def from_id(
        cls,
        id: str,
        *,
        client: Optional[DeepOriginClient] = None,
    ) -> Self:
        """Load a single pose from a result-explorer record id.

        Args:
            id: Platform pose result id.
            client: Optional platform client.

        Returns:
            The matching :class:`Pose`.

        Raises:
            ValueError: If no pose record exists for ``id``.
        """

        if client is None:
            client = DeepOriginClient()

        response = client.results.get(
            result_type="pose",
            filter_dict={"id": {"eq": id}},
            limit=1,
        )
        records = response.get("data", [])
        if not records:
            raise ValueError(f"No pose record found for id={id!r}.")

        record = records[0]
        data = dict(record.get("data") or {})
        data["id"] = record.get("id")
        if record.get("compute_job_id") is not None:
            data.setdefault("compute_job_id", record.get("compute_job_id"))
        if "file_path" in data and "remote_path" not in data:
            data["remote_path"] = data.pop("file_path")
        return cls.from_json([data], client=client)[0]

    @classmethod
    def from_sdf(
        cls,
        path: str | Path,
        *,
        ligand: Ligand | None = None,
        protein_id: str | None = None,
        origin: str = "registered",
        client: Optional[DeepOriginClient] = None,
        sanitize: bool = True,
        remove_hydrogens: bool = False,
    ) -> Self:
        """Register an external SDF as a platform pose and return a :class:`Pose`.

        Syncs the parent :class:`Ligand` (unless ``ligand`` is supplied), uploads
        the SDF, and invokes the ImportTool pose-registration path.

        Args:
            path: Local SDF file path.
            ligand: Optional explicit parent ligand (skips auto-sync by SMILES).
            protein_id: Optional associated protein id.
            origin: Provenance string stored on the pose row.
            client: Optional platform client.
            sanitize: Passed to :meth:`Ligand.from_sdf`.
            remove_hydrogens: Passed to :meth:`Ligand.from_sdf`.

        Returns:
            Registered :class:`Pose` with platform id populated.

        Raises:
            DeepOriginException: If registration fails or returns no pose row.
        """

        if client is None:
            client = DeepOriginClient()

        local_path = str(path)
        parent = ligand or Ligand.from_sdf(
            local_path,
            sanitize=sanitize,
            remove_hydrogens=remove_hydrogens,
        )
        if ligand is None:
            parent.sync(client=client)
        if parent.id is None:
            raise DeepOriginException(
                title="Ligand sync failed",
                message="Parent ligand must have a platform id before pose registration.",
            )

        staging = cls(
            ligand_id=parent.id,
            local_path=local_path,
            smiles=parent.smiles or parent.canonical_smiles,
            name=parent.name,
            protein_id=protein_id,
            origin=origin,
        )
        staging.upload(client=client)
        pose_remote = staging.remote_path
        if pose_remote is None:
            raise DeepOriginException(
                title="Pose upload failed",
                message="Could not upload pose SDF to platform storage.",
            )

        inputs: dict[str, Any] = {
            "register_pose": True,
            "file_path": pose_remote,
            "ligand_id": parent.id,
            "origin": origin,
        }
        if protein_id is not None:
            inputs["protein_id"] = protein_id

        tool_meta = TOOL_KEYS_AND_VERSIONS["import_dataset"]
        raw = client.executions.create(  # ty:ignore[unresolved-attribute]
            tool_key=tool_meta["tool_key"],
            tool_version=tool_meta["tool_version"],
            data={
                "inputs": inputs,
                "outputs": {},
                "metadata": {},
                "sync": True,
            },
        )
        dto = raw if isinstance(raw, dict) else {}
        pose_row = _pose_row_from_registration_execution(dto)
        if pose_row is None:
            raise DeepOriginException(
                title="Pose registration failed",
                message="ImportTool did not return a pose row in jobOutputs.poses.",
            )

        if pose_row.get("id") is None:
            pose_row = _resolve_registered_pose_row(
                client=client,
                ligand_id=parent.id,
                file_path=pose_remote,
                origin=origin,
                fallback=pose_row,
            )

        pose_row.setdefault("ligand_id", parent.id)
        pose_row.setdefault("origin", origin)
        if protein_id is not None:
            pose_row.setdefault("protein_id", protein_id)
        pose_row["local_path"] = local_path
        pose_row.setdefault("file_path", pose_remote)
        pose_row.setdefault("remote_path", pose_remote)
        if parent.smiles:
            pose_row.setdefault("smiles", parent.smiles)

        pose = cls.from_json([pose_row], client=client)[0]
        if pose.local_path is None:
            pose.local_path = local_path
        return pose

    def download(
        self,
        *,
        lazy: bool = True,
        client: DeepOriginClient | None = None,
        sanitize: bool = True,
        remove_hydrogens: bool = False,
    ) -> str:
        """Download the pose SDF and reload :attr:`mol` from disk when needed.

        Args:
            lazy: Reuse cached local files when True.
            client: Optional platform client.
            sanitize: Passed to :meth:`Ligand.from_sdf` when rehydrating.
            remove_hydrogens: Passed to :meth:`Ligand.from_sdf` when rehydrating.

        Returns:
            Local file path.
        """

        prior_local = self.local_path
        out = super().download(lazy=lazy, client=client)
        if prior_local is None and self.local_path is not None:
            _rehydrate_pose_from_local_sdf(
                self,
                sanitize=sanitize,
                remove_hydrogens=remove_hydrogens,
            )
        return out

    def to_ligand(self) -> Ligand:
        """Convert this pose to a legacy pose-hydrated :class:`Ligand`.

        Prefer using :class:`Pose` directly; this exists for backward compatibility
        with code paths that still expect :class:`Ligand` pose rows (for example
        molstar overlays).
        """

        lig = _ligand_from_pose_structure(self)
        _copy_pose_metadata_onto_ligand(self, lig)
        return lig


def _rehydrate_pose_from_local_sdf(
    pose: Pose,
    *,
    sanitize: bool = True,
    remove_hydrogens: bool = False,
) -> None:
    """Reload pose mol/smiles/name from ``local_path`` when it is an SDF file."""

    if pose.local_path is None:
        return
    path = Path(pose.local_path)
    if path.suffix.lower() != ".sdf" or not path.is_file():
        return
    mol = _first_valid_mol_from_sdf(
        path,
        sanitize=sanitize,
        remove_hydrogens=remove_hydrogens,
    )
    if mol is None:
        return
    lig = Ligand.from_rdkit_mol(mol, properties=mol.GetPropsAsDict())
    pose._mol = lig.mol
    if pose.smiles is None:
        pose.smiles = lig.smiles or lig.canonical_smiles
    if pose.name in (None, ""):
        pose.name = lig.name


def _ligand_from_pose_structure(pose: Pose) -> Ligand:
    """Build a Ligand from a pose's local SDF or SMILES."""

    if pose.local_path is not None and Path(pose.local_path).is_file():
        mol = pose._mol or _first_valid_mol_from_sdf(pose.local_path)
        if mol is not None:
            lig = Ligand.from_rdkit_mol(mol, name=pose.name or "")
            lig.local_path = pose.local_path
            if pose.remote_path is not None:
                lig.remote_path = pose.remote_path
            return lig
    if pose.smiles:
        lig = Ligand.from_smiles(smiles=pose.smiles, name=pose.name or "")
        lig.remote_path = pose.remote_path or pose.local_path
        return lig
    raise DeepOriginException(
        title="Cannot convert Pose to Ligand",
        message=(
            "Pose needs a local SDF or SMILES to build a Ligand. "
            "Call download() first when only remote_path is set."
        ),
    )


def _copy_pose_metadata_onto_ligand(pose: Pose, lig: Ligand) -> None:
    """Copy platform pose fields onto a legacy Ligand."""

    lig.id = pose.ligand_id
    if pose.project_id is not None:
        lig.project_id = pose.project_id
    if pose.id is not None:
        lig.properties["pose_result_id"] = pose.id
        lig.properties["id"] = pose.id
    if pose.pose_score is not None:
        lig.properties["pose_score"] = pose.pose_score
    if pose.binding_energy is not None:
        lig.properties["Binding Energy"] = pose.binding_energy
        lig.properties["binding_energy"] = pose.binding_energy
    if pose.best_pose is not None:
        lig.properties["best_pose"] = pose.best_pose
    if pose.protein_id is not None:
        lig.properties["protein_id"] = pose.protein_id
    if pose.compute_job_id is not None:
        lig.properties["compute_job_id"] = pose.compute_job_id
    if pose.origin is not None:
        lig.properties["origin"] = pose.origin
    for key, val in pose.props.items():
        lig.properties[str(key)] = val
    if pose.name:
        lig.name = pose.name


def _pose_row_from_registration_execution(dto: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the first pose dict from an ImportTool registration execution."""

    jo = dto.get("jobOutputs")
    if isinstance(jo, dict):
        poses = jo.get("poses")
        if isinstance(poses, list) and poses:
            first = poses[0]
            if isinstance(first, dict):
                return dict(first)
    return None


def _explorer_record_to_pose_row(
    rec: dict[str, Any],
    fallback: dict[str, Any],
) -> dict[str, Any]:
    """Merge a result-explorer pose record into a registration fallback row."""

    data = rec.get("data")
    row = dict(fallback)
    if isinstance(data, dict):
        row.update(data)
    row["id"] = rec.get("id")
    if rec.get("compute_job_id") is not None:
        row.setdefault("compute_job_id", rec.get("compute_job_id"))
    return row


def _pose_record_data(rec: Any) -> dict[str, Any] | None:
    """Return pose ``data`` payload when ``rec`` is a valid result-explorer row."""

    if not isinstance(rec, dict):
        return None
    data = rec.get("data")
    if not isinstance(data, dict):
        return None
    return data


def _matches_registered_pose_row(
    data: dict[str, Any],
    *,
    origin: str,
    file_path: str | None,
) -> bool:
    """Return whether a pose row matches registration lookup filters."""

    if file_path is not None:
        return data.get("file_path") == file_path
    if origin:
        return data.get("origin") == origin
    return False


def _resolve_registered_pose_row(
    *,
    client: DeepOriginClient,
    ligand_id: str,
    file_path: str | None,
    origin: str,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    """Look up a freshly registered pose row in result-explorer when id is missing."""

    response = client.results.get_poses(ligand_id=ligand_id, limit=None)
    records = response.get("data", [])
    for rec in records:
        data = _pose_record_data(rec)
        if data is None:
            continue
        if _matches_registered_pose_row(
            data,
            origin=origin,
            file_path=file_path,
        ):
            return _explorer_record_to_pose_row(rec, fallback)

    if records:
        last_rec = records[-1]
        data = _pose_record_data(last_rec)
        if data is not None:
            return _explorer_record_to_pose_row(last_rec, fallback)

    return fallback


@dataclass
@beartype
class PoseSet:
    """Collection of :class:`Pose` objects."""

    poses: list[Pose] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.poses)

    def __iter__(self):
        return iter(self.poses)

    def __getitem__(self, index: int | slice) -> Pose | PoseSet:
        result = self.poses[index]
        if isinstance(result, list):
            return PoseSet(poses=result)
        return result

    @classmethod
    def from_json(
        cls,
        data: list[dict[str, Any]],
        *,
        client: Optional[DeepOriginClient] = None,
        sanitize: bool = True,
        remove_hydrogens: bool = False,
    ) -> Self:
        """Build a :class:`PoseSet` from pose metadata dicts."""

        return cls(
            poses=Pose.from_json(
                data,
                client=client,
                sanitize=sanitize,
                remove_hydrogens=remove_hydrogens,
            )
        )

    @classmethod
    def from_result(
        cls,
        *,
        protein_id: str | None = None,
        execution_id: str | None = None,
        ligand_id: str | list[str] | None = None,
        best_pose: bool | None = None,
        scored_only: bool = False,
        client: Optional[DeepOriginClient] = None,
    ) -> Self:
        """Load poses from the data platform result explorer.

        Args:
            protein_id: Optional protein filter.
            execution_id: Optional compute job / execution id filter.
            ligand_id: Optional ligand id filter (single id or list).
            best_pose: When set, restrict to rows whose ``best_pose`` matches.
            scored_only: When ``True``, skip reference/metadata rows that lack
                docking scores (same filter as legacy docking loaders).
            client: Optional platform client.

        Returns:
            Matching :class:`PoseSet`.

        Raises:
            ValueError: If no pose rows match the filters.
        """

        from deeporigin.drug_discovery.docking_common import (
            load_poses_from_result_explorer,
        )

        if client is None:
            client = DeepOriginClient()

        return load_poses_from_result_explorer(
            execution_id,
            client=client,
            protein_id=protein_id,
            ligand_id=ligand_id,
            best_pose=best_pose,
            scored_only=scored_only,
        )

    def to_ligand_set(self) -> LigandSet:
        """Convert to a legacy :class:`LigandSet` of pose-hydrated ligands."""

        return LigandSet(ligands=[pose.to_ligand() for pose in self.poses])

    def download(
        self,
        *,
        client: Optional[DeepOriginClient] = None,
        lazy: bool = True,
        max_workers: int = 20,
        skip_errors: bool = False,
        sanitize: bool = True,
        remove_hydrogens: bool = False,
    ) -> None:
        """Download platform SDF files for poses that lack a local path.

        Args:
            client: Optional platform client.
            lazy: Reuse cached local files when True.
            max_workers: Maximum concurrent downloads.
            skip_errors: When False, raise on the first download failure.
            sanitize: Passed to SDF rehydration after download.
            remove_hydrogens: Passed to SDF rehydration after download.
        """

        pending = [
            pose for pose in self.poses if pose.remote_path and pose.local_path is None
        ]
        if not pending:
            return
        if client is None:
            client = DeepOriginClient()
        remotes = list(
            dict.fromkeys(rp for rp in (p.remote_path for p in pending) if rp)
        )
        paths_by_remote = client.files.download_many(
            files=remotes,
            lazy=lazy,
            max_workers=max_workers,
            skip_errors=skip_errors,
        )
        for pose in pending:
            _assign_downloaded_pose_path(
                pose,
                paths_by_remote=paths_by_remote,
                skip_errors=skip_errors,
                sanitize=sanitize,
                remove_hydrogens=remove_hydrogens,
            )

    def to_dataframe(self) -> pd.DataFrame:
        """Convert poses to a pandas DataFrame (via legacy ligand view)."""

        if len(self.poses) == 0:
            return pd.DataFrame()
        return self.to_ligand_set().to_dataframe()

    def show_df(self):
        """Show poses in a dataframe with 2D visualizations."""

        return self.to_ligand_set().show_df()

    def to_sdf(self, output_path: str | Path | None = None) -> str:
        """Write all poses with local structures to a multi-record SDF.

        Args:
            output_path: Destination path. When omitted, writes a temp file.

        Returns:
            Path to the written SDF.
        """

        return self.to_ligand_set().to_sdf(output_path)

    def filter_top_poses(self, *, by_pose_score: bool = True) -> Self:
        """Keep the best pose for each unique SMILES.

        Groups by :attr:`Pose.smiles` and retains:
        - maximum :attr:`Pose.pose_score` when ``by_pose_score`` is True, or
        - minimum :attr:`Pose.binding_energy` otherwise.

        Args:
            by_pose_score: Select by pose score (True) or binding energy (False).

        Returns:
            A new :class:`PoseSet` with one pose per SMILES group.

        Raises:
            DeepOriginException: If a multi-pose group lacks the required score.
        """

        if not self.poses:
            return type(self)(poses=[])

        grouped: dict[str, list[Pose]] = {}
        for pose in self.poses:
            smiles = pose.smiles
            if smiles is None:
                continue
            grouped.setdefault(smiles, []).append(pose)

        best: list[Pose] = []
        for poses in grouped.values():
            if len(poses) == 1:
                best.append(poses[0])
                continue
            if by_pose_score:
                best.append(max(poses, key=lambda p: _require_pose_score(p)))
            else:
                best.append(min(poses, key=lambda p: _require_binding_energy(p)))
        return type(self)(poses=best)


def _assign_downloaded_pose_path(
    pose: Pose,
    *,
    paths_by_remote: dict[str, str],
    skip_errors: bool,
    sanitize: bool,
    remove_hydrogens: bool,
) -> None:
    """Assign a downloaded local path onto ``pose`` and rehydrate when possible."""

    rp = pose.remote_path
    if not rp:
        return
    local_path = paths_by_remote.get(rp)
    if local_path is None:
        if skip_errors:
            return
        raise RuntimeError(f"download_many returned no path for remote_path={rp!r}")
    try:
        pose.local_path = local_path
        _rehydrate_pose_from_local_sdf(
            pose,
            sanitize=sanitize,
            remove_hydrogens=remove_hydrogens,
        )
    except Exception:
        if skip_errors:
            return
        raise


def _require_pose_score(pose: Pose) -> float:
    """Return pose_score or raise when missing/invalid."""

    if pose.pose_score is None:
        raise DeepOriginException(
            f"Pose {pose.id or pose.name or 'unnamed'} missing pose_score"
        )
    return float(pose.pose_score)


def _require_binding_energy(pose: Pose) -> float:
    """Return binding_energy or raise when missing/invalid."""

    if pose.binding_energy is None:
        raise DeepOriginException(
            f"Pose {pose.id or pose.name or 'unnamed'} missing binding_energy"
        )
    return float(pose.binding_energy)
