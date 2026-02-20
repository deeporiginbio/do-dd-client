"""
A simplified class representing a binding pocket in a protein structure.

The Pocket class stores only the essential coordinate information needed for
pocket analysis and visualization, removing the complexity of maintaining
full biotite structure objects.

Attributes:
    file_path (Optional[Path]): Path to the PDB file containing the pocket.
    coordinates (Optional[np.ndarray]): 3D coordinates of the pocket atoms.
    name (Optional[str]): Name of the pocket.
    color (str): Color for visualization (default: "red").
    props (Optional[Dict[str, Any]]): Additional properties of the pocket.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Self

import numpy as np

from deeporigin.drug_discovery.constants import POCKETS_BASE_DIR
from deeporigin.drug_discovery.structures.ligand import Ligand


@dataclass
class Pocket:
    """A simplified class representing a binding pocket in a protein structure.

    This class focuses on coordinate-based operations and removes the complexity
    of maintaining full biotite structure objects. It provides essential methods
    for pocket analysis, visualization, and coordinate manipulation.
    """

    file_path: Optional[Path] = None
    color: str = "red"
    name: Optional[str] = None
    pdb_id: Optional[str] = None
    protein_id: Optional[str] = None
    index: Optional[int] = 0
    props: Optional[dict[str, Any]] = field(default_factory=dict)
    coordinates: Optional[np.ndarray] = None

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

    def __repr__(self):
        # Single table with all info
        table_data = [
            ["Name", self.name],
            ["Color", self.color],
        ]

        # Add properties if available
        if self.props:
            table_data.extend(
                [
                    ["Volume", f"{self.props.get('volume', 'N/A')} Å³"],
                    ["Total SASA", f"{self.props.get('total_SASA', 'N/A')} Å²"],
                    ["Polar SASA", f"{self.props.get('polar_SASA', 'N/A')} Å²"],
                    [
                        "Polar/Apolar SASA ratio",
                        f"{self.props.get('polar_apolar_SASA_ratio', 'N/A')}",
                    ],
                    ["Hydrophobicity", f"{self.props.get('hydrophobicity', 'N/A')}"],
                    ["Polarity", f"{self.props.get('polarity', 'N/A')}"],
                    [
                        "Drugability score",
                        f"{self.props.get('drugability_score', 'N/A')}",
                    ],
                ]
            )

        from tabulate import tabulate

        return f"Pocket:\n{tabulate(table_data, tablefmt='rounded_grid')}"

    def get_center(self) -> np.ndarray:
        """
        Get the center of the pocket based on its coordinates.

        Returns:
            np.ndarray: A numpy array containing the center of the pocket.
        """
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

    @classmethod
    def from_json(
        cls,
        data: list[dict[str, Any]],
    ) -> list[Self]:
        """Create a list of Pocket objects from a JSON pocket list.

        Each entry in the list should be a dict with at least a ``file_path``
        key. All remaining keys (except ``protein_id``) are stored in
        ``props``.  The ``protein_id`` key is mapped to the dedicated
        attribute of the same name.

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

        reserved_keys = {"file_path", "protein_id"}

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
            props = {k: v for k, v in entry.items() if k not in reserved_keys}

            pocket = cls(
                file_path=file_path,
                name=file_path.stem,
                protein_id=protein_id,
                props=props,
                color=colors[idx % len(colors)],
            )
            pockets.append(pocket)

        return pockets

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

    def __str__(self):
        properties_line = ""
        if self.props:
            properties_line = (
                f"  Volume: {self.props.get('volume', 'N/A')}Å³, "
                f"Total SASA: {self.props.get('total_SASA', 'N/A')}, "
                f"Polar SASA: {self.props.get('polar_SASA', 'N/A')}, "
                f"Polar/Apolar SASA ratio: {self.props.get('polar_apolar_SASA_ratio', 'N/A')}, "
                f"Hydrophobicity: {self.props.get('hydrophobicity', 'N/A')}, "
                f"Polarity: {self.props.get('polarity', 'N/A')}, "
                f"Drugability score: {self.props.get('drugability_score', 'N/A')}"
            )

        return (
            f"Pocket:\n  Name: {self.name}\n{properties_line}  File: {self.file_path}\n"
            "Available Fields: {file_path, name, coordinates, color, props}"
        )

    def update_coordinates(self, coords: np.ndarray):
        """update coordinates of the pocket"""

        self.coordinates = coords
