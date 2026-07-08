"""
Protein Module

This module encapsulates the Protein class, which is responsible for managing and manipulating
protein structures in computational biology workflows. It provides functionalities to load protein data
from various sources, preprocess structures, handle ligands, and visualize protein-ligand interactions.

"""

from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
import io
import os
from pathlib import Path
import tempfile
from typing import Any, Optional, Self

from beartype import beartype
import Bio.Seq
import numpy as np

from deeporigin.drug_discovery.constants import (
    METAL_ELEMENTS,
    METALS,
    PROTEINS_DIR,
    STATE_DUMP_PATH,
)
from deeporigin.drug_discovery.utils.structure_qc import _any_ligand_protein_clashes
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.env import _ensure_do_folder

from .entity import Entity
from .ligand import Ligand, LigandSet
from .pocket import Pocket

_PROTEIN_STRUCTURE_NOT_LOADED_MSG = "Protein structure is not loaded."


@dataclass
@beartype
class Protein(Entity):
    """A class representing a protein structure with various manipulation and analysis capabilities."""

    # Core attributes (``structure`` is None until a local file is loaded or :meth:`download` runs.)
    name: str
    structure: Any | None = field(default=None, repr=False)
    pdb_id: Optional[str] = None
    info: Optional[dict] = None
    atom_types: Optional[np.ndarray] = None
    block_type: str = "pdb"
    block_content: Optional[str] = None

    _remote_path_base = "entities/proteins/"
    _preferred_ext = ".pdb"

    @classmethod
    def from_name(cls, name: str) -> Self:
        """
        Create a Protein instance from a name.
        """

        from rcsbapi.search import TextQuery

        query = TextQuery(value=name)
        results = query()
        pdb_id = results.to_dict()["result_set"][0]  # top hit

        return cls.from_pdb_id(pdb_id)

    @classmethod
    def from_id(
        cls,
        id: str,
        *,
        client: Optional[DeepOriginClient] = None,
        download: bool = True,
        remote_path_override: Optional[str] = None,
    ) -> Self:
        """
        Create a Protein instance from a Deep Origin Data Platform ID.

        Args:
            id: The Deep Origin Data Platform ID of the protein.
            client: Optional DeepOriginClient instance. If not provided, uses the default client.
            download: If True (default), download the structure file and load coordinates
                when the record has a ``file_path``. If False, fetch metadata only and set
                :attr:`remote_path` to the platform file path (``remote_path_override`` or
                the record's ``file_path``) without downloading; :attr:`structure` stays
                ``None`` until :meth:`download` or :meth:`load_structure_from_local`.
                When the record has no ``file_path``, returns metadata only regardless of
                ``download``.
            remote_path_override: When ``download`` is False, use this as ``remote_path``
                instead of the API record's ``file_path`` (e.g. the path stored on the
                execution ``userInputs``).

        Returns:
            Protein: A new Protein instance.

        Raises:
            RuntimeError: If the file cannot be downloaded or loaded.
        """
        if client is None:
            client = DeepOriginClient()

        data = client.entities.get_protein(id=id)

        file_path = data.get("file_path")
        if not file_path or not download:
            remote_path: str | None = None
            if file_path:
                remote_path = (
                    remote_path_override
                    if remote_path_override is not None
                    else file_path
                )
            elif remote_path_override is not None:
                remote_path = remote_path_override
            name = (
                data.get("protein_name")
                or data.get("pdb_id")
                or data.get("gene_symbol")
                or id
            )
            return cls(
                name=name,
                structure=None,
                pdb_id=data.get("pdb_id"),
                info=None,
                atom_types=None,
                block_type="pdb",
                block_content=None,
                id=data.get("id"),
                remote_path=remote_path,
                project_id=str(data["project_id"])
                if data.get("project_id") is not None
                else None,
            )

        # Download the file
        local_file_path = client.files.download(remote_path=file_path, lazy=True)

        # Create Protein instance from the downloaded file
        protein = cls.from_file(file_path=local_file_path)
        protein.remote_path = file_path

        # Set the ID from the data
        protein.id = data.get("id")

        # Update fields from the data
        if data.get("protein_name"):
            protein.name = data["protein_name"]
        elif data.get("pdb_id"):
            protein.name = data["pdb_id"]
        elif data.get("gene_symbol"):
            protein.name = data["gene_symbol"]

        if data.get("pdb_id"):
            protein.pdb_id = data["pdb_id"]

        if data.get("project_id") is not None:
            protein.project_id = str(data["project_id"])

        return protein

    def _hydrate_structure_from_file(self, path: str | Path) -> None:
        """Populate :attr:`structure` and related fields from a local structure file."""
        path = Path(path)
        loaded = Protein.from_file(path)
        self.structure = loaded.structure
        self.local_path = loaded.local_path
        self.atom_types = loaded.atom_types
        self.block_type = loaded.block_type
        self.block_content = loaded.block_content

    def download(
        self,
        *,
        lazy: bool = True,
        client: DeepOriginClient | None = None,
    ) -> str:
        """Download the remote structure file and load :attr:`structure` from it.

        If :attr:`structure` is already loaded (e.g. from :meth:`from_pdb_id` or
        :meth:`from_file`), returns :attr:`local_path` when set without hitting
        the files API.

        Otherwise delegates to :meth:`Entity.download`, then parses the returned
        path with :meth:`from_file` when :attr:`structure` is still ``None``.

        Args:
            client: DeepOriginClient instance. If None, uses the default client.

        Returns:
            Local file path returned by the files client, or an existing on-disk
            path when the structure was already loaded from a local file.
        """
        if self.structure is not None:
            if self.local_path is not None:
                return self.local_path
            raise ValueError(
                "Structure is loaded but no local file path is set; set local_path "
                "or reload via download() to obtain a valid path."
            )

        path_str = super().download(client=client, lazy=lazy)
        self._hydrate_structure_from_file(path_str)
        return path_str

    def load_structure_from_local(self, path: str | Path | None = None) -> None:
        """Load :attr:`structure` from disk without using the remote API.

        Args:
            path: Path to a PDB/mmCIF file. If None, uses :attr:`local_path`
                (see :class:`Entity`).
        """
        if path is not None:
            self._hydrate_structure_from_file(path)
            return
        if self.local_path is not None:
            self._hydrate_structure_from_file(self.local_path)
            return
        raise ValueError("No local file path; pass path= or set local_path first.")

    @classmethod
    def from_pdb_id(cls, pdb_id: str, struct_ind: int = 0) -> Self:
        """
        Create a Protein instance from a PDB ID.

        Args:
            pdb_id (str): PDB ID of the protein to download.
            struct_ind (int): Index of the structure to select if multiple are present.

        Returns:
            Protein: A new Protein instance.

        Raises:
            ValueError: If the PDB ID is invalid or the structure cannot be loaded.
            RuntimeError: If the download fails.
        """
        try:
            # Download logic (merged from download_protein_by_pdb_id)

            from deeporigin.utils.network import download_sync

            pdb_id_lower = pdb_id.lower()

            # Get directory for storing protein files
            proteins_dir = _ensure_do_folder() / "proteins"
            proteins_dir.mkdir(parents=True, exist_ok=True)
            file_path = proteins_dir / f"{pdb_id_lower}.pdb"
            if not file_path.exists():
                pdb_url = f"https://files.rcsb.org/download/{pdb_id_lower}.pdb"
                download_sync(pdb_url, file_path)

            file_path = file_path.absolute()
            block_content = file_path.read_text()
            structure = cls.load_structure_from_block(block_content, "pdb")
            structure = cls.select_structure(structure, struct_ind)

            from deeporigin.drug_discovery.external_tools.protein_info import (
                get_protein_info_dict,
            )

            return cls(
                name=pdb_id,
                structure=structure,
                local_path=str(file_path),
                pdb_id=pdb_id,
                info=get_protein_info_dict(pdb_id),
                atom_types=structure.atom_name,
                block_content=block_content,
            )
        except Exception as e:
            # if something goes wrong, delete the file, because it did not lead to a valid protein
            try:
                file_path.unlink()
            except Exception:
                pass
            raise DeepOriginException(
                title="Failed to download protein from PDB",
                message=f"Failed to create Protein from PDB ID `{pdb_id}`: {str(e)}. The RCSB API appears to be down.",
            ) from None

    @classmethod
    def from_file(
        cls,
        file_path: str | Path,
        struct_ind: int = 0,
        *,
        validate: bool = True,
    ) -> Self:
        """
        Create a Protein instance from a file.

        Args:
            file_path (str): Path to the protein PDB or CIF file.
            struct_ind (int): Index of the structure to select if multiple are present.

        Returns:
            Protein: A new Protein instance.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file type is unsupported or the structure cannot be loaded.
            RuntimeError: If the file cannot be read or processed.
        """
        file_path = Path(file_path).absolute()
        if not file_path.exists():
            raise FileNotFoundError(f"The file {file_path} does not exist.")

        block_type = file_path.suffix.lstrip(".").lower()
        if block_type not in ["pdb", "pdbqt", "cif"]:
            raise ValueError(
                f"Unsupported file type: {block_type}. Supported types are: pdb, pdbqt, cif"
            )

        # validate PDB files
        if block_type == "pdb" and validate:
            validate_pdb_file(file_path)
        try:
            block_content = file_path.read_text()
            structure = cls.load_structure_from_block(block_content, block_type)
            structure = cls.select_structure(structure, struct_ind)

            return cls(
                name=file_path.stem,
                structure=structure,
                local_path=str(file_path),
                atom_types=structure.atom_name,
                block_type=block_type,
                block_content=block_content,
            )
        except (FileNotFoundError, ValueError):
            raise
        except Exception as e:
            raise RuntimeError(
                f"Failed to create Protein from file {file_path}: {str(e)}"
            ) from e

    @classmethod
    def from_remote_file(
        cls,
        remote_path: str,
        *,
        client: DeepOriginClient | None = None,
        lazy: bool = True,
        struct_ind: int = 0,
        validate: bool = True,
    ) -> Self:
        """Create a Protein from a structure file stored on the platform.

        Downloads the file via :meth:`deeporigin.platform.files.FilesClient.download`,
        then loads it with :meth:`from_file`. Supported formats are PDB, PDBQT, and mmCIF.

        Args:
            remote_path: Platform file path (e.g. org storage path) to the structure file.
            client: DeepOrigin client used for download. If ``None``, uses
                ``DeepOriginClient()``.
            lazy: Passed to ``files.download``; if ``True``, skip download when the
                file already exists locally at the default cache location.
            struct_ind: Index of the structure to select if multiple are present (see
                :meth:`from_file`).
            validate: Whether to validate PDB files when reading (see :meth:`from_file`).

        Returns:
            Protein: A protein with :attr:`~deeporigin.drug_discovery.structures.entity.Entity.remote_path`
            set to ``remote_path`` and :attr:`~deeporigin.drug_discovery.structures.entity.Entity.local_path`
            set to the downloaded file path.
        """
        if client is None:
            client = DeepOriginClient()

        local_file_path = client.files.download(remote_path=remote_path, lazy=lazy)
        protein = cls.from_file(
            local_file_path,
            struct_ind=struct_ind,
            validate=validate,
        )
        protein.remote_path = remote_path
        return protein

    @staticmethod
    def load_structure_from_block(block_content: str, block_type: str):
        """Load a protein structure from block content.

        Args:
            block_content (str): The content of the structure file.
            block_type (str): The type of the structure file (pdb, pdbqt, or cif).

        Raises:
            ValueError: If the block type is unsupported.
        """
        if block_type in ["pdb", "pdbqt"]:
            from biotite.structure.io.pdb import PDBFile

            pdb_file = PDBFile.read(io.StringIO(block_content))
            structure = pdb_file.get_structure()
        elif block_type == "cif":
            from biotite import InvalidFileError
            import biotite.structure.io.pdbx as pdbx

            cif_file = pdbx.CIFFile.read(io.StringIO(block_content))
            try:
                structure = pdbx.get_structure(cif_file)
            except InvalidFileError as e:
                if "atom_site" in str(e).lower():
                    raise ValueError(
                        "The CIF file does not contain atomic coordinates (missing 'atom_site' category). "
                        "This appears to be a structure factor file or another type of CIF file that "
                        "does not contain coordinate data. Please provide a coordinate CIF file instead."
                    ) from e
                raise
        else:
            raise ValueError(f"Unsupported block type: {block_type}")
        return structure

    @staticmethod
    def select_structure(structure, index: int):
        """Select a specific structure by index."""
        if index < 0 or index >= len(structure):
            raise ValueError(
                f"Invalid structure index {index}. Total structures: {len(structure)}"
            )
        return structure[index]

    @property
    def sequence(self) -> list[Bio.Seq.Seq]:
        """
        Retrieve the amino acid sequences of all polypeptide chains in the protein structure.

        This property parses the protein structure file using Bio.PDB and extracts the sequences
        of all peptide chains present. Each sequence is returned as a Bio.Seq object, which can be
        converted to a string if needed. The method is useful for analyzing the primary structure
        of the protein or for downstream sequence-based analyses.

        Returns:
            list[str]: A list of amino acid sequences (as Bio.Seq objects) for each polypeptide chain
                found in the protein structure. If the structure contains multiple chains, each chain's
                sequence is included as a separate entry in the list.

        Example:
            >>> protein = Protein.from_file("example.pdb")
            >>> sequences = protein.sequence
            >>> for seq in sequences:
            ...     print(seq)
        """
        if self.local_path is None:
            raise ValueError(
                "No local structure file; call download() or load_structure_from_local() first."
            )

        from Bio.PDB import PDBParser, PPBuilder

        parser = PDBParser(QUIET=True)
        structure = parser.get_structure("X", self.local_path)

        ppb = PPBuilder()
        sequences = []
        for pp in ppb.build_peptides(structure):
            sequences.append(pp.get_sequence())

        return sequences

    @property
    def coordinates(self):
        self.download(lazy=True)
        assert self.structure is not None
        return self.structure.coord

    def bounding_box_volume(self) -> float:
        """Compute the volume of the axis-aligned bounding box of the protein.

        Uses atomic coordinates to estimate size as the product of the spans
        along each axis. Coordinates are in Angstroms, so the result is in
        cubic Angstroms (Å³).

        Returns:
            float: Bounding box volume in Å³.

        Raises:
            ValueError: If the protein structure is not loaded.
        """
        if self.structure is None:
            if self.local_path is None and self.remote_path is None:
                raise ValueError(_PROTEIN_STRUCTURE_NOT_LOADED_MSG)
            self.download(lazy=True)
        if self.structure is None:
            raise ValueError(_PROTEIN_STRUCTURE_NOT_LOADED_MSG)

        coords = self.structure.coord
        span = coords.max(axis=0) - coords.min(axis=0)
        return float(span[0] * span[1] * span[2])

    def has_ligand_clashes(
        self,
        ligand: Ligand | str | Path,
        *,
        contact_distance: float = 2.5,
        protein_atoms_only: bool = True,
        exclude_waters: bool = True,
        heavy_atoms_only: bool = True,
    ) -> bool:
        """Check whether a ligand pose sterically clashes with this protein.

        Compares ligand atom coordinates against protein atom coordinates and
        returns ``True`` when any pair is closer than ``contact_distance``.

        The ligand SDF must already be in the same coordinate frame as the
        protein structure (for example, a docked pose aligned to the receptor).

        Args:
            ligand: A :class:`Ligand` instance or path to a single-molecule SDF.
            contact_distance: Distance threshold (Å) below which a pair is a clash.
            protein_atoms_only: When ``True``, exclude HETATM records so the
                check compares the ligand against the receptor only.
            exclude_waters: When ``True``, remove solvent before checking.
            heavy_atoms_only: When ``True``, ignore hydrogen atoms on both sides.

        Returns:
            ``True`` if at least one ligand atom clashes with a protein atom.

        Raises:
            ValueError: If the protein structure is not loaded or
                ``contact_distance`` is not positive.
            DeepOriginException: If the ligand does not have 3D coordinates.
        """
        if contact_distance <= 0:
            raise ValueError("contact_distance must be positive.")

        if self.structure is None:
            if self.local_path is None and self.remote_path is None:
                raise ValueError(_PROTEIN_STRUCTURE_NOT_LOADED_MSG)
            self.download(lazy=True)
        if self.structure is None:
            raise ValueError(_PROTEIN_STRUCTURE_NOT_LOADED_MSG)

        if isinstance(ligand, (str, Path)):
            ligand_obj = Ligand.from_sdf(ligand)
        else:
            ligand_obj = ligand

        if not ligand_obj.has_3d_structure():
            raise DeepOriginException(
                title="Ligand missing 3D coordinates",
                message=(
                    "Cannot check ligand clashes because the ligand does not "
                    "have 3D coordinates."
                ),
            )

        structure = self.structure
        atom_mask = np.ones(len(structure), dtype=bool)

        if protein_atoms_only:
            atom_mask &= ~structure.hetero

        if exclude_waters and not protein_atoms_only:
            from biotite.structure import filter_solvent

            atom_mask &= ~filter_solvent(structure)

        if heavy_atoms_only:
            atom_mask &= structure.element != "H"

        protein_atoms = structure[atom_mask]
        protein_coords = protein_atoms.coord

        ligand_coords = ligand_obj.coordinates
        if heavy_atoms_only:
            ligand_elements = ligand_obj.get_species()
            heavy_mask = np.array(
                [element != "H" for element in ligand_elements],
                dtype=bool,
            )
            ligand_coords = ligand_coords[heavy_mask]

        return _any_ligand_protein_clashes(
            ligand_coords,
            protein_coords,
            contact_distance=contact_distance,
        )

    def _filter_hetatm_records(
        self, exclude_water: bool = True, keep_resnames: Optional[list[str]] = None
    ):
        """
        Internal method to filter HETATM records, optionally excluding water molecules and keeping specified residues.

        Parameters:
        - exclude_water (bool): Whether to exclude water molecules (default: True).
        - keep_resnames (Optional[list[str]]): List of residue names to keep (e.g., metal ions, cofactors).

        Returns:
        - AtomArray: Filtered HETATM records from the structure.
        """
        self.download(lazy=True)
        hetatm_records = self.structure[self.structure.hetero]
        res_names_upper = np.char.upper(hetatm_records.res_name)

        if exclude_water:
            water_residue_names = ["HOH", "WAT"]
            water_residue_names_upper = [name.upper() for name in water_residue_names]
            hetatm_records = hetatm_records[
                ~np.isin(res_names_upper, water_residue_names_upper)
            ]
            res_names_upper = np.char.upper(hetatm_records.res_name)

        if keep_resnames:
            keep_resnames_upper = [name.upper() for name in keep_resnames]
            hetatm_records = hetatm_records[
                np.isin(res_names_upper, keep_resnames_upper)
            ]

        return hetatm_records

    def _filter_chain_records(self, chain_ids: Optional[list[str]] = None):
        """
        Filter chain records based on chain IDs.

        Args:
        Parameters:
        - chain_ids (Optional[List[str]]): List of chain IDs to filter. If None or contains "ALL", all chains are returned.

        Returns:
        - AtomArray: Filtered chain records from the structure.
        """
        self.download(lazy=True)
        if chain_ids is None or "ALL" in chain_ids:
            return self.structure
        else:
            return self.structure[np.isin(self.structure.chain_id, chain_ids)]

    def list_chain_names(self) -> list[str]:
        """
        List all unique chain IDs in the protein structure.

        Returns:
            list[str]: A list of unique chain IDs.
        """
        chain_records = self._filter_chain_records()
        chain_ids = np.unique(chain_records.chain_id)
        return list(chain_ids)

    def list_hetero_names(self, exclude_water=True) -> list[str]:
        """
        List all unique hetero residue names in the protein structure.

        Args:
            exclude_water (bool): Whether to exclude water molecules from the list.

        Returns:
            list[str]: A list of unique ligand residue names (excluding water).
        """
        hetatm_records = self._filter_hetatm_records(exclude_water=exclude_water)
        ligand_res_names = np.unique(hetatm_records.res_name)
        return list(ligand_res_names)

    def select_chain(self, chain_id: str) -> Optional[Self]:
        """
        Select a specific chain by its ID and return a new Protein object.

        Parameters:
        - chain_id (str): Chain ID to select.

        Returns:
        - Protein: A new Protein object containing the selected chain.

        Raises:
        - ValueError: If the chain ID is not found.


        """
        chain_records = self._filter_chain_records(chain_ids=[chain_id])
        if len(chain_records) > 0:
            return self._create_new_protein_with_structure(
                chain_records, suffix=f"_chain_{chain_id}"
            )
        else:
            raise ValueError(f"Chain {chain_id} not found.")

    def select_chains(self, chain_ids: list[str]) -> Self:
        """
        Select specific chains from the protein structure.

        Args:
            chain_ids (list[str]): List of chain IDs to select.
        """
        chain_records = self._filter_chain_records(chain_ids=chain_ids)
        if len(chain_records) == 0:
            raise ValueError(f"No chains found for the provided chain IDs: {chain_ids}")
        return self._create_new_protein_with_structure(
            chain_records, suffix=f"_chains_{'_'.join(chain_ids)}"
        )

    @beartype
    def remove_hetatm(
        self,
        keep_resnames: Optional[list[str]] = None,
        remove_metals: Optional[list[str]] = None,
    ) -> None:
        """
        Remove HETATM records from the protein structure, with options to retain specified residues or exclude certain metals.

        Args:
            keep_resnames (Optional[list[str]]): A list of residue names (strings) to keep in the structure even if they are HETATM records.
            remove_metals (Optional[list[str]]): A list of metal names (strings) to exclude from removal. These metals will be retained in the structure.

        Notes:

        - By default, a predefined list of metals is considered for removal unless specified in `exclude_metals`.
        - If `keep_resnames` is provided, those residues (along with any metals not excluded) will be retained even if they are HETATM records.
        - The method updates the current protein object in place.


        """
        self.download(lazy=True)
        metals = METALS
        if remove_metals:
            exclude_metals_upper = [metal.upper() for metal in remove_metals]
            metals = list(set(METALS) - set(exclude_metals_upper))

        if not metals and not keep_resnames:
            self.structure = self.structure[~self.structure.hetero]
        else:
            keep_resnames_upper = (
                [res.upper() for res in keep_resnames] if keep_resnames else []
            )
            keep_resnames_upper.extend(metals)
            keep_resnames_set = list(set(keep_resnames_upper))

            hetatm_to_keep = self._filter_hetatm_records(
                keep_resnames=keep_resnames_set
            )
            hetatm_indices_to_keep = np.isin(
                self.structure.res_id, hetatm_to_keep.res_id
            )
            self.structure = self.structure[
                ~self.structure.hetero | hetatm_indices_to_keep
            ]

    @beartype
    def remove_resnames(
        self,
        exclude_resnames: Optional[list[str]] = None,
    ) -> None:
        """
        Remove specific residue names from the protein structure in place.

        Args:
            exclude_resnames (Optional[list[str]]): List of residue names to exclude.
        """
        self.download(lazy=True)
        if exclude_resnames is not None:
            b_resn = np.isin(self.structure.res_name, exclude_resnames)
            self.structure = self.structure[~b_resn]

    def remove_water(self) -> None:
        """
        Remove water molecules from the protein structure in place.

        """
        self.download(lazy=True)
        from biotite.structure import filter_solvent

        self.structure = self.structure[~filter_solvent(self.structure)]

    def find_missing_residues(self) -> dict[str, list[tuple[int, int]]]:
        """find missing residues in the protein structure"""

        self.download(lazy=True)

        import os
        import tempfile

        from Bio.PDB import PDBParser

        parser = PDBParser(QUIET=True)
        missing = {}

        temp_file = tempfile.NamedTemporaryFile(suffix=".pdb", delete=False)
        try:
            self.to_pdb(temp_file.name)
            temp_file.close()  # Close so it can be reopened on Windows
            structure = parser.get_structure("protein", temp_file.name)

            for model in structure:
                for chain in model:
                    chain_id = chain.id
                    last_resseq = None
                    gaps = []

                    residues = sorted(
                        [res for res in chain.get_residues() if res.id[0] == " "],
                        key=lambda r: r.id[1],
                    )
                    for res in residues:
                        resseq = res.id[1]
                        if last_resseq is not None and resseq > last_resseq + 1:
                            gaps.append((last_resseq, resseq))
                        last_resseq = resseq

                    if gaps:
                        missing[chain_id] = gaps
        finally:
            os.unlink(temp_file.name)

        return missing

    def extract_metals_and_cofactors(self) -> tuple[list[str], list[str]]:
        """
        Extract metal ions and cofactors from the protein structure.

        Returns:
            Tuple[list[str], list[str]]
        """
        self.download(lazy=True)
        hetatm_records = self.structure[self.structure.hetero]
        water_residue_names = ["HOH", "WAT"]
        hetatm_records = hetatm_records[
            ~np.isin(hetatm_records.res_name, water_residue_names)
        ]

        residue_groups = defaultdict(list)
        for atom in hetatm_records:
            key = (atom.chain_id, atom.res_id, atom.ins_code)
            residue_groups[key].append(atom)

        metal_resnames = set()
        cofactor_resnames = set()
        for atoms in residue_groups.values():
            res_name = atoms[0].res_name.strip().upper()
            is_metal = all(
                atom.element.strip().upper() in METAL_ELEMENTS for atom in atoms
            )
            if is_metal:
                metal_resnames.add(res_name)
            else:
                cofactor_resnames.add(res_name)

        metal_resnames = list(metal_resnames)
        cofactor_resnames = list(cofactor_resnames)

        return metal_resnames, cofactor_resnames

    def extract_ligand(self, exclude_resnames: Optional[set[str]] = None) -> Ligand:
        """
        Extracts ligand(s) from a Protein object and removes them from the protein structure.
        This method mutates the protein object by removing ligand records.

        Args:
            exclude_resnames (set): Residue names to exclude (e.g., water).

        Returns:
            Ligand: The extracted ligand molecule.
        """
        self.download(lazy=True)

        from rdkit import Chem

        if exclude_resnames is None:
            exclude_resnames = {"HOH", "WAT", "H2O"}
        else:
            # Normalize to uppercase for comparison
            exclude_resnames = {resname.upper() for resname in exclude_resnames}

        ligand_lines = []
        conect_lines = []
        ligand_resnames = set()
        ligand_atom_serials = set()

        # For CIF files, we need to convert to PDB format first to extract HETATM records
        if self.block_type == "cif":
            # Convert CIF to PDB format temporarily
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".pdb", delete=False
            ) as temp_file:
                temp_pdb_path = temp_file.name
            try:
                self.to_pdb(temp_pdb_path)
                with open(temp_pdb_path, "r") as f:
                    content_lines = list(f)
            finally:
                # Clean up temporary file
                if os.path.exists(temp_pdb_path):
                    os.remove(temp_pdb_path)
        elif self.block_content:
            # Split by newline and add newlines back to match file reading behavior
            content_lines = [line + "\n" for line in self.block_content.split("\n")]
        elif self.local_path:
            # Read file line by line to preserve newlines
            with open(self.local_path, "r") as f:
                content_lines = list(f)
        else:
            raise ValueError(
                "No block_content or local_path available to extract ligand from."
            )

        # First pass: collect HETATM lines and their residue names
        for line in content_lines:
            if line.startswith("HETATM"):
                # Extract resname and normalize to uppercase for comparison
                resname = line[17:20].strip().upper()
                altloc = line[16].strip()

                # Skip excluded residue names (e.g., water)
                if resname in exclude_resnames:
                    continue

                if altloc not in ("", "A"):  # skip altLocs other than primary
                    continue
                ligand_lines.append(line)
                ligand_resnames.add(resname)
                # Store atom serial for later removal from structure
                try:
                    atom_serial = int(line[6:11].strip())
                    ligand_atom_serials.add(atom_serial)
                except ValueError:
                    continue

        # Second pass: collect CONECT records for the ligand atoms
        for line in content_lines:
            if line.startswith("CONECT"):
                try:
                    atom1 = int(line[6:11].strip())
                    # Check if this CONECT involves any ligand atoms
                    # We'll need to check against the atom serial numbers in our HETATM records
                    for hetatm_line in ligand_lines:
                        hetatm_atom_serial = int(hetatm_line[6:11].strip())
                        if atom1 == hetatm_atom_serial:
                            conect_lines.append(line)
                            break
                except ValueError:
                    # Skip malformed CONECT records
                    continue

        if not ligand_lines:
            raise ValueError("No ligand HETATM records found in the PDB.")

        # Create PDB block from ligand lines and CONECT records
        ligand_pdb_block = "".join(ligand_lines) + "".join(conect_lines) + "END\n"

        # Parse with RDKit
        mol = Chem.MolFromPDBBlock(ligand_pdb_block, sanitize=True, removeHs=False)
        if mol is None:
            raise ValueError("RDKit could not parse the ligand from the PDB block.")

        # Now remove the ligand from the protein structure
        self._remove_ligand_from_structure(ligand_atom_serials, ligand_resnames)

        return Ligand.from_rdkit_mol(mol)

    def _remove_ligand_from_structure(
        self, ligand_atom_serials: set[int], ligand_resnames: set[str]
    ):
        """
        Remove ligand atoms from the protein structure and update block_content.

        Args:
            ligand_atom_serials: Set of atom serial numbers to remove
            ligand_resnames: Set of residue names to remove
        """
        if not self.block_content:
            return

        # For CIF files, filter the structure directly and regenerate CIF content
        if self.block_type == "cif":
            # Normalize residue names to uppercase for comparison
            ligand_resnames_upper = {resname.upper() for resname in ligand_resnames}

            # Filter structure: remove atoms with matching residue names
            # Keep atoms that are not hetero OR are hetero but not in ligand_resnames
            res_names_upper = np.char.upper(self.structure.res_name)
            mask = ~(
                self.structure.hetero
                & np.isin(res_names_upper, list(ligand_resnames_upper))
            )
            filtered_structure = self.structure[mask]

            # Update the structure
            self.structure = filtered_structure
            if hasattr(self.structure, "atom_name"):
                self.atom_types = self.structure.atom_name

            # Regenerate CIF block_content from the filtered structure
            try:
                import biotite.structure.io.pdbx as pdbx

                cif_file = pdbx.CIFFile()
                pdbx.set_structure(cif_file, self.structure)

                # Serialize to string to get the CIF content
                self.block_content = cif_file.serialize()
            except Exception as e:
                import warnings

                warnings.warn(
                    f"Failed to regenerate CIF content after ligand removal: {e}",
                    stacklevel=2,
                )
            return

        # For PDB files, filter text lines from block_content
        filtered_lines = []
        lines = self.block_content.split("\n")
        removed_atoms = 0
        removed_conect = 0

        for line in lines:
            # Skip HETATM lines for ligands
            if line.startswith("HETATM"):
                resname = line[17:20].strip()
                if resname in ligand_resnames:
                    removed_atoms += 1
                    continue

            # Skip CONECT lines involving ligand atoms
            if line.startswith("CONECT"):
                try:
                    atom1 = int(line[6:11].strip())
                    if atom1 in ligand_atom_serials:
                        removed_conect += 1
                        continue
                    # Check if any other atoms in CONECT are ligand atoms
                    atom2 = int(line[11:16].strip()) if len(line) > 16 else None
                    atom3 = int(line[16:21].strip()) if len(line) > 21 else None
                    atom4 = int(line[21:26].strip()) if len(line) > 26 else None

                    if (
                        atom2
                        and atom2 in ligand_atom_serials
                        or atom3
                        and atom3 in ligand_atom_serials
                        or atom4
                        and atom4 in ligand_atom_serials
                    ):
                        removed_conect += 1
                        continue
                except ValueError:
                    # Keep malformed CONECT records
                    pass

            filtered_lines.append(line)

        # Update MASTER record if it exists
        for i, line in enumerate(filtered_lines):
            if line.startswith("MASTER"):
                # MASTER record format: MASTER xxxxx xxxxx xxxxx xxxxx xxxxx xxxxx xxxxx xxxxx xxxxx xxxxx xxxxx xxxxx
                # Field 9 (index 8) is total number of atoms, Field 11 (index 10) is total number of CONECT records
                parts = line.split()
                if len(parts) >= 12:
                    try:
                        # Update atom count (field 9)
                        old_atom_count = int(parts[8])
                        new_atom_count = old_atom_count - removed_atoms
                        parts[8] = str(new_atom_count)

                        # Update CONECT count (field 11)
                        old_conect_count = int(parts[10])
                        new_conect_count = old_conect_count - removed_conect
                        parts[10] = str(new_conect_count)

                        # Reconstruct the MASTER line with proper spacing
                        filtered_lines[i] = (
                            f"{parts[0]:<6}{parts[1]:>5}{parts[2]:>5}{parts[3]:>5}{parts[4]:>5}{parts[5]:>5}{parts[6]:>5}{parts[7]:>5}{parts[8]:>5}{parts[9]:>5}{parts[10]:>5}{parts[11]:>5}"
                        )
                    except (ValueError, IndexError):
                        # If we can't parse the MASTER record, leave it unchanged
                        pass
                break

        # Update block_content
        self.block_content = "\n".join(filtered_lines)

        # Update the structure by reloading from the filtered content
        try:
            new_structure = self.load_structure_from_block(
                self.block_content, self.block_type
            )
            # Ensure we get an AtomArray, not AtomArrayStack
            if (
                hasattr(new_structure, "array_length")
                and new_structure.array_length() > 0
            ):
                # It's an AtomArrayStack, select the first structure
                self.structure = new_structure[0]
            else:
                # It's already an AtomArray
                self.structure = new_structure

            # Update atom_types if they exist
            if hasattr(self.structure, "atom_name"):
                self.atom_types = self.structure.atom_name
        except Exception as e:
            # If structure reloading fails, log warning but don't fail the extraction
            import warnings

            warnings.warn(
                f"Failed to update protein structure after ligand removal: {e}",
                stacklevel=2,
            )

    def _create_new_protein_with_structure(
        self, new_structure, suffix: str = "_modified"
    ) -> Self:
        """
        Helper method to create a new Protein object with a modified structure.
        Writes the modified structure to a new file and creates a new Protein object from that file.

        Parameters:
        - new_structure: The modified structure.
        - suffix (str): A suffix to append to the new file name (default: "_modified").

        Returns:
        - Protein: A new Protein object created from the newly written structure file.

        Raises:
        - Exception: If writing the new structure fails.
        """
        local = Path(self.local_path) if self.local_path else None
        base_name = local.stem if local else "modified_structure"
        new_file_name = f"{base_name}{suffix}.pdb"
        parent_dir = local.parent if local else Path(tempfile.gettempdir())
        new_file_path = parent_dir / new_file_name

        if new_file_path.exists():
            os.remove(new_file_path)

        try:
            from biotite.structure.io.pdb import PDBFile

            pdb_file = PDBFile()
            pdb_file.set_structure(new_structure)
            pdb_file.write(str(new_file_path))
            return Protein.from_file(str(new_file_path))
        except Exception as e:
            raise RuntimeError(
                f"Failed to create new Protein with modified structure: {str(e)}"
            ) from e

    @beartype
    def to_pdb(self, file_path: Optional[str | Path] = None) -> str:
        """
        Write the protein structure to a PDB file.

        This is a local operation: it serializes the current :attr:`structure`. If the
        protein has :attr:`remote_path` but no local file yet, raise; rehydrate with
        :meth:`download` first.

        Args:
            file_path (str): Path where the PDB file will be written.

        Raises:
            DeepOriginException: If ``remote_path`` is set but no local file exists yet,
                or if :attr:`structure` is not loaded.

        """

        self._assert_rehydrated_for_file_export(
            entity_label="Protein",
            format_name="PDB",
        )
        if self.structure is None:
            raise DeepOriginException(
                title="Protein structure not loaded",
                message=(
                    "Cannot write PDB: structure is not loaded. "
                    "Call download() or load_structure_from_local(), or load from file / PDB ID."
                ),
            )

        if file_path is None:
            file_path = PROTEINS_DIR / (self.to_hash() + ".pdb")

        try:
            from biotite.structure.io.pdb import PDBFile

            pdb_file = PDBFile()
            pdb_file.set_structure(self.structure)
            pdb_file.write(str(file_path))
            return str(file_path)
        except Exception as e:
            raise RuntimeError(
                f"Failed to write structure to file {file_path}: {str(e)}"
            ) from e

    @beartype
    def to_file(self, file_path: Optional[str | Path] = None) -> str:
        """Dump state to a file.

        Args:
            file_path: Path where the file will be written. If None, uses default path.

        Returns:
            str: Path to the written file.
        """
        return self.to_pdb(file_path)

    @beartype
    def to_base64(self) -> str:
        """Convert the protein to base64 encoded PDB format.

        Returns:
            str: Base64 encoded string of the PDB file content
        """
        import base64
        import tempfile

        # Create a temporary PDB file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".pdb", delete=False
        ) as temp_file:
            temp_file_path = temp_file.name

        try:
            # Write the protein to the temporary file
            self.to_pdb(temp_file_path)

            # Read the file and encode to base64
            with open(temp_file_path, "rb") as f:
                pdb_content = f.read()
                base64_encoded = base64.b64encode(pdb_content).decode("utf-8")

            return base64_encoded
        finally:
            # Clean up the temporary file
            import os

            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

    @property
    def num_atoms(self) -> int:
        """Count the number of atoms in PDB file for this protein


        Returns:
            int: The number of atoms in the PDB file.
        """
        from Bio.PDB import PDBParser

        parser = PDBParser(QUIET=True)
        structure = parser.get_structure("complex", str(self.to_pdb()))

        return sum(1 for _ in structure.get_atoms())

    def to_hash(self) -> str:
        """Convert the protein to SHA256 hash of the PDB file content.

        Returns:
            str: SHA256 hash string of the PDB file content
        """
        import tempfile

        # Create a temporary PDB file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".pdb", delete=False
        ) as temp_file:
            temp_file_path = temp_file.name

        try:
            # Write the protein to the temporary file
            self.to_pdb(temp_file_path)

            # Read the file in text mode, normalize newlines, and compute SHA256
            with open(temp_file_path, "r", newline="") as f:
                pdb_text = f.read()
                # Normalize all line endings to \n for OS-agnostic hashing
                normalized_text = pdb_text.replace("\r\n", "\n").replace("\r", "\n")
                # Ensure file ends with a single newline to avoid platform differences
                if not normalized_text.endswith("\n"):
                    normalized_text = f"{normalized_text}\n"
                hash_object = hashlib.sha256(normalized_text.encode("utf-8"))
                hash_hex = hash_object.hexdigest()

            return hash_hex
        finally:
            # Clean up the temporary file
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

    @classmethod
    def from_base64(
        cls,
        base64_string: str,
        name: str = "",
        **kwargs: Any,
    ) -> Self:
        """
        Create a Protein instance from a base64 encoded PDB string.

        Args:
            base64_string (str): Base64 encoded PDB content
            name (str, optional): Name of the protein. Defaults to "".
            **kwargs: Additional arguments to pass to the constructor

        Returns:
            Protein: A new Protein instance

        Raises:
            DeepOriginException: If the base64 string cannot be decoded or parsed
        """
        import base64
        import tempfile

        try:
            # Decode the base64 string
            pdb_content = base64.b64decode(base64_string)

            # Create a temporary file with the decoded content
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".pdb", delete=False
            ) as temp_file:
                temp_file.write(pdb_content)
                temp_file_path = temp_file.name

            # Create the protein from the temporary PDB file
            protein = cls.from_file(temp_file_path, **kwargs)

            # Set the name if provided
            if name:
                protein.name = name

            # Clean up the temporary file
            import os

            os.remove(temp_file_path)

            return protein

        except Exception as e:
            raise DeepOriginException(
                f"Failed to create Protein from base64 string: {str(e)}"
            ) from None

    @beartype
    def _dump_state(self) -> str:
        """Dump the current protein state to a fixed location in the user's home directory.

        Returns:
            str: Path to the state dump file containing the protein structure.
        """
        # Create the .deeporigin directory if it doesn't exist
        STATE_DUMP_PATH.parent.mkdir(exist_ok=True)

        # Use the constant file path
        self.to_pdb(str(STATE_DUMP_PATH))
        return str(STATE_DUMP_PATH)

    @beartype
    def show(
        self,
        *,
        pockets: Optional[list[Pocket]] = None,
        ligand: Optional[Ligand] = None,
        ligands: Optional[LigandSet | list[Ligand]] = None,
        poses: Optional[LigandSet | list[Ligand]] = None,
    ):
        """Visualize the protein structure in a Jupyter notebook using Mol*.

        Renders via the hosted ``molstarLib`` bundle. Protein-only and pockets-only
        views, docked poses, and pockets+poses are supported.

        When more than one pose is supplied, all poses are loaded and overlaid, and a
        navigation bar is shown at the bottom of the viewer. Use its ◀ / ▶ buttons or
        the Left/Right arrow keys to cycle through an "all poses" view and each
        individual pose one at a time.

        Args:
            pockets: Optional pocket overlays (gaussian surfaces).
            ligand: Optional single ligand / docked pose to overlay.
            ligands: Optional ligand set (or list) to overlay as docked poses.
            poses: Alias for ``ligands``.

        Raises:
            DeepOriginException: If both ``ligand`` and ``ligands``/``poses`` are set.
            ValueError: If ``ligands`` or ``poses`` is provided but empty.
        """
        from deeporigin.drug_discovery.docking_common import ligand_payloads_for_viewer
        from deeporigin.utils.notebook import render_html
        from deeporigin.viz.molstar_html import (
            render_protein_html,
            render_protein_with_pockets_and_poses_html,
            render_protein_with_pockets_html,
            render_protein_with_poses_html,
        )

        current_protein_file = self._dump_state()

        if poses is not None:
            ligands = poses

        if ligand is not None and ligands is not None:
            raise DeepOriginException(
                "Either ligand or ligands must be provided, not both"
            ) from None

        pose_ligands: list[Ligand] = []
        if ligand is not None:
            pose_ligands = [ligand]
        elif ligands is not None:
            if isinstance(ligands, LigandSet):
                pose_ligands = list(ligands.ligands)
            else:
                pose_ligands = list(ligands)
            if not pose_ligands:
                raise ValueError("ligands/poses must be non-empty when provided")

        has_pockets = pockets is not None and len(pockets) > 0
        has_poses = len(pose_ligands) > 0

        def _pocket_args() -> tuple[list[str], list[str], list[str]]:
            """Download pockets and return paths, colors, and labels."""
            assert pockets is not None
            for pocket in pockets:
                pocket.download()
            return (
                [str(pocket.local_path) for pocket in pockets],
                [pocket.color for pocket in pockets],
                [
                    pocket.name or f"pocket-{index + 1}"
                    for index, pocket in enumerate(pockets)
                ],
            )

        if not has_pockets and not has_poses:
            return render_html(render_protein_html(pdb_path=current_protein_file))

        if has_pockets and not has_poses:
            pocket_paths, pocket_colors, pocket_labels = _pocket_args()
            return render_html(
                render_protein_with_pockets_html(
                    pdb_path=current_protein_file,
                    pocket_paths=pocket_paths,
                    pocket_colors=pocket_colors,
                    pocket_labels=pocket_labels,
                )
            )

        if has_poses and not has_pockets:
            return render_html(
                render_protein_with_poses_html(
                    pdb_path=current_protein_file,
                    ligand_payloads=ligand_payloads_for_viewer(pose_ligands),
                )
            )

        pocket_paths, pocket_colors, pocket_labels = _pocket_args()
        return render_html(
            render_protein_with_pockets_and_poses_html(
                pdb_path=current_protein_file,
                pocket_paths=pocket_paths,
                pocket_colors=pocket_colors,
                pocket_labels=pocket_labels,
                ligand_payloads=ligand_payloads_for_viewer(pose_ligands),
            )
        )

    def _repr_html_(self):
        """
        Return the HTML representation of the object for Jupyter Notebook.

        Returns:
            str: The HTML content.
        """

        try:
            if self.info:
                from deeporigin.drug_discovery.external_tools.protein_info import (
                    generate_html_output,
                )

                html_content = generate_html_output(self.info)
                return html_content
            return self.visualize()
        except Exception:
            return self.__str__()

    def __str__(self):
        info_str = f"Name: {self.name}\nLocal path: {self.local_path}\nRemote path: {self.remote_path}\n"
        if self.info:
            info_str += f"Info: {self.info}\n"
        return f"Protein:\n  {info_str}"

    @beartype
    def register(
        self,
        *,
        client: Optional[DeepOriginClient] = None,
        remote_path: Optional[str] = None,
    ) -> None:
        """Register the protein as a new record in the data platform.

        Uploads the protein file to remote storage and creates a new protein
        record, regardless of whether one already exists for this file path.

        Args:
            client: DeepOriginClient instance. If None, uses DeepOriginClient().
            remote_path: Custom remote path to upload to. Overrides the
                default hash-based path.

        Returns:
            None. As a side effect, uploads the protein and sets ``self.id``
            to the newly created record's ID.
        """
        if client is None:
            client = DeepOriginClient()

        self.upload(client=client, remote_path=remote_path)

        kwargs: dict[str, Any] = {
            "file_path": self.remote_path,
        }

        if self.pdb_id is not None:
            kwargs["pdb_id"] = self.pdb_id

        if self.local_path is not None:
            kwargs["protein_length"] = self.length
        kwargs["protein_name"] = self.name

        proj_id = self.resolved_project_id(client=client)
        if proj_id is not None:
            kwargs["project_id"] = proj_id
        if self.tags is not None:
            kwargs["tags"] = self.tags

        result = client.entities.create_protein(**kwargs)

        if "data" in result and "id" in result["data"]:
            self.id = result["data"]["id"]

    def sync(
        self,
        *,
        lazy: bool = False,
        client: Optional[DeepOriginClient] = None,
        remote_path: Optional[str] = None,
    ) -> None:
        """Sync the protein to the data platform.

        Uploads the protein file and links to an existing record if one with
        the same file path already exists, otherwise creates a new record via
        :meth:`register`.

        Args:
            lazy: If True, skip syncing when the protein already has an ID.
                Defaults to False.
            client: DeepOriginClient instance. If None, uses DeepOriginClient().
            remote_path: Custom remote path to upload to. Overrides the
                default hash-based path.

        Returns:
            None. As a side effect, uploads the protein (if necessary) and updates
            ``self.id`` with the ID of the existing or newly created protein record,
            and sets :attr:`project_id` when a project scope applies or the platform
            row includes ``project_id``.
        """
        if lazy and self.id is not None:
            if client is None:
                client = DeepOriginClient()
            proj_id = self.resolved_project_id(client=client)
            if proj_id is not None:
                self.project_id = proj_id
            return

        if client is None:
            client = DeepOriginClient()

        self.upload(client=client, remote_path=remote_path)

        proj_id = self.resolved_project_id(client=client)
        if proj_id is not None:
            self.project_id = proj_id

        if proj_id is not None:
            response = client.entities.search_proteins(
                file_path=self.remote_path,
                project_id=proj_id,
            )
        else:
            response = client.entities.search_proteins(file_path=self.remote_path)
        data = response["data"]

        if data:
            existing_protein = data[0]
            if "id" in existing_protein:
                self.id = existing_protein["id"]
            ep = existing_protein.get("project_id")
            if ep is not None:
                self.project_id = str(ep)
            if self.tags is not None and self.id is not None:
                client.entities.update_protein(self.id, tags=self.tags)
            return

        self.register(client=client)

    @beartype
    def update(
        self,
        *,
        client: Optional[DeepOriginClient] = None,
        remote_path: Optional[str] = None,
    ) -> None:
        """Update the protein's ``file_path`` on an existing platform record.

        Uploads the local structure file when present, then PATCHes
        ``file_path`` on the record identified by ``self.id``. Use
        :meth:`sync` to link or create by identity; use ``update`` when you
        already have a platform ID.

        Args:
            client: DeepOriginClient instance. If None, uses DeepOriginClient().
            remote_path: Explicit remote path to set as ``file_path``. When
                omitted, uploads ``local_path`` and uses the resulting path.

        Returns:
            None. Refreshes ``self.remote_path`` from the platform response.

        Raises:
            ValueError: If ``self.id`` is unset or no file path can be resolved.
        """
        if self.id is None:
            raise ValueError(
                "Cannot update a protein without a platform id; "
                "call sync() or register() first."
            )

        if client is None:
            client = DeepOriginClient()

        if remote_path is not None:
            path = remote_path
            if self.local_path is not None:
                self.upload(client=client, remote_path=remote_path)
        elif self.local_path is not None:
            self.upload(client=client, remote_path=None)
            path = self.remote_path
        else:
            raise ValueError(
                "Nothing to update: provide remote_path or set local_path "
                "before calling update()."
            )

        if path is None:
            raise ValueError("remote_path is required after upload.")

        result = client.entities.update_protein(self.id, file_path=path)  # ty:ignore[unresolved-attribute]

        row = result.get("data")
        if isinstance(row, list):
            row = row[0] if row else None
        if isinstance(row, dict):
            file_path = row.get("file_path")
            if file_path:
                self.remote_path = file_path

    def update_coordinates(self, coords: np.ndarray):
        """update coordinates of the protein structure"""

        self.download(lazy=True)
        self.structure.coord = coords

    @property
    def length(self) -> int:
        """get the length of the protein structure"""
        return sum([len(seq) for seq in self.sequence])


def validate_pdb_file(file_path: str | Path) -> None:
    """validate a PDB file by checking if it can be parsed by RDKit

    Args:
        file_path (str | Path): Path to the PDB file.

    Raises:
        DeepOriginException: If the PDB file is invalid.
    """
    # If you want *exceptions* instead, use:
    from rdkit import Chem, rdBase

    rdBase.EnableLog("rdApp.error")  # logging on
    mol = Chem.MolFromPDBFile(str(file_path), sanitize=False, removeHs=False)
    rdBase.DisableLog("rdApp.error")
    if mol is None:
        raise DeepOriginException(
            title="Invalid PDB file",
            message="The PDB file is invalid. It could not be parsed by RDKit.",
            fix="Please check the PDB file and try again.",
        )
