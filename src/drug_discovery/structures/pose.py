"""Pose and PoseSet — 3D conformations registered in the platform pose result table."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Optional, Self

from beartype import beartype
from rdkit import Chem

from deeporigin.drug_discovery.structures.entity import Entity
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
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
        "effort",
        "constrained",
    }
)


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
            supplier = Chem.SDMolSupplier(self.local_path, removeHs=False)
            mol = supplier[0] if supplier else None
            if mol is not None:
                self._mol = mol
            return self._mol
        return None

    def to_hash(self) -> str:
        """Return a stable hash string for remote path generation."""

        if self.id is not None:
            return self.id
        if self.remote_path:
            return Path(self.remote_path).stem
        lig = Ligand.from_smiles(self.smiles or "C")
        return lig.to_hash()

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

        local_path, remote_path = LigandSet._resolve_pose_entry_paths(entry, idx)
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
        proj = LigandSet._strip_nonempty_str(entry.get("project_id"))
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
            protein_id=LigandSet._strip_nonempty_str(entry.get("protein_id")),
            compute_job_id=LigandSet._strip_nonempty_str(entry.get("compute_job_id")),
            pose_score=_optional_float(entry.get("pose_score")),
            binding_energy=_optional_float(entry.get("binding_energy")),
            best_pose=_optional_bool(entry.get("best_pose")),
            origin=LigandSet._strip_nonempty_str(entry.get("origin")),
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
        parent.sync(client=client)
        if parent.id is None:
            raise DeepOriginException(
                title="Ligand sync failed",
                message="Parent ligand must have a platform id before pose registration.",
            )

        parent.upload(client=client)
        parent.ensure_remote_path(client=client, label="Ligand")

        inputs: dict[str, Any] = {
            "register_pose": True,
            "file_path": parent.remote_path,
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
                file_path=parent.remote_path,
                origin=origin,
                fallback=pose_row,
            )

        pose_row.setdefault("ligand_id", parent.id)
        pose_row.setdefault("origin", origin)
        if protein_id is not None:
            pose_row.setdefault("protein_id", protein_id)
        pose_row["local_path"] = local_path
        if parent.remote_path is not None:
            pose_row.setdefault("file_path", parent.remote_path)
            pose_row.setdefault("remote_path", parent.remote_path)
        if parent.smiles:
            pose_row.setdefault("smiles", parent.smiles)

        pose = cls.from_json([pose_row], client=client)[0]
        if pose.local_path is None:
            pose.local_path = local_path
        return pose

    def to_ligand(self) -> Ligand:
        """Convert this pose to a legacy pose-hydrated :class:`Ligand`.

        Prefer using :class:`Pose` directly; this exists for backward compatibility
        with code paths that still expect :class:`Ligand` pose rows.
        """

        row: dict[str, Any] = {
            "ligand_id": self.ligand_id,
            "smiles": self.smiles,
            "name": self.name,
            "file_path": self.remote_path or self.local_path,
            "local_path": self.local_path,
            "remote_path": self.remote_path,
            "protein_id": self.protein_id,
            "pose_score": self.pose_score,
            "binding_energy": self.binding_energy,
            "best_pose": self.best_pose,
            "origin": self.origin,
        }
        if self.id is not None:
            row["id"] = self.id
        row.update(self.props)
        return LigandSet.from_json([row])[0]


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
        if not isinstance(rec, dict):
            continue
        data = rec.get("data")
        if not isinstance(data, dict):
            continue
        if origin and data.get("origin") == origin:
            return _explorer_record_to_pose_row(rec, fallback)
        if file_path and data.get("file_path") == file_path:
            return _explorer_record_to_pose_row(rec, fallback)

    if records:
        rec = records[-1]
        if isinstance(rec, dict):
            data = rec.get("data")
            if isinstance(data, dict):
                return _explorer_record_to_pose_row(rec, fallback)

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
