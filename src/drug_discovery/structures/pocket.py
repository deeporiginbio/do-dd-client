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
import os
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from tabulate import tabulate
from termcolor import colored

from deeporigin.drug_discovery.constants import POCKETS_BASE_DIR
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.utilities.visualize import jupyter_visualization


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
                directory = Path(self.get_directory())
                directory.mkdir(parents=True, exist_ok=True)
                num = len(list(directory.glob(f"{self.name}*")))
                self.name = f"{self.name}_{num + 1}"

    @classmethod
    def from_pdb_file(
        cls,
        pdb_file_path: str | Path,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> "Pocket":
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
    ) -> "Pocket":
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

            # Get the acutal distances
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
    def from_pocket_finder_results(
        cls,
        pocket_finder_results_dir: str | Path,
    ) -> list["Pocket"]:
        """Create a list of Pocket objects from pocket finder results directory.

        Args:
            pocket_finder_results_dir: Directory containing pocket finder results
                with PDB files for each pocket and a CSV properties file.

        Returns:
            List of Pocket objects with properties from the CSV file.
        """
        # Convert to Path object for consistent handling
        results_dir = Path(pocket_finder_results_dir)

        # Find all PDB files in the directory
        pdb_files = list(results_dir.glob("*.pdb"))

        # Colors to cycle through for pockets
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

        # Create Pocket objects from each PDB file
        pockets = []
        for idx, pdb_file in enumerate(pdb_files):
            # Create a Pocket object with the file path and name (without extension)
            pocket = cls(
                file_path=pdb_file,
                name=pdb_file.stem,
                pdb_id=None,  # Will be set from CSV if available
                props={},  # Initialize empty properties dictionary
                color=colors[idx % len(colors)],  # Cycle through colors
            )
            pockets.append(pocket)

        # Find the CSV properties file
        csv_files = list(results_dir.glob("*.csv"))
        if not csv_files:
            # If no CSV file, return pockets with just file and name
            return pockets

        # Use the first CSV file found
        properties_file = csv_files[0]

        try:
            # Read CSV file using pandas
            df = pd.read_csv(properties_file)

            # Map CSV columns to Pocket properties
            # Using 'pocket_file' column to match with PDB file names
            for pocket in pockets:
                # Get the filename without extension to match with CSV
                pdb_filename = os.path.basename(pocket.file_path)

                # Try to find a row in the CSV that matches this pocket file
                pocket_row = df[df["pocket_file"] == pdb_filename]

                if not pocket_row.empty:
                    # Add all properties from the CSV to the pocket's properties dictionary
                    for column in df.columns:
                        if column != "pocket_file":  # Skip the file column
                            value = pocket_row[column].iloc[0]

                            # Convert NumPy types to Python primitive types
                            if isinstance(value, np.integer):
                                value = int(value)
                            elif isinstance(value, np.floating):
                                value = float(value)
                            elif isinstance(value, np.bool_):
                                value = bool(value)
                            elif pd.isna(value):
                                value = None

                            pocket.props[column] = value
        except Exception:
            # If there's an error reading the CSV, just return the pockets with basic info
            pass

        return pockets

    @classmethod
    def from_ligand(
        cls,
        ligand: "Ligand",
        name: Optional[str] = None,
    ) -> "Pocket":
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

    @jupyter_visualization
    def show(self):
        """show the pocket in a jupyter notebook"""

        pocket_paths = [str(self.file_path)]
        pocket_names = ["Name: " + self.name + " | " + str(self.props)]

        from deeporigin_molstar import ProteinViewer

        viewer = ProteinViewer("", format="pdb")

        pocket_config = viewer.get_pocket_visualization_config()
        # Ensure self.index is within the bounds of surface_colors
        if self.index >= len(pocket_config.surface_colors):
            self.index = 0  # Default to the first color if out of bounds

        pocket_config.surface_colors = [pocket_config.surface_colors[self.index]]
        print(
            "\n|\n".join(
                colored("■", pocket_config.surface_colors[0]) + " " + pocket_name
                for pocket_name in pocket_names
            )
        )

        return viewer.render_protein_with_pockets(
            pocket_paths=pocket_paths, pocket_config=pocket_config
        )

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

    @staticmethod
    def get_directory() -> str:
        """
        Get the pockets directory path.

        Returns:
            str: The path to the pockets directory.
        """
        return str(Path(POCKETS_BASE_DIR).expanduser())

    def update_coordinates(self, coords: np.ndarray):
        """update coordinates of the pocket"""

        self.coordinates = coords
