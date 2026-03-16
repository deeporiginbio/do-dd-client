"""
A simplified class representing a binding pocket in a protein structure.

The Pocket class stores only the essential coordinate information needed for
pocket analysis and visualization, removing the complexity of maintaining
full biotite structure objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Optional, Self

import numpy as np

if TYPE_CHECKING:
    from deeporigin.functions.result import FunctionResult
    from deeporigin.platform.client import DeepOriginClient

from deeporigin.drug_discovery.constants import POCKETS_BASE_DIR
from deeporigin.drug_discovery.structures.ligand import Ligand


@dataclass
class Pocket:
    """Class representing a binding pocket in a protein structure.

    This class provides essential methods
    for pocket analysis, visualization, and coordinate manipulation.
    """

    id: Optional[str] = None
    file_path: Optional[Path] = None
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
    pocket_center: Optional[list[float]] = None
    box_size_x: Optional[float] = None
    box_size_y: Optional[float] = None
    box_size_z: Optional[float] = None

    props: Optional[dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self):
        from biotite.structure.io.pdb import PDBFile

        if self.file_path is not None:
            # Load coordinates directly from PDB file
            structure_file = PDBFile.read(str(self.file_path))
            structure = structure_file.get_structure()

            # Handle AtomArrayStack by taking the first structure
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

        # Set name if not provided
        if self.name is None:
            if self.file_path:
                self.name = self.file_path.stem
            else:
                self.name = "Unknown_Pocket"
                directory = Path(POCKETS_BASE_DIR)
                directory.mkdir(parents=True, exist_ok=True)
                num = len(list(directory.glob(f"{self.name}*")))
                self.name = f"{self.name}_{num + 1}"

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
            file_path=pdb_file_path,
            name=name,
            coordinates=coordinates,
            **kwargs,
        )
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

        if self.pocket_center is not None:
            cx, cy, cz = self.pocket_center
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

        Returns the pre-computed ``pocket_center`` when available, otherwise
        falls back to computing the mean of the loaded coordinates.

        Returns:
            np.ndarray: A numpy array of shape (3,) with the pocket center.
        """
        if self.pocket_center is not None:
            return np.asarray(self.pocket_center, dtype=float)
        if self.coordinates is None:
            raise ValueError("No coordinates loaded for this pocket")
        return self.coordinates.mean(axis=0)

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
            "pocket_center",
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
    }

    @classmethod
    def from_json(
        cls,
        data: list[dict[str, Any]],
    ) -> list[Self]:
        """Create a list of Pocket objects from a JSON pocket list.

        Each entry in the list should be a dict with at least a ``file_path``
        key. Known property keys (``volume``, ``total_SASA``, etc.) are mapped
        to dedicated attributes. The ``protein_id`` key is mapped to its own
        attribute. Any remaining unknown keys go into ``props``.

        Args:
            data: List of pocket dicts, e.g. the value of the ``"pockets"``
                key returned by the pocket-finder tool.

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
            {"id", "file_path", "protein_id"} | cls._PROPERTY_ATTRS | json_mapped_keys
        )

        pockets = []
        for idx, entry in enumerate(data):
            raw_path = entry.get("file_path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise ValueError(
                    f"Entry at index {idx} is missing a valid 'file_path' value "
                    f"(got {raw_path!r}): {entry}"
                )
            file_path = Path(raw_path)
            protein_id = entry.get("protein_id")

            attr_kwargs: dict[str, Any] = {}
            for k in cls._PROPERTY_ATTRS:
                if k in entry:
                    attr_kwargs[k] = entry[k]
            for json_key, attr_name in cls._JSON_KEY_MAP.items():
                if json_key in entry and attr_name not in attr_kwargs:
                    attr_kwargs[attr_name] = entry[json_key]

            props = {k: v for k, v in entry.items() if k not in reserved_keys}

            pocket = cls(
                id=entry.get("id"),
                file_path=file_path,
                name=file_path.stem,
                protein_id=protein_id,
                props=props,
                color=colors[idx % len(colors)],
                **attr_kwargs,
            )
            pockets.append(pocket)

        return pockets

    @classmethod
    def from_function_result(
        cls,
        *,
        result: "FunctionResult",
        client: "DeepOriginClient",
    ) -> list[Self]:
        """Download pocket PDB files from a function result and build Pocket objects.

        Extracts the pocket list from a raw pocket-finder ``FunctionResult``,
        downloads the PDB files, and delegates to ``from_json`` to construct
        Pocket instances.

        Args:
            result: FunctionResult wrapping a pocket-finder response.
            client: DeepOrigin client for downloading files.

        Returns:
            A list of Pocket objects.
        """
        outputs = result.function_outputs[0]
        pockets_data = [
            {
                **pocket,
                "file_path": client.files.download_file(
                    remote_path=pocket["file_path"],
                    lazy=True,
                ),
            }
            for pocket in outputs.get("pockets", [])
        ]

        return cls.from_json(pockets_data)

    @classmethod
    def from_id(
        cls,
        id: str,
        *,
        client: Optional["DeepOriginClient"] = None,
    ) -> Self:
        """Create a Pocket from a result-explorer record ID.

        Fetches the single record, downloads the pocket PDB file, and
        constructs a Pocket object.

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
            client = DeepOriginClient.get()

        response = client.results.get_pockets(id=id)
        records = response.get("data", [])

        if not records:
            raise ValueError(f"No pocket record found for id={id!r}.")

        record = records[0]
        pocket_data = dict(record["data"])
        pocket_data["id"] = record["id"]
        remote_path = pocket_data["file_path"]
        pocket_data["file_path"] = client.files.download_file(
            remote_path=remote_path,
            lazy=True,
        )

        return cls.from_json([pocket_data])[0]

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

        Fetches pocketfinder results for the given protein, downloads the
        pocket PDB files, and constructs Pocket objects.

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
            client = DeepOriginClient.get()

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
            remote_path = pocket_data["file_path"]
            local_path = client.files.download_file(remote_path=remote_path)
            pocket_data["file_path"] = local_path
            pockets_data.append(pocket_data)

        return cls.from_json(pockets_data)

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
        """Write coordinates to a PDB file."""
        if self.coordinates is None:
            raise ValueError("No coordinates available to write to file")

        path = Path(output_path)
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            f.write("HEADER    POCKET COORDINATES\n")
            for i, coord in enumerate(self.coordinates):
                x, y, z = coord
                f.write(
                    f"ATOM  {i + 1:5d}  CA  UNK A{i + 1:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           C\n"
                )
            f.write("END\n")

    def update_coordinates(self, coords: np.ndarray):
        """update coordinates of the pocket"""

        self.coordinates = coords
