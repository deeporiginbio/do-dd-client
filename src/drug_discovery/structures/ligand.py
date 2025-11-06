"""
This module contains the Ligand and LigandSet classes, which allow you to work with ligands (molecules) in drug discovery workflows.
"""

import base64
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import random
import tempfile
from typing import Any, Literal, Optional
import warnings

from beartype import beartype
from deeporigin_molstar import MoleculeViewer
import numpy as np
import pandas as pd
from rdkit import Chem, RDLogger
from rdkit.Chem import AllChem, SaltRemover, rdMolDescriptors
from tqdm import tqdm

from deeporigin.drug_discovery.constants import LIGANDS_DIR
from deeporigin.drug_discovery.utilities.visualize import jupyter_visualization
from deeporigin.exceptions import DeepOriginException
from deeporigin.utils.constants import SUPPORTED_ATOM_SYMBOLS, number

from .entity import Entity

warnings.filterwarnings("ignore", category=UserWarning, module="rdkit")
RDLogger.DisableLog("rdApp.*")


FILE_FORMATS = Literal["mol", "mol2", "pdb", "pdbqt", "xyz", "sdf"]


@dataclass
class Ligand(Entity):
    """A class representing a ligand molecule in drug discovery workflows.

    The Ligand class provides functionality to create, manipulate, and analyze small molecules
    (ligands) in computational drug discovery. It supports various input formats and provides
    methods for property prediction, visualization, and file operations.

    """

    identifier: str | None = None
    file_path: str | None = None
    smiles: str | None = None
    block_type: str | None = None
    block_content: str | None = None
    name: str | None = None
    seed: int | None = None
    xref_protein: str | None = None
    xref_ins_code: str | None = None
    xref_residue_id: str | None = None
    xref_protein_chain_id: str | None = None
    save_to_file: bool = False
    properties: dict = field(default_factory=dict)
    mol: Chem.Mol | None = None

    # Additional attributes that are initialized in __post_init__
    available_for_docking: bool = field(init=False, default=True)

    _remote_path_base = "entities/ligands/"
    _preferred_ext = ".sdf"

    @classmethod
    @beartype
    def from_rdkit_mol(
        cls,
        mol: Chem.rdchem.Mol,
        name: Optional[str] = None,
        save_to_file: bool = False,
        **kwargs: Any,
    ):
        """
        Create a Ligand instance from an RDKit Mol object.

        Args:
            mol (Chem.rdchem.Mol): RDKit molecule object to convert to a Ligand
            name (str, optional): Name of the ligand. Defaults to "".
            save_to_file (bool, optional): Whether to save the ligand to file. Defaults to False.
            **kwargs: Additional arguments to pass to the constructor

        """
        # Get name from properties if available
        if mol.HasProp("_Name") and name is None:
            name = mol.GetProp("_Name")
        elif (
            name is None and "properties" in kwargs and "_Name" in kwargs["properties"]
        ):
            name = kwargs["properties"]["_Name"]

        return cls(
            mol=mol,
            name=name,
            save_to_file=save_to_file,
            **kwargs,
        )

    @classmethod
    def from_smiles(
        cls,
        smiles: str,
        name: str = "",
        save_to_file: bool = False,
        **kwargs: Any,
    ) -> "Ligand":
        """
        Create a Ligand instance from a SMILES string.

        Args:
            smiles (str): SMILES string representing the ligand
            name (str, optional): Name of the ligand. Defaults to "".
            save_to_file (bool, optional): Whether to save the ligand to file. Defaults to False.
            **kwargs: Additional arguments to pass to the constructor

        Returns:
            Ligand: A new Ligand instance


        """
        try:
            # Create a Molecule object from the SMILES string
            mol = Chem.MolFromSmiles(smiles)
        except Exception as e:
            raise DeepOriginException(
                f"Cannot create Ligand from SMILES string `{smiles}`: {str(e)}"
            ) from None

        if mol is None:
            raise DeepOriginException(
                f"Cannot create Ligand from SMILES string `{smiles}`"
            )

        return cls(
            mol=mol,
            smiles=smiles,
            name=name,
            save_to_file=save_to_file,
            **kwargs,
        )

    @classmethod
    def from_block_content(
        cls,
        block_content: str,
        block_type: str,
        name: str = "",
        save_to_file: bool = False,
        **kwargs: Any,
    ) -> "Ligand":
        """
        Create a Ligand instance from block content.

        Args:
            block_content (str): String containing the molecule data
            block_type (str): Format of the block content ('mol', 'mol2', 'sdf', 'pdb')
            name (str, optional): Name of the ligand. Defaults to "".
            save_to_file (bool, optional): Whether to save the ligand to file. Defaults to False.
            **kwargs: Additional arguments to pass to the constructor

        Returns:
            Ligand: A new Ligand instance
        """

        mol = cls.mol_from_block(block_type, block_content)

        return cls(
            block_content=block_content,
            block_type=block_type,
            mol=mol,
            name=name,
            save_to_file=save_to_file,
            **kwargs,
        )

    @classmethod
    def from_identifier(
        cls,
        identifier: str,
    ):
        """
        Create a Ligand instance from a compound name.

        Args:
            identifier (str): The identifier to resolve to a SMILES string.

        Raises:
            DeepOriginException: If no compound is found for the given name
            AssertionError: If neither smiles nor name is provided
        """

        import requests

        try:
            url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{identifier}/property/smiles/JSON"
            response = requests.get(url)
            data = response.json()
            smiles = data["PropertyTable"]["Properties"][0]["SMILES"]
        except Exception:
            raise DeepOriginException(
                f"Error resolving SMILES string of {identifier}. Pubchempy did not resolve SMILES"
            ) from None

        mol = Chem.MolFromSmiles(smiles)

        return cls(mol=mol, name=identifier)

    @classmethod
    @beartype
    def from_base64(
        cls,
        base64_string: str,
        name: str = "",
        save_to_file: bool = False,
        **kwargs: Any,
    ) -> "Ligand":
        """
        Create a Ligand instance from a base64 encoded SDF string.

        Args:
            base64_string (str): Base64 encoded SDF content
            name (str, optional): Name of the ligand. Defaults to "".
            save_to_file (bool, optional): Whether to save the ligand to file. Defaults to False.
            **kwargs: Additional arguments to pass to the constructor

        Returns:
            Ligand: A new Ligand instance

        Raises:
            DeepOriginException: If the base64 string cannot be decoded or parsed
        """
        import tempfile

        try:
            # Decode the base64 string
            sdf_content = base64.b64decode(base64_string)

            # Create a temporary file with the decoded content
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".sdf", delete=False
            ) as temp_file:
                temp_file.write(sdf_content)
                temp_file_path = temp_file.name

            # Create the ligand from the temporary SDF file
            ligand = cls.from_sdf(temp_file_path, **kwargs)

            # Set the name if provided
            if name:
                ligand.name = name

            # Clean up the temporary file
            import os

            os.remove(temp_file_path)

            return ligand

        except Exception as e:
            raise DeepOriginException(
                f"Failed to create Ligand from base64 string: {str(e)}"
            ) from None

    @classmethod
    def from_sdf(
        cls,
        file_path: str,
        *,
        sanitize: bool = True,
        remove_hydrogens: bool = False,
    ) -> "Ligand":
        """
        Create a single Ligand instance from an SDF file containing exactly one molecule.

        Args:
            file_path (str): The path to the SDF file.
            sanitize (bool): Whether to sanitize molecules. Defaults to True.
            remove_hydrogens (bool): Whether to remove hydrogens. Defaults to False.

        Returns:
            Ligand: The Ligand instance created from the SDF file.

        Raises:
            FileNotFoundError: If the file does not exist.
            DeepOriginException: If the file cannot be parsed correctly or contains more than one molecule.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"The file '{file_path}' does not exist.")

        ligands = []
        try:
            suppl = Chem.SDMolSupplier(
                str(path),
                sanitize=sanitize,
                removeHs=remove_hydrogens,
            )
            for idx, mol in enumerate(suppl, start=1):
                try:
                    if mol is None:
                        print(
                            f"Warning: Skipping molecule at index {idx} due to parsing error."
                        )
                        continue
                    ligand = cls.from_rdkit_mol(
                        mol,
                        properties=mol.GetPropsAsDict(),
                    )
                    ligands.append(ligand)
                except Exception as e:
                    print(
                        f"Error: Failed to create Ligand from SDF file molecule_idx = '{idx}': {str(e)}"
                    )
        except Exception as e:
            raise DeepOriginException(
                f"Failed to create Ligand from SDF file '{file_path}': {str(e)}"
            ) from e

        if len(ligands) != 1:
            raise DeepOriginException(
                f"SDF file '{file_path}' must contain exactly one molecule, but found {len(ligands)}. If you want to work with a set of ligands in a SDF file, use LigandSet.from_sdf instead."
            ) from None
        ligands[0].file_path = str(path)
        return ligands[0]

    def process_mol(self) -> None:
        """
        Clean the ligand molecule by removing hydrogens and sanitizing the structure.

        Raises:
            DeepOriginException: If salt removal or kekulization fails
        """
        remover = SaltRemover.SaltRemover()

        stripped_mol = remover.StripMol(self.mol)
        if stripped_mol is None:
            raise DeepOriginException("Salt removal failed.")

        try:
            Chem.Kekulize(stripped_mol, clearAromaticFlags=False)
        except Chem.KekulizeException as e:
            raise DeepOriginException("Kekulization failed.") from e

        self.mol = stripped_mol

    @beartype
    def prepare(self, *, remove_hydrogens: bool = False) -> "Ligand":
        """Prepare the ligand for downstream workflows.

        The routine performs the following using RDKit and internal utilities:
        - Salt removal
        - Kekulization
        - Validation of atom types against supported symbols

        Args:
            remove_hydrogens (bool): Whether to remove hydrogens from the SMILES representation.
                                   Defaults to False (preserve hydrogens).

        Returns:
            Ligand: The prepared ligand (self), for chaining.

        Raises:
            DeepOriginException: If preparation fails or unsupported atom types are present.
        """
        # Start from current molecule
        if self.mol is None:
            raise DeepOriginException("Ligand has no molecule to prepare.")

        # 1) Salt removal and kekulization (reuse process_mol)
        self.process_mol()

        # 2) Sanity sanitize and generate 2D coords if missing
        try:
            Chem.SanitizeMol(self.mol)
        except Exception:
            # Attempt to re-kekulize and sanitize again
            try:
                Chem.Kekulize(self.mol, clearAromaticFlags=False)
                Chem.SanitizeMol(self.mol)
            except Exception as e:
                raise DeepOriginException(f"Sanitization failed: {str(e)}") from e

        if not self.mol.GetConformers():
            AllChem.Compute2DCoords(self.mol)

        # 3) Validate atom types
        atom_symbols = [atom.GetSymbol() for atom in self.mol.GetAtoms()]
        unsupported = sorted(
            {sym for sym in atom_symbols if sym not in SUPPORTED_ATOM_SYMBOLS}
        )
        if unsupported:
            raise DeepOriginException(
                f"Unsupported atom types found in ligand: {', '.join(unsupported)}"
            )

        # Update smiles and properties to reflect prepared state
        if remove_hydrogens:
            self.smiles = Chem.MolToSmiles(Chem.RemoveHs(self.mol), canonical=True)
        else:
            self.smiles = Chem.MolToSmiles(self.mol, canonical=True)
        self.set_property("prepared", True)

        return self

    def get_heavy_atom_count(self) -> int:
        """
        Get the number of heavy atoms in the molecule.
        """
        return self.mol.GetNumHeavyAtoms()

    def is_charged(self) -> bool:
        """
        Check if the molecule is charged.
        """
        total_charge = sum(atom.GetFormalCharge() for atom in self.mol.GetAtoms())
        return total_charge != 0

    def get_conformer(self, conformer_id: int = 0):
        """
        Get a specific conformer of the molecule.

        Args:
            conformer_id (int): Conformer index
        """
        return self.mol.GetConformer(conformer_id)

    def get_conformer_id(self) -> int:
        """
        Get the ID of the current conformer.

        Returns:
            int: Conformer ID
        """
        return self.mol.GetConformer().GetId()

    def set_conformer_id(self, i=0):
        """
        Set the ID of the current conformer.

        Args:
            i (int): New conformer ID
        """
        self.mol.GetConformer().SetId(i)

    def embed(self, add_hydrogens: bool = True, seed: int = -1):
        """
        Generate 3D coordinates for the molecule.

        Args:
            add_hydrogens (bool): Whether to add hydrogens
            seed (int): Random seed for coordinate generation
        """
        if add_hydrogens:
            self.add_hydrogens()

        AllChem.EmbedMolecule(self.mol, randomSeed=seed)
        self.set_conformer_id(0)

    def add_hydrogens(self, add_coordinates: bool = True):
        """
        Add hydrogens to the molecule.

        Args:
            add_coordinates (bool): Whether to generate coordinates for added hydrogens
        """
        self.mol = Chem.AddHs(self.mol, addCoords=add_coordinates)

    def get_coordinates(self, i: int = 0):
        """
        Get the coordinates of atoms in a specific conformer.

        Args:
            i (int): Conformer index

        """
        conf = self.get_conformer(i)
        return conf.GetPositions()

    def get_species(self) -> list[str]:
        """
        Get the atomic symbols of all atoms in the molecule.

        Returns:
            list: List of atomic symbols
        """

        return [a.GetSymbol() for a in self.mol.GetAtoms()]

    @beartype
    def protonate(
        self,
        *,
        ph: number = 7.4,
        filter_percentage: number = 1.0,
    ):
        """
        Protonate the ligand at a given pH.

        Only the most abundant species is retained.
        """
        from deeporigin.functions.protonation import protonate

        data = protonate(
            smiles=self.smiles,
            ph=ph,
            filter_percentage=filter_percentage,
        )
        self.mol = Chem.MolFromSmiles(data["protonation_states"]["smiles_list"][0])

    def to_molblock(self) -> str:
        """
        Generate a MOL block representation of the molecule.

        Returns:
            str: MOL block string
        """
        return Chem.MolToMolBlock(self.mol)

    def get_formula(self) -> str:
        """
        Get the chemical formula of the molecule.
        """
        return rdMolDescriptors.CalcMolFormula(self.mol)

    def __post_init__(self):
        """
        Initialize a Ligand instance from an identifier, file path, SMILES string,
        block content, or direct Molecule object.
        """

        # check that a mol exists
        if self.mol is None:
            raise DeepOriginException(
                "mol must be provided when initializing from an identifier, file path, SMILES string, or block content."
            )

        self.process_mol()
        self.smiles = Chem.MolToSmiles(Chem.RemoveHs(self.mol), canonical=True)

        if not self.mol.GetConformers():
            AllChem.Compute2DCoords(self.mol)

        self.set_conformer_id()

        self.mol.SetProp("initial_smiles", Chem.MolToSmiles(Chem.RemoveHs(self.mol)))

        if self.name is None:
            self.name = "Unknown_Ligand"
        directory = Path(self._get_directory())
        if self.name == "Unknown_Ligand":
            num = len(list(directory.glob(f"{self.name}*")))
            self.name = f"{self.name}_{num + 1}"

        file_props = self.mol.GetPropsAsDict()

        for key, value in file_props.items():
            self.properties[key] = value

        self.available_for_docking = not self.contains_boron
        if self.save_to_file:
            self.write_to_file(output_format="sdf")

    @property
    def contains_boron(self) -> bool:
        """
        Check if the ligand contains boron atoms.

        Currently, ligands with boron atoms are not supported for docking.

        Returns:
            bool: True if the ligand contains boron atoms, False otherwise.
        """
        return any(atom.GetSymbol() == "B" for atom in self.mol.GetAtoms())

    @property
    def coordinates(self):
        if self.mol.GetNumConformers() == 0:
            return None
        return np.array(self.get_coordinates(0), dtype=np.float32)

    @property
    def atom_types(self):
        return self.get_species()

    def set_property(self, prop_name: str, prop_value):
        """
        Set a property for the ligand molecule.

        Parameters:
        - prop_name (str): Name of the property.
        - prop_value: Value of the property.


        """
        self.properties[prop_name] = prop_value
        self.mol.SetProp(prop_name, str(prop_value))

    def get_property(self, prop_name: str):
        """
        Get the value of a property for the ligand molecule.

        Parameters:
        - prop_name (str): Name of the property to retrieve.

        Returns:
        - The value of the property if it exists, otherwise None.


        """
        value = self.properties.get(prop_name)
        if value is not None:
            return value

        if self.mol.HasProp(prop_name):
            value = self.mol.GetProp(prop_name)
            self.properties[prop_name] = value
            return value

        return None

    @beartype
    def write_to_file(
        self,
        output_path: Optional[str] = None,
        output_format: Literal["mol", "sdf", "pdb"] = "sdf",
    ) -> str | Path:
        """
        Writes the ligand molecule to a file, including all properties.

        Parameters:
        - output_path (str): Path where the ligand will be written.
        - output_format (Literal[".mol", ".sdf", ".pdb", "mol", "sdf", "pdb"]): Format to write the ligand in.

        Raises:
            - DeepOriginException: If the file extension is unsupported.
            - Exception: If writing to the file fails.

        """
        try:
            if not output_path:
                output_path = str(
                    Path(self._get_directory()) / f"{self.name}.{output_format}"
                )

            path = Path(output_path)

            if self.name is not None:
                self.set_property("_Name", self.name)
            if self.smiles is not None:
                self.set_property("_SMILES", self.smiles)
            if self.properties:
                for prop_name, prop_value in self.properties.items():
                    self.set_property(prop_name, str(prop_value))

            if output_format == "pdb":
                pdb_block = Chem.MolToPDBBlock(self.mol)
                remark_lines = ""
                for prop_name, prop_value in self.mol.GetPropsAsDict().items():
                    remark_lines += f"REMARK   {prop_name}: {prop_value}\n"
                pdb_block_with_remarks = remark_lines + pdb_block
                path.write_text(pdb_block_with_remarks)
            elif output_format == "sdf":
                with tempfile.NamedTemporaryFile(
                    mode="w+", suffix=".sdf", delete=False
                ) as temp_file:
                    writer = Chem.SDWriter(temp_file.name)
                    writer.write(self.mol)
                    writer.close()
                    temp_file.flush()
                    temp_file.seek(0)
                    path.write_text(temp_file.read())
            elif output_format == "mol":
                mol_block = Chem.MolToMolBlock(self.mol)
                prop_lines = ""
                for prop_name, prop_value in self.mol.GetPropsAsDict().items():
                    prop_lines += f">  <{prop_name}>\n{prop_value}\n\n"
                mol_block_with_props = mol_block + "\n" + prop_lines
                path.write_text(mol_block_with_props)
            else:
                raise DeepOriginException(
                    f"Unsupported file extension '{output_format}'. Supported extensions are 'pdb', 'mol', 'sdf'."
                ) from None

            return output_path

        except Exception as e:
            raise DeepOriginException(
                f"Failed to write structure to file {output_path}: {str(e)}"
            ) from None

    @beartype
    def to_mol(self, output_path: Optional[str] = None) -> str | Path:
        """Write the ligand to a MOL file."""
        return self.write_to_file(output_path=output_path, output_format="mol")

    @beartype
    def to_sdf(self, output_path: Optional[str] = None) -> str:
        """Write the ligand to an SDF file."""

        if output_path is None:
            output_path = LIGANDS_DIR / (self.to_hash() + ".sdf")

        with open(output_path, "w+") as file:
            writer = Chem.SDWriter(file.name)
            writer.write(self.mol)
            writer.close()
            file.flush()
            file.seek(0)

        return str(output_path)

    @beartype
    def to_base64(self) -> str:
        """Convert the ligand to base64 encoded SDF format.

        Returns:
            str: Base64 encoded string of the SDF file content
        """

        # Create a temporary SDF file
        temp_sdf_path = self.to_sdf()

        # Read the file and encode to base64
        with open(temp_sdf_path, "rb") as f:
            sdf_content = f.read()
            base64_encoded = base64.b64encode(sdf_content).decode("utf-8")

        # Clean up the temporary file
        import os

        os.remove(temp_sdf_path)

        return base64_encoded

    @beartype
    def to_hash(self) -> str:
        """Convert the ligand to SHA256 hash of the SDF file content.

        Returns:
            str: SHA256 hash string of the SDF file content
        """

        # Create a temporary SDF file
        temp_sdf_path = self.to_sdf("__ligand_hash__.sdf")

        # Read the file in text mode, normalize newlines, and compute SHA256
        with open(temp_sdf_path, "r", newline="") as f:
            sdf_text = f.read()
            # Normalize all line endings to \n for OS-agnostic hashing
            normalized_text = sdf_text.replace("\r\n", "\n").replace("\r", "\n")
            # Ensure file ends with a single newline to avoid platform differences
            if not normalized_text.endswith("\n"):
                normalized_text = f"{normalized_text}\n"
            hash_object = hashlib.sha256(normalized_text.encode("utf-8"))
            hash_hex = hash_object.hexdigest()

        # Clean up the temporary file
        os.remove(temp_sdf_path)

        return hash_hex

    @beartype
    def to_pdb(self, output_path: Optional[str] = None) -> str | Path:
        """Write the ligand to a PDB file."""
        return self.write_to_file(output_path=output_path, output_format="pdb")

    @beartype
    def get_center(self) -> list[number]:
        """
        Get the center of the ligand based on its coordinates.

        Returns:
        - list: The center coordinates of the ligand.
        - None: If coordinates are not available.


        """
        if self.coordinates is None:
            raise DeepOriginException(
                "Warning: Coordinates are not available for this ligand."
            )
        center = self.coordinates.mean(axis=0)
        return [float(x) for x in center.tolist()]

    def draw(self):
        """
        Draw the contained rdkit molecule using rdkit methods

        """
        from rdkit.Chem.Draw import MolToImage

        return MolToImage(self.mol)

    def show(self) -> str:
        """
        Visualize the current state of the ligand molecule.

        Returns:
        - str: HTML representation of the visualization.

        Raises:
        - Exception: If visualization fails.


        """
        try:
            sdf_file = self.to_sdf()

            viewer = MoleculeViewer(str(sdf_file), format="sdf")
            ligand_config = viewer.get_ligand_visualization_config()
            html = viewer.render_ligand(ligand_config=ligand_config)

            from deeporigin.utils.notebook import render_html

            return render_html(html)
        except Exception as e:
            raise DeepOriginException(f"Visualization failed: {str(e)}") from e

    def _repr_html_(self) -> str:
        """
        Return the HTML representation of the object for Jupyter Notebook.

        Returns:
            str: The HTML content.
        """
        try:
            print(self.mol)
            return self.show()
        except Exception as e:
            print(f"Warning: Failed to generate HTML representation: {str(e)}")
            return self.__str__()

    def __str__(self) -> str:
        info_str = f"Name: {self.name}\nSMILES: {self.smiles}\nHeavy Atoms: {self.get_heavy_atom_count()}\n"
        if self.properties:
            info_str += "Properties:\n"
            for prop_name, prop_value in self.properties.items():
                info_str += f"  {prop_name}: {prop_value}\n"

        if self.xref_protein is not None:
            info_str += (
                f"Cross-reference Protein Chain ID: {self.xref_protein_chain_id}\n"
            )
            info_str += f"Cross-reference Residue ID: {self.xref_residue_id}\n"
            info_str += f"Cross-reference Insertion Code: {self.xref_ins_code}\n"

        return f"Ligand:\n  {info_str}"

    def __repr__(self) -> str:
        return self.__str__()

    @staticmethod
    def _get_directory() -> str:
        """
        Generates and ensures the existence of a directory for ligands.

        Returns:
            str: The path to the ligands directory (~/.deeporigin/ligands).
        """
        ligands_base_dir = Path.home() / ".deeporigin" / "ligands"
        ligands_base_dir.mkdir(parents=True, exist_ok=True)

        return str(ligands_base_dir)

    @beartype
    def admet_properties(self, use_cache: bool = True) -> dict:
        """
        Predict ADMET properties for the ligand using DO's molprops model.

        """

        from deeporigin.functions.molprops import molprops

        try:
            props = molprops(self.smiles, use_cache=use_cache)["properties"]
            for key, value in props.items():
                self.set_property(key, value)

            return props
        except Exception as e:
            raise DeepOriginException(
                f"Failed to predict ADMET properties: {str(e)}"
            ) from e

    def update_coordinates(self, coordinates: np.ndarray):
        """update coordinates of the ligand structure"""

        if self.mol.GetNumConformers() == 0:
            raise DeepOriginException("Ligand molecule has no conformers to update.")

        conformer = self.mol.GetConformer()
        mol_without_hs = Chem.RemoveHs(self.mol)

        conformer_no_hs = mol_without_hs.GetConformer()
        if coordinates.shape[0] != conformer.GetNumAtoms():
            if coordinates.shape[0] != conformer_no_hs.GetNumAtoms():
                raise DeepOriginException(
                    "Number of ligand atoms does not match the conformer's atom count."
                ) from None

        conformer.SetPositions(coordinates.astype(np.float64))

    @classmethod
    def mol_from_block(
        cls,
        block_type: str,
        block: str,
        sanitize: bool = True,
        remove_hs: bool = False,
    ) -> Chem.Mol:
        """
        Create a molecule from a block of text.

        Args:
            block_type (str): Type of the input block
            block (str): Text block containing molecular data
            sanitize (bool): Whether to sanitize the molecule
            remove_hs (bool): Whether to remove hydrogens

        Returns:
            Chem.Mol: RDKit molecule object
        """
        with tempfile.TemporaryFile(mode="w+") as temp_file:
            temp_file.write(block)
            temp_file.seek(0)  # Reset file pointer to beginning
            return cls.mol_from_file(
                file_type=block_type,
                file_path=temp_file.name,
                sanitize=sanitize,
                remove_hs=remove_hs,
            )

    @classmethod
    def mol_from_file(
        cls,
        *,
        file_type: FILE_FORMATS,
        file_path: str,
        sanitize: bool = True,
        remove_hs: bool = False,
    ) -> Chem.Mol:
        """
        Create a molecule from a file.

        Args:
            file_type (str): Type of the input file (must be in FILE_FORMATS)
            file_path (str): Path to the input file
            sanitize (bool): Whether to sanitize the molecule
            remove_hs (bool): Whether to remove hydrogens

        Returns:
            Chem.Mol: RDKit molecule object

        Raises:
            DeepOriginException: If the file format is invalid or parsing fails
            NotImplementedError: If the file type is not supported
        """

        mol_rdk = None

        if file_type == "mol":
            mol_rdk = Chem.MolFromMolFile(file_path, sanitize, remove_hs)
        elif file_type == "mol2":
            mol_rdk = Chem.MolFromMol2File(file_path, sanitize, remove_hs)
        elif file_type == "pdb":
            mol_rdk = Chem.MolFromPDBFile(file_path, sanitize, remove_hs)
        elif file_type == "xyz":
            mol_rdk = Chem.MolFromXYZFile(file_path)
            if sanitize:
                Chem.SanitizeMol(mol_rdk)
            if remove_hs:
                mol_rdk = Chem.RemoveHs(mol_rdk)
        elif file_type == "sdf":
            mol_rdk = next(iter(Chem.SDMolSupplier(file_path, sanitize, remove_hs)))

        if mol_rdk is None:
            raise DeepOriginException(
                "Invalid file format or file path or failed to sanitize the molecule"
            )

        return mol_rdk


@beartype
def ligands_to_dataframe(ligands: list[Ligand]):
    """convert a list of ligands to a pandas dataframe"""

    import pandas as pd

    data = {}

    # find the union of all properties in all ligands
    all_keys = set()
    for ligand in ligands:
        all_keys.update(ligand.properties.keys())
    for key in all_keys:
        if key == "_Name" or key == "_SMILES" or key == "initial_smiles":
            continue
        data[key] = [ligand.properties.get(key, None) for ligand in ligands]

    return pd.DataFrame(data)


@dataclass
class LigandSet:
    """
    A class representing a set of Ligand objects.

    Attributes:
        ligands (list[Ligand]): A list of Ligand instances contained in the set.
        network (dict): A dictionary containing the network of ligands estimated using Konnektor.

    """

    ligands: list[Ligand] = field(default_factory=list)
    network: dict = field(default_factory=dict)

    def __len__(self):
        return len(self.ligands)

    def __iter__(self):
        return iter(self.ligands)

    def __getitem__(self, index) -> "Ligand | LigandSet":
        """
        Get a single ligand or a subset of ligands.

        Args:
            index: Integer index for single ligand, or slice for subset

        Returns:
            Ligand: If index is a single integer
            LigandSet: If index is a slice (e.g., [1:3], [:2], etc.)

        Examples:
            >>> ligands = LigandSet([ligand1, ligand2, ligand3])
            >>> ligands[0]      # Returns: Ligand
            >>> ligands[1:3]    # Returns: LigandSet
            >>> ligands[:2]     # Returns: LigandSet
        """
        result = self.ligands[index]

        # If result is a list (from slicing), return a new LigandSet
        if isinstance(result, list):
            return LigandSet(ligands=result)

        # If result is a single Ligand, return it directly
        return result

    def __contains__(self, ligand):
        return ligand in self.ligands

    def __add__(self, other):
        """Add another LigandSet or a Ligand to this LigandSet, returning a new LigandSet."""

        if isinstance(other, LigandSet):
            return LigandSet(ligands=self.ligands + other.ligands)
        elif isinstance(other, Ligand):
            return LigandSet(ligands=self.ligands + [other])
        elif isinstance(other, list):
            return LigandSet(ligands=self.ligands + other)
        else:
            return NotImplemented

    def __radd__(self, other):
        """Support Ligand + LigandSet, returning a new LigandSet."""

        if isinstance(other, Ligand):
            return LigandSet(ligands=[other] + self.ligands)
        elif isinstance(other, list):
            return LigandSet(ligands=other + self.ligands)
        else:
            return NotImplemented

    @beartype
    def random_sample(self, n: int) -> "LigandSet":
        """
        Return a new LigandSet containing n randomly selected ligands.

        Args:
            n (int): Number of ligands to randomly sample

        Returns:
            LigandSet: A new LigandSet with n randomly selected ligands

        Raises:
            ValueError: If n is greater than the total number of ligands
        """

        if n < 1:
            raise ValueError("n must be at least 1")
        if n > len(self.ligands):
            raise ValueError(
                f"Cannot sample {n} ligands from a set of {len(self.ligands)} ligands"
            )

        sampled_ligands = random.sample(self.ligands, n)  # NOSONAR
        return LigandSet(ligands=sampled_ligands)

    def _repr_html_(self):
        """Return an HTML representation of the LigandSet."""

        return self.show_df().to_html()

    def to_dataframe(self) -> pd.DataFrame:
        """Convert the LigandSet to a pandas DataFrame."""

        if len(self.ligands) == 0:
            return pd.DataFrame()

        return ligands_to_dataframe(self.ligands)

    def show_df(self):
        """Show ligands in the set in a dataframe with 2D visualizations."""

        df = self.to_dataframe()

        if len(df) == 0:
            print("Empty LigandSet")
            return df

        from rdkit.Chem import PandasTools

        PandasTools.AddMoleculeColumnToFrame(df, smilesCol="Ligand", molCol="Ligand")
        PandasTools.RenderImagesInAllDataFrames()

        # show structure first
        new_order = ["Ligand"] + [col for col in df.columns if col != "Ligand"]

        # re‑index your DataFrame
        df = df[new_order]

        return df

    @classmethod
    def from_rdkit_mols(cls, mols: list[Chem.rdchem.Mol]):
        """Create a LigandSet from a list of RDKit molecules."""

        ligands = []
        for mol in mols:
            ligand = Ligand.from_rdkit_mol(
                mol,
                properties=mol.GetPropsAsDict(),
            )
            ligands.append(ligand)

        return cls(ligands=ligands)

    @classmethod
    def from_csv(
        cls,
        file_path: str,
        smiles_column: str = "smiles",
    ) -> "LigandSet":
        """
        Create a LigandSet instance from a CSV file containing SMILES strings and additional properties.

        Args:
            file_path (str): The path to the CSV file.
            smiles_column (str, optional): The name of the column containing SMILES strings. Defaults to "smiles".

        Returns:
            LigandSet: A LigandSet instance containing Ligand objects created from the CSV file.

        Raises:
            FileNotFoundError: If the file does not exist.
            DeepOriginException: If the CSV does not contain the specified smiles column or if SMILES strings are invalid.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"The file '{file_path}' does not exist.")

        # First read just the header to check for the smiles column
        df_header = pd.read_csv(file_path, nrows=0)
        if smiles_column not in df_header.columns:
            # Try case-insensitive match
            lower_to_actual = {col.lower(): col for col in df_header.columns}
            if smiles_column.lower() in lower_to_actual:
                smiles_column = lower_to_actual[smiles_column.lower()]
            else:
                raise DeepOriginException(
                    f"Column '{smiles_column}' not found in CSV file '{file_path}'. Available columns: {', '.join(df_header.columns)}"
                )

        ligands = []
        try:
            df = pd.read_csv(file_path)
            normalized_columns = [col.strip().lower() for col in df.columns]

            if smiles_column.lower() not in normalized_columns:
                raise DeepOriginException(
                    f"CSV file must contain a '{smiles_column}' column."
                )

            smiles_col_index = normalized_columns.index(smiles_column.lower())
            smiles_col = df.columns[smiles_col_index]
            other_columns = [col for col in df.columns if col != smiles_col]

            for idx, row in df.iterrows():
                try:
                    smiles = row[smiles_col]
                    if pd.isna(smiles):
                        print(
                            f"Warning: Skipping row {idx + 1}: SMILES value is missing."
                        )
                        continue
                    mol = Chem.MolFromSmiles(smiles)
                    if mol is None:
                        print(
                            f"Warning: Skipping row {idx + 1}: Invalid SMILES '{smiles}'."
                        )
                        continue

                    # Create properties dictionary
                    properties = {}
                    for col in other_columns:
                        value = row[col]
                        if pd.notna(value):
                            properties[col] = value

                    # Get name from properties if available
                    name = properties.get("Name", "")

                    # Create ligand using from_smiles
                    ligand = Ligand.from_smiles(
                        smiles=smiles,
                        name=name,
                        properties=properties,
                    )
                    ligands.append(ligand)
                except Exception as e:
                    print(
                        f"Error: Failed to create Ligand from CSV file row {idx + 1}: {str(e)}"
                    )

        except pd.errors.EmptyDataError as e:
            raise DeepOriginException(f"The CSV file '{file_path}' is empty.") from e
        except pd.errors.ParserError as e:
            raise DeepOriginException(
                f"Error parsing CSV file '{file_path}': {str(e)}"
            ) from e
        except Exception as e:
            raise DeepOriginException(
                f"Failed to create Ligands from CSV file '{file_path}': {str(e)}"
            ) from e

        return cls(ligands=ligands)

    @classmethod
    def from_sdf(
        cls,
        file_path: str,
        *,
        sanitize: bool = True,
        remove_hydrogens: bool = False,
    ) -> "LigandSet":
        """
        Create a LigandSet instance from an SDF file containing one or more molecules.

        Args:
            file_path (str): The path to the SDF file.
            sanitize (bool): Whether to sanitize molecules. Defaults to True.
            remove_hydrogens (bool): Whether to remove hydrogens. Defaults to False.

        Returns:
            LigandSet: A LigandSet instance containing Ligand objects created from the SDF file.

        Raises:
            FileNotFoundError: If the file does not exist.
            DeepOriginException: If the file cannot be parsed correctly.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"The file '{file_path}' does not exist.")

        ligands = []
        try:
            suppl = Chem.SDMolSupplier(
                str(path),
                sanitize=sanitize,
                removeHs=remove_hydrogens,
            )
            for idx, mol in enumerate(suppl, start=1):
                try:
                    if mol is None:
                        print(
                            f"Warning: Skipping molecule at index {idx} due to parsing error."
                        )
                        continue
                    ligand = Ligand.from_rdkit_mol(
                        mol,
                        properties=mol.GetPropsAsDict(),
                    )
                    ligands.append(ligand)
                except Exception as e:
                    print(
                        f"Error: Failed to create Ligand from SDF file molecule_idx = '{idx}': {str(e)}"
                    )
        except Exception as e:
            raise DeepOriginException(
                f"Failed to create Ligands from SDF file '{file_path}': {str(e)}"
            ) from e

        return cls(ligands=ligands)

    @classmethod
    def from_sdf_files(
        cls,
        file_paths: list[str],
        *,
        sanitize: bool = True,
        remove_hydrogens: bool = False,
    ) -> "LigandSet":
        """
        Create a LigandSet instance from multiple SDF files by concatenating them together.

        Args:
            file_paths (list[str]): A list of paths to SDF files.
            sanitize (bool): Whether to sanitize molecules. Defaults to True.
            remove_hydrogens (bool): Whether to remove hydrogens. Defaults to False.

        Returns:
            LigandSet: A LigandSet instance containing Ligand objects from all SDF files.

        Raises:
            FileNotFoundError: If any of the files do not exist.
            DeepOriginException: If any of the files cannot be parsed correctly.
        """
        all_ligands = []

        for file_path in file_paths:
            try:
                # Use the existing from_sdf method for each file
                file_ligand_set = cls.from_sdf(
                    file_path, sanitize=sanitize, remove_hydrogens=remove_hydrogens
                )
                all_ligands.extend(file_ligand_set.ligands)
            except FileNotFoundError as e:
                # Re-raise with more context
                raise FileNotFoundError(
                    f"Failed to process file '{file_path}': {str(e)}"
                ) from e
            except DeepOriginException as e:
                # Re-raise with more context
                raise DeepOriginException(
                    f"Failed to process file '{file_path}': {str(e)}"
                ) from e
            except Exception as e:
                # Catch any other unexpected errors
                raise DeepOriginException(
                    f"Unexpected error processing file '{file_path}': {str(e)}"
                ) from e

        return cls(ligands=all_ligands)

    @classmethod
    def from_dir(cls, directory: str) -> "LigandSet":
        """
        Create a LigandSet instance from a directory containing SDF files.
        """
        sdf_files = [f for f in os.listdir(directory) if f.endswith(".sdf")]
        ligands = []
        for sdf_file in sdf_files:
            this_file = os.path.join(directory, sdf_file)
            this_set = cls.from_sdf(this_file)
            for ligand in this_set.ligands:
                ligand.file_path = this_file
            ligands.extend(this_set.ligands)

        #  now get all CSV files
        csv_files = [f for f in os.listdir(directory) if f.endswith(".csv")]
        for csv_file in csv_files:
            this_file = os.path.join(directory, csv_file)
            this_set = cls.from_csv(this_file)
            for ligand in this_set.ligands:
                ligand.file_path = this_file
            ligands.extend(this_set)

        return cls(ligands=ligands)

    def add_hydrogens(self) -> None:
        """Add hydrogens to all ligands in the set."""
        for ligand in self.ligands:
            ligand.add_hydrogens()

    @jupyter_visualization
    def show(self):
        """
        Visualize all ligands in this LigandSet in 3D
        """

        sdf_file = self.to_sdf()

        try:
            viewer = MoleculeViewer(str(sdf_file), format="sdf")
            ligand_config = viewer.get_ligand_visualization_config()
            html = viewer.render_ligand(ligand_config=ligand_config)

            from deeporigin.utils.notebook import render_html

            return render_html(html)
        except Exception as e:
            raise DeepOriginException(f"Visualization failed: {str(e)}") from e

    @beartype
    def show_grid(
        self,
        mols_per_row: int = 3,
        sub_img_size: tuple[int, int] = (300, 300),
    ):
        """show all ligands in the LigandSet in a grid"""

        from rdkit.Chem.Draw import MolsToGridImage

        return MolsToGridImage(
            self.to_rdkit_mols(),
            legends=self.to_smiles(),
            molsPerRow=mols_per_row,
            subImgSize=sub_img_size,
        )

    def embed(self):
        """
        Minimize all ligands in the set using their 3D optimization routines.
        This calls the embed() method on each Ligand in the set.
        """
        for ligand in self.ligands:
            ligand.embed()
        return self

    @beartype
    def protonate(
        self,
        *,
        ph: number = 7.4,
        filter_percentage: number = 1.0,
    ):
        """
        Protonate the ligandSet. Only the most abundant species is retained for each ligand.
        """
        for ligand in tqdm(self.ligands, desc="Protonating ligands", unit="ligand"):
            ligand.protonate(ph=ph, filter_percentage=filter_percentage)
        return self

    @beartype
    def admet_properties(self, use_cache: bool = True):
        """
        Predict ADMET properties for all ligands in the set.
        This calls the admet_properties() method on each Ligand in the set.
        Returns a list of the results for each ligand.
        Shows a progress bar using tqdm.
        """

        for ligand in tqdm(self.ligands, desc="Predicting ADMET properties"):
            ligand.admet_properties(use_cache=use_cache)
        return self

    @beartype
    def to_sdf(self, output_path: Optional[str] = None) -> str:
        """
        Write all ligands in the set to a single SDF file, preserving all properties from each Ligand's mol field.

        Args:
            output_path (str): The path to the output SDF file.

        Returns:
            str: The path to the written SDF file.
        """
        from pathlib import Path

        from rdkit import Chem

        if output_path is None:
            output_path = f"{tempfile.mkstemp()[1]}.sdf"

        path = Path(output_path)
        writer = Chem.SDWriter(str(path))
        try:
            for ligand in self.ligands:
                # Ensure all properties are set on the RDKit Mol object
                if ligand.name is not None:
                    ligand.set_property("_Name", ligand.name)
                if ligand.smiles is not None:
                    ligand.set_property("_SMILES", ligand.smiles)
                if ligand.properties:
                    for prop_name, prop_value in ligand.properties.items():
                        ligand.set_property(prop_name, str(prop_value))
                writer.write(ligand.mol)
            return str(path)
        except Exception as e:
            raise DeepOriginException(
                f"Failed to write LigandSet to SDF file {output_path}: {str(e)}"
            ) from None
        finally:
            writer.close()

    def to_smiles(self) -> list[str]:
        """
        Convert all ligands in the set to SMILES strings.
        """
        return [ligand.smiles for ligand in self.ligands]

    @beartype
    @classmethod
    def from_smiles(cls, smiles: list[str] | set[str]) -> "LigandSet":
        """
        Create a LigandSet from a list of SMILES strings.
        """

        return cls(ligands=[Ligand.from_smiles(s) for s in smiles])

    def map_network(
        self,
        *,
        use_cache: bool = True,
        operation: Literal["mapping", "network", "full"] = "network",
        network_type: Literal["star", "mst", "cyclic"] = "mst",
    ):
        """
        Map a network of ligands from an SDF file using the DeepOrigin API.
        """
        from deeporigin.functions.rbfe_tools import map_network

        self.network = map_network(
            sdf_file=self.to_sdf(),
            use_cache=use_cache,
            operation=operation,
            network_type=network_type,
        )

        return self

    def show_network(self):
        """
        Show the network of ligands in the set.
        """

        if "network_html" not in self.network.keys():
            raise DeepOriginException(
                "Network not mapped yet. Please map the network first using `map_network()`."
            ) from None

        from IPython.display import IFrame, display

        file_name = "network.html"
        try:
            with open(file_name, "w") as file:
                file.write(self.network["network_html"])
            display(IFrame(file_name, width=1000, height=1000))
        except Exception as e:
            raise DeepOriginException(f"Failed to display network: {e}") from None

    def to_rdkit_mols(self) -> list[Chem.Mol]:
        """
        Convert all ligands in the set to RDKit molecules.
        """
        return [ligand.mol for ligand in self.ligands]

    def mcs(self) -> str:
        """
        Generates the Most Common Substructure (MCS) for ligands in a LigandSet

        Returns:
            smartsString (str) : SMARTS string representing the MCS

        """

        from deeporigin.drug_discovery import align

        return align.mcs(self.to_rdkit_mols())

    @beartype
    def filter_top_poses(self, *, by_pose_score: bool = False) -> "LigandSet":
        """
        Filter ligands to keep only the best pose for each unique molecule.

        Groups ligands by SMILES string and retains only the one with:
        - Minimum binding energy (default), or
        - Maximum pose score (when by_pose_score=True)

        Args:
            by_pose_score (bool): If True, select by maximum pose score.
                                If False (default), select by minimum binding energy.

        Returns:
            LigandSet: A new LigandSet containing only the best pose for each unique molecule.

        Raises:
            DeepOriginException: If required properties are missing from ligands.

        Example:
            >>> # Filter by binding energy (default)
            >>> filtered_ligands = ligand_set.filter_top_poses()

            >>> # Filter by pose score
            >>> filtered_ligands = ligand_set.filter_top_poses(by_pose_score=True)
        """
        if not self.ligands:
            return LigandSet(ligands=[])

        # Group ligands by smiles
        grouped_ligands = {}
        for ligand in self.ligands:
            initial_smiles = ligand.properties.get("SMILES")
            if initial_smiles is None:
                # Skip ligands without initial_smiles property
                continue

            if initial_smiles not in grouped_ligands:
                grouped_ligands[initial_smiles] = []
            grouped_ligands[initial_smiles].append(ligand)

        # Select best pose for each group
        best_ligands = []
        for ligands in grouped_ligands.values():
            if len(ligands) == 1:
                # Only one pose, keep it
                best_ligands.append(ligands[0])
            else:
                # Multiple poses, select the best one
                if by_pose_score:
                    # Select by maximum pose score
                    best_ligand = max(ligands, key=lambda x: self._get_pose_score(x))
                else:
                    # Select by minimum binding energy
                    best_ligand = min(
                        ligands, key=lambda x: self._get_binding_energy(x)
                    )
                best_ligands.append(best_ligand)

        return LigandSet(ligands=best_ligands)

    def _get_pose_score(self, ligand: "Ligand") -> number:
        """
        Extract pose score from ligand properties.

        Args:
            ligand: The ligand to extract pose score from.


        Raises:
            DeepOriginException: If pose score property is missing or invalid.
        """
        pose_score_str = ligand.properties.get("POSE SCORE")
        if pose_score_str is None:
            raise DeepOriginException(
                f"Ligand {ligand.name or 'unnamed'} missing 'POSE SCORE' property"
            )

        try:
            return float(pose_score_str)
        except (ValueError, TypeError) as e:
            raise DeepOriginException(
                f"Invalid pose score value '{pose_score_str}' for ligand {ligand.name or 'unnamed'}: {str(e)}"
            ) from e

    def _get_binding_energy(self, ligand: "Ligand") -> number:
        """
        Extract binding energy from ligand properties.

        Args:
            ligand: The ligand to extract binding energy from.

        Returns:
            number: The binding energy value.

        Raises:
            DeepOriginException: If binding energy property is missing or invalid.
        """
        binding_energy_str = ligand.properties.get("Binding Energy")
        if binding_energy_str is None:
            raise DeepOriginException(
                f"Ligand {ligand.name or 'unnamed'} missing 'Binding Energy' property"
            )

        try:
            return float(binding_energy_str)
        except (ValueError, TypeError) as e:
            raise DeepOriginException(
                f"Invalid binding energy value '{binding_energy_str}' for ligand {ligand.name or 'unnamed'}: {str(e)}"
            ) from e

    def compute_constraints(
        self, *, reference: Ligand, mcs_mol=None
    ) -> list[list[dict]]:
        """
        Align a set of ligands to a reference ligand
        """
        from deeporigin.drug_discovery import align

        if mcs_mol is None:
            mcs_mol = self.mcs()

        return align.compute_constraints(
            mols=self.to_rdkit_mols(),
            reference=reference.mol,
            mcs_mol=mcs_mol,
        )

    def compute_rmsd(self):
        """compute pairwise rmsd between all ligands in the set"""

        from deeporigin.drug_discovery import chemistry

        return chemistry.pairwise_pose_rmsd(self.to_rdkit_mols())

    def plot(
        self,
        *,
        x_label: str = "Pose Score",
        y_label: str = "Binding Energy (kcal/mol)",
        x="POSE SCORE",
        y="Binding Energy",
    ):
        """
        Create a scatter plot of ligands using specified attributes for the axes.

        Args:
            x (str, optional): The name of the ligand property to use for the x-axis. Defaults to "POSE SCORE".
            y (str, optional): The name of the ligand property to use for the y-axis. Defaults to "Binding Energy".



        """
        from deeporigin.plots import scatter

        df = self.to_dataframe()

        return scatter(
            x=df[x],
            y=df[y],
            smiles_list=df["SMILES"],
            x_label=x_label,
            y_label=y_label,
            title="Binding Energy vs POSE SCORE",
        )
