"""
A simplified class representing a binding pocket in a protein structure.

The Pocket class stores only the essential coordinate information needed for
pocket analysis and visualization, removing the complexity of maintaining
full biotite structure objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, Any, ClassVar, Optional, Self

import numpy as np

if TYPE_CHECKING:
    from deeporigin.drug_discovery.sync_function_responses import SyncFunctionResponses

from deeporigin.drug_discovery.constants import POCKETS_BASE_DIR
from deeporigin.drug_discovery.structures.entity import Entity
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.platform.client import DeepOriginClient


@dataclass
class Pocket(Entity):
    """Class representing a binding pocket in a protein structure.

    This class provides essential methods
    for pocket analysis, visualization, and coordinate manipulation.
    """

    _remote_path_base = "entities/pockets/"
    _preferred_ext = ".pdb"

    color: str = "red"
    name: Optional[str] = None
    pdb_id: Optional[str] = None
    protein_id: Optional[str] = None
    index: Optional[int] = 0
    coordinates: Optional[np.ndarray] = None

    volume: Optional[float] = None
    total_sasa: Optional[float] = None
    polar_sasa: Optional[float] = None
    apolar_sasa: Optional[float] = None
    polar_apolar_sasa_ratio: Optional[float] = None
    hydrophobicity: Optional[float] = None
    drugability_score: Optional[float] = None
    polarity: Optional[float] = None
    center: Optional[list[float]] = None
    box_size_x: Optional[float] = None
    box_size_y: Optional[float] = None
    box_size_z: Optional[float] = None

    props: Optional[dict[str, Any]] = field(default_factory=dict)
    _client: Optional[DeepOriginClient] = field(default=None, repr=False)

    def __post_init__(self):
        if self.local_path is not None and self.coordinates is None:
            self._load_coordinates_from_file(self.local_path)

        if self.name is None:
            if self.local_path:
                self.name = Path(self.local_path).stem
            elif self.remote_path:
                self.name = Path(self.remote_path).stem
            else:
                self.name = "Unknown_Pocket"
                directory = Path(POCKETS_BASE_DIR)
                directory.mkdir(parents=True, exist_ok=True)
                num = len(list(directory.glob(f"{self.name}*")))
                self.name = f"{self.name}_{num + 1}"

    def _load_coordinates_from_file(self, path: str) -> None:
        """Read a PDB file and populate ``self.coordinates``.

        Args:
            path: Local filesystem path to the PDB file.
        """
        from biotite.structure.io.pdb import PDBFile

        structure_file = PDBFile.read(path)
        structure = structure_file.get_structure()

        if (
            hasattr(structure, "__len__")
            and len(structure) > 0
            and hasattr(structure[0], "coord")
        ):
            self.coordinates = structure[0].coord
        elif hasattr(structure, "coord"):
            self.coordinates = structure.coord
        else:
            raise ValueError("Could not extract coordinates from structure")

    def _ensure_coordinates(self) -> np.ndarray:
        """Load coordinates from file if needed, downloading first if necessary.

        Returns:
            The coordinate array.

        Raises:
            ValueError: If no coordinates and no file path available.
        """
        if self.coordinates is None:
            local = self.download(client=self._client)
            self._load_coordinates_from_file(local)
        coords = self.coordinates
        if coords is None:
            raise ValueError(
                "Pocket coordinates are not available and could not be loaded."
            )
        self._backfill_geometry_from_coordinates()
        return coords

    def _backfill_geometry_from_coordinates(self) -> None:
        """Populate ``center`` / box sizes from loaded coordinates when the API omits them.

        Result-explorer rows may not repeat ``pocket_center`` or box extents; once
        coordinates are available we derive the same fields used by docking tools.
        """
        coords = self.coordinates
        if coords is None or len(coords) == 0:
            return
        if self.center is None:
            mean = coords.mean(axis=0)
            self.center = [float(mean[0]), float(mean[1]), float(mean[2])]
        if (
            self.box_size_x is None
            and self.box_size_y is None
            and self.box_size_z is None
        ):
            span = coords.max(axis=0) - coords.min(axis=0)
            self.box_size_x = float(max(span[0], 1.0))
            self.box_size_y = float(max(span[1], 1.0))
            self.box_size_z = float(max(span[2], 1.0))

    def _to_pdb_string(self) -> str:
        """Generate PDB format string from coordinates.

        Returns:
            PDB file content as a string.
        """
        coords = self._ensure_coordinates()
        lines = ["HEADER    POCKET COORDINATES"]
        for i, coord in enumerate(coords):
            x, y, z = coord
            lines.append(
                f"ATOM  {i + 1:5d}  CA  UNK A{i + 1:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           C"
            )
        lines.append("END")
        return "\n".join(lines) + "\n"

    def to_hash(self) -> str:
        """Compute a hash of the pocket PDB content.

        Returns:
            SHA-256 hex digest of the generated PDB string.
        """
        return hashlib.sha256(self._to_pdb_string().encode()).hexdigest()

    def to_file(self, file_path: str | Path | None = None) -> str:
        """Write pocket coordinates to a PDB file.

        Args:
            file_path: Destination path. When ``None`` a temporary file is
                created; the caller is responsible for deleting it when done.

        Returns:
            The path the file was written to.
        """
        if file_path is None:
            fd = tempfile.NamedTemporaryFile(
                mode="w",
                delete=False,
                suffix=".pdb",
                prefix=f"{self.name or 'pocket'}_",
            )
            path = Path(fd.name)
            fd.write(self._to_pdb_string())
            fd.close()
            return str(path)
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._to_pdb_string())
        return str(path)

    def sync(
        self,
        *,
        lazy: bool = False,
        client: Optional[DeepOriginClient] = None,
        remote_path: Optional[str] = None,
    ) -> None:
        """Upload pocket coordinates to remote storage.

        Unlike :class:`Protein` and :class:`Ligand`, pockets are not looked up
        in the entities API; this only uploads the generated PDB so
        :attr:`remote_path` is set for tools that need a file reference.

        Args:
            lazy: If True, skip when the pocket already has a platform ``id``.
            client: DeepOrigin client. If None, uses ``DeepOriginClient()``.
            remote_path: Optional explicit destination path on the file server.
        """
        if lazy and self.id is not None:
            return
        if client is None:
            client = DeepOriginClient()
        self.upload(client=client, remote_path=remote_path)

    @classmethod
    def from_pdb_file(
        cls,
        pdb_file_path: str | Path,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> Self:
        """
        Create a Pocket instance from a PDB file.

        Args:
            pdb_file_path (str | Path): Path to the PDB file.
            name (Optional[str]): Name for the pocket.
            **kwargs: Additional arguments to pass to the Pocket constructor.

        Returns:
            Pocket: A new Pocket instance.
        """
        pdb_file_path = Path(pdb_file_path)
        if not pdb_file_path.exists():  # NOSONAR sonar is incorrectly flagging this
            raise FileNotFoundError(f"The file {pdb_file_path} does not exist.")

        # Load coordinates directly from PDB file
        from biotite.structure.io.pdb import PDBFile

        structure_file = PDBFile.read(str(pdb_file_path))
        structure = structure_file.get_structure()

        # Handle AtomArrayStack by taking the first structure
        if (
            hasattr(structure, "__len__")
            and len(structure) > 0
            and hasattr(structure[0], "coord")
        ):
            coordinates = structure[0].coord
        elif hasattr(structure, "coord"):
            coordinates = structure.coord
        else:
            raise ValueError("Could not extract coordinates from structure")

        if name is None:
            name = pdb_file_path.stem

        pocket = cls(
            local_path=str(pdb_file_path),
            name=name,
            coordinates=coordinates,
            **kwargs,
        )
        return pocket

    @classmethod
    def from_remote_file(
        cls,
        remote_path: str,
        *,
        client: DeepOriginClient | None = None,
        lazy: bool = True,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> Self:
        """Create a Pocket from a PDB file stored on the platform.

        Downloads the file via :meth:`deeporigin.platform.files.FilesClient.download`,
        then loads it with :meth:`from_pdb_file`.

        Args:
            remote_path: Platform file path (e.g. org storage path) to the PDB file.
            client: DeepOrigin client used for download. If ``None``, uses
                ``DeepOriginClient()``.
            lazy: Passed to ``files.download``; if ``True``, skip download when the
                file already exists locally at the default cache location.
            name: Optional pocket name; defaults to the downloaded file stem (see
                :meth:`from_pdb_file`).
            **kwargs: Additional arguments passed to :meth:`from_pdb_file`.

        Returns:
            Pocket: A pocket with :attr:`~deeporigin.drug_discovery.structures.entity.Entity.remote_path`
            set to ``remote_path`` and :attr:`~deeporigin.drug_discovery.structures.entity.Entity.local_path`
            set to the downloaded file path.
        """
        if client is None:
            client = DeepOriginClient()

        local_file_path = client.files.download(remote_path=remote_path, lazy=lazy)
        pocket = cls.from_pdb_file(local_file_path, name=name, **kwargs)
        pocket.remote_path = remote_path
        return pocket

    def _fmt(self, value: float | None, unit: str = "") -> str:
        """Format a numeric value for display, returning 'N/A' when None."""
        if value is None:
            return "N/A"
        return f"{value}{unit}"

    def __repr__(self):
        """Rich table representation of the pocket."""
        from tabulate import tabulate

        table_data = [["Name", self.name]]
        if self.id:
            table_data.append(["ID", self.id])
        if self.pdb_id:
            table_data.append(["PDB ID", self.pdb_id])
        if self.protein_id:
            table_data.append(["Protein ID", self.protein_id])
        table_data.append(["Color", self.color])

        if self.center is not None:
            cx, cy, cz = self.center
            table_data.append(["Center", f"({cx:.2f}, {cy:.2f}, {cz:.2f})"])

        if all(
            v is not None for v in (self.box_size_x, self.box_size_y, self.box_size_z)
        ):
            table_data.append(
                [
                    "Box size",
                    f"{self.box_size_x:.2f} \u00d7 {self.box_size_y:.2f} \u00d7 {self.box_size_z:.2f} \u00c5",
                ]
            )

        property_rows = [
            ("Volume", self.volume, " \u00c5\u00b3"),
            ("Total SASA", self.total_sasa, " \u00c5\u00b2"),
            ("Polar SASA", self.polar_sasa, " \u00c5\u00b2"),
            ("Polar/Apolar SASA ratio", self.polar_apolar_sasa_ratio, ""),
            ("Hydrophobicity", self.hydrophobicity, ""),
            ("Polarity", self.polarity, ""),
            ("Drugability score", self.drugability_score, ""),
        ]
        has_any = any(v is not None for _, v, _ in property_rows)
        if has_any:
            table_data.extend(
                [label, self._fmt(val, unit)] for label, val, unit in property_rows
            )

        return f"Pocket:\n{tabulate(table_data, tablefmt='rounded_grid')}"

    __str__ = __repr__

    def get_center(self) -> np.ndarray:
        """Get the center of the pocket.

        Returns the pre-computed ``center`` when available, otherwise
        falls back to computing the mean of the loaded coordinates.

        Returns:
            np.ndarray: A numpy array of shape (3,) with the pocket center.
        """
        if self.center is not None:
            return np.asarray(self.center, dtype=float)
        self._ensure_coordinates()
        if self.center is None:
            raise ValueError("Pocket has no center and coordinates could not be loaded.")
        return np.asarray(self.center, dtype=float)

    @classmethod
    def from_residue_number(
        cls,
        protein,
        residue_number: int,
        chain_id: str | None = None,
        cutoff: float = 5.0,
    ) -> Self:
        """
        Creates a pocket centered on a given residue (by number)

        Args:
            protein (Protein): A DeepOrigin Protein Object
            residue_number (int): Residue number of the target residue
            chain_id (str): Chain ID that the residue is in
            cutoff (float): Minimum distance cutoff (Angstroms) from target residue to be included in pocket

        Returns:
            A Pocket object matching the above design.
        """
        if protein.structure is None:
            raise ValueError(
                "Protein has no loaded structure; call protein.download() or "
                "protein.load_structure_from_local() first."
            )

        structure = protein.structure

        if residue_number not in structure.res_id:
            raise ValueError(f"Residue number {residue_number} not found in structure.")

        target_mask = structure.res_id == residue_number

        # Filter by chain if specified
        if chain_id is not None:
            if chain_id not in structure.chain_id:
                raise ValueError(f"Chain {chain_id} not found in structure.")
            target_mask &= structure.chain_id == chain_id

        # Select the targeted residue
        target_atoms = structure[target_mask]
        target_coords = target_atoms.coord

        # Get all unique residues in the structure to compare against
        all_residue_ids = np.unique(structure.res_id)

        selected_residues = []

        for res_id in all_residue_ids:
            # Get atoms for current residue
            res_mask = structure.res_id == res_id

            current_res_atoms = structure[res_mask]
            current_coords = current_res_atoms.coord

            # Get the actual distances
            diff = target_coords[:, np.newaxis, :] - current_coords[np.newaxis, :, :]
            distances = np.sqrt(np.sum(diff**2, axis=2))
            min_distance = np.min(distances)

            if min_distance <= cutoff:
                selected_residues.append(int(res_id))

        # Mask the pocket itself
        pocket_mask = np.isin(structure.res_id, selected_residues)
        pocket_atoms = structure[pocket_mask]

        pocket = cls()
        pocket.coordinates = pocket_atoms.coord
        pocket.name = f"Pocket_{residue_number}"

        return pocket

    _PROPERTY_ATTRS = frozenset(
        {
            "volume",
            "total_sasa",
            "polar_sasa",
            "apolar_sasa",
            "polar_apolar_sasa_ratio",
            "hydrophobicity",
            "drugability_score",
            "polarity",
            "center",
            "box_size_x",
            "box_size_y",
            "box_size_z",
        }
    )

    _JSON_KEY_MAP: ClassVar[dict[str, str]] = {
        "total_SASA": "total_sasa",
        "polar_SASA": "polar_sasa",
        "apolar_SASA": "apolar_sasa",
        "polar_apolar_SASA_ratio": "polar_apolar_sasa_ratio",
        "pocket_center": "center",
    }

    @staticmethod
    def _resolve_paths(
        entry: dict[str, Any],
        idx: int,
    ) -> tuple[str | None, str | None]:
        """Extract and validate local/remote paths from a pocket dict.

        Args:
            entry: Single pocket dict.
            idx: Position in the list (for error messages).

        Returns:
            ``(local_path, remote_path)`` — at least one is non-None.

        Raises:
            ValueError: If neither a valid local nor remote path is present.
        """
        raw_local = entry.get("file_path") or entry.get("local_path")
        raw_remote = entry.get("remote_path")

        has_local = isinstance(raw_local, str) and raw_local.strip()
        has_remote = isinstance(raw_remote, str) and raw_remote.strip()

        if not has_local and not has_remote:
            raise ValueError(
                f"Entry at index {idx} needs a valid 'file_path', "
                f"'local_path', or 'remote_path' "
                f"(got file_path={entry.get('file_path')!r}, "
                f"remote_path={raw_remote!r}): {entry}"
            )

        local_path = raw_local if has_local else None
        remote_path = raw_remote if has_remote else None
        return local_path, remote_path

    @classmethod
    def from_json(
        cls,
        data: list[dict[str, Any]],
        *,
        client: Optional["DeepOriginClient"] = None,
    ) -> list[Self]:
        """Create a list of Pocket objects from a JSON pocket list.

        Each entry should contain at least one of ``file_path`` /
        ``local_path`` (a local filesystem path) or ``remote_path`` (a UFA
        remote path).  When only ``remote_path`` is provided the pocket is
        created without downloading; coordinates will be fetched lazily on
        first access via :meth:`_ensure_coordinates`.

        Known property keys (``volume``, ``total_SASA``, etc.) are mapped
        to dedicated attributes.  The ``protein_id`` key is mapped to its
        own attribute.  Any remaining unknown keys go into ``props``.

        Args:
            data: List of pocket dicts, e.g. the value of the ``"pockets"``
                key returned by the pocket-finder tool.
            client: Optional client to use for lazy downloads. When provided,
                stored on each Pocket and used by :meth:`download` when
                coordinates are first accessed. When an entry omits
                ``project_id``, each Pocket uses ``getattr(client, "project_id", None)``
                when a client is given.

        Returns:
            List of Pocket objects with properties populated from the dicts.
        """
        colors = [
            "red",
            "green",
            "blue",
            "yellow",
            "orange",
            "gray",
            "purple",
            "cyan",
            "magenta",
            "lime",
        ]

        json_mapped_keys = set(cls._JSON_KEY_MAP.keys())
        reserved_keys = (
            {
                "id",
                "file_path",
                "local_path",
                "remote_path",
                "protein_id",
                "project_id",
            }
            | cls._PROPERTY_ATTRS
            | json_mapped_keys
        )

        pockets = []
        for idx, entry in enumerate(data):
            local_path, remote_path = cls._resolve_paths(entry, idx)
            name = Path(local_path or remote_path).stem

            attr_kwargs: dict[str, Any] = {}
            for k in cls._PROPERTY_ATTRS:
                if k in entry:
                    attr_kwargs[k] = entry[k]
            for json_key, attr_name in cls._JSON_KEY_MAP.items():
                if json_key in entry and attr_name not in attr_kwargs:
                    attr_kwargs[attr_name] = entry[json_key]

            props = {k: v for k, v in entry.items() if k not in reserved_keys}

            project_id: str | None = entry.get("project_id")
            if project_id is None and client is not None:
                project_id = getattr(client, "project_id", None)

            pocket = cls(
                id=entry.get("id"),
                local_path=local_path,
                remote_path=remote_path,
                project_id=project_id,
                name=name,
                protein_id=entry.get("protein_id"),
                props=props,
                color=colors[idx % len(colors)],
                _client=client,
                **attr_kwargs,
            )
            pockets.append(pocket)

        return pockets

    @classmethod
    def from_function_result(
        cls,
        *,
        result: "SyncFunctionResponses",
        client: "DeepOriginClient",
    ) -> list[Self]:
        """Build Pocket objects from a pocket-finder ``SyncFunctionResponses``.

        Extracts the pocket list and stores the remote paths without
        downloading.  Files are fetched lazily when coordinates are first
        accessed.

        Args:
            result: SyncFunctionResponses wrapping a pocket-finder response.
            client: DeepOrigin client (retained for API compatibility).

        Returns:
            A list of Pocket objects.
        """
        outputs = result.function_outputs[0]
        pockets_data = []
        for pocket in outputs.get("pockets", []):
            entry = {**pocket}
            entry["remote_path"] = entry.pop("file_path")
            pockets_data.append(entry)

        return cls.from_json(pockets_data, client=client)

    @classmethod
    def from_id(
        cls,
        id: str,
        *,
        client: Optional["DeepOriginClient"] = None,
    ) -> Self:
        """Create a Pocket from a result-explorer record ID.

        Fetches the single record and stores the remote path without
        downloading.  The PDB file is fetched lazily when coordinates
        are first accessed.

        Args:
            id: Result-explorer record ID of the pocket.
            client: Optional DeepOriginClient instance. If not provided,
                uses the default client.

        Returns:
            A Pocket with properties populated from the record.

        Raises:
            ValueError: If no record is found for the given ID.
        """
        from deeporigin.platform.client import DeepOriginClient

        if client is None:
            client = DeepOriginClient()

        response = client.results.get_pockets(id=id)
        records = response.get("data", [])

        if not records:
            raise ValueError(f"No pocket record found for id={id!r}.")

        record = records[0]
        pocket_data = dict(record["data"])
        pocket_data["id"] = record["id"]
        pocket_data["remote_path"] = pocket_data.pop("file_path")

        return cls.from_json([pocket_data], client=client)[0]

    @classmethod
    def from_result(
        cls,
        *,
        protein_id: str | None = None,
        execution_id: str | None = None,
        pocket_count: int | None = None,
        pocket_min_size: int | None = None,
        client: Optional["DeepOriginClient"] = None,
    ) -> list[Self]:
        """Create Pocket objects from pocketfinder results in the data platform.

        Fetches pocketfinder results for the given protein and stores the
        remote paths without downloading.  PDB files are fetched lazily
        when coordinates are first accessed.

        Args:
            protein_id: Protein ID to fetch pocket results for.
            execution_id: Optional compute job ID to filter by.
            pocket_count: Optional maximum number of pockets to filter by.
            pocket_min_size: Optional minimum pocket volume in cubic Angstroms
                to filter by.
            client: Optional DeepOriginClient instance. If not provided,
                uses the default client.

        Returns:
            List of Pocket objects with properties populated from the results.

        Raises:
            ValueError: If no pocket results are found for the protein.
        """
        from deeporigin.platform.client import DeepOriginClient

        if client is None:
            client = DeepOriginClient()

        response = client.results.get_pockets(
            protein_id=protein_id,
            compute_job_id=execution_id,
            pocket_count=pocket_count,
            pocket_min_size=pocket_min_size,
        )
        records = response.get("data", [])

        if not records:
            raise ValueError(
                f"No pocketfinder results found for protein_id={protein_id!r}. Run the pocketfinder tool on that protein to get pockets."
            )

        pockets_data: list[dict[str, Any]] = []
        for record in records:
            pocket_data = dict(record["data"])
            pocket_data["id"] = record["id"]
            pocket_data["remote_path"] = pocket_data.pop("file_path")
            pockets_data.append(pocket_data)

        return cls.from_json(pockets_data, client=client)

    @classmethod
    def from_ligand(
        cls,
        ligand: "Ligand",
        name: Optional[str] = None,
    ) -> Self:
        """
        Create a Pocket instance from a Ligand instance.
        """
        return cls.from_pdb_file(str(ligand.to_pdb()), name=name)

    def to_pdb_file(self, output_path: str):
        """Write coordinates to a PDB file.

        Args:
            output_path: Destination file path.
        """
        self.to_file(output_path)

    def update_coordinates(self, coords: np.ndarray):
        """update coordinates of the pocket"""

        self.coordinates = coords
