"""Module to support Drug Discovery workflows using Deep Origin"""

from dataclasses import dataclass, field
import os
from typing import Optional

from deeporigin.drug_discovery.abfe import ABFE
from deeporigin.drug_discovery.docking import Docking
from deeporigin.drug_discovery.rbfe import RBFE
from deeporigin.drug_discovery.structures import Ligand, LigandSet, Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform import Client


@dataclass
class Complex:
    """class to represent a set of a protein and 1 or many ligands"""

    protein: Protein

    # Use a private attribute for ligands
    _ligands: LigandSet = field(default_factory=LigandSet, repr=False)
    client: Optional[Client] = None
    _prepared_systems: dict[str, str] = field(default_factory=dict, repr=False)

    def __init__(
        self,
        *,
        protein: Protein,
        ligands: Optional[LigandSet | list[Ligand] | Ligand] = None,
        client: Optional[Client] = None,
    ):
        """Initialize a Complex object.

        Args:
            protein (Protein): The protein to use in the complex.
            ligands (LigandSet | list[Ligand] | Ligand): The ligands to use in the complex.
        """
        self.protein = protein
        self.ligands = ligands
        self.client = client

        # assign references to the complex in the
        # various child classes
        self.docking = Docking(parent=self)
        self.abfe = ABFE(parent=self)
        self.rbfe = RBFE(parent=self)

        self._prepared_systems = {}

    @property
    def ligands(self) -> LigandSet:
        return self._ligands

    @ligands.setter
    def ligands(self, value):
        if value is None:
            self._ligands = LigandSet()
            return
        if isinstance(value, list):
            self._ligands = LigandSet(ligands=value)
        elif isinstance(value, LigandSet):
            self._ligands = value
        elif isinstance(value, Ligand):
            self._ligands = LigandSet(ligands=[value])
        else:
            raise ValueError(
                "ligands must be a list of Ligands, a Ligand, or a LigandSet"
            )

    @classmethod
    def from_dir(
        cls,
        directory: str,
        *,
        client: Optional[Client] = None,
    ) -> "Complex":
        """Initialize a Complex from a directory containing protein and ligand files.

        Args:
            directory (str): Directory containing ligand and protein files.

        The directory should contain:
        - Exactly one PDB file for the protein
        - One or more SDF files for the ligands. Each SDF file can contain one or more molecules.

        Returns:
            Complex: A new Complex instance initialized from the files in the directory.

        Raises:
            ValueError: If no PDB file is found or if multiple PDB files are found.
        """

        # Load all ligands from SDF files
        ligands = LigandSet.from_dir(directory)

        # Find PDB file
        pdb_files = [
            os.path.join(directory, f)
            for f in os.listdir(directory)
            if f.lower().endswith(".pdb")
        ]

        if len(pdb_files) != 1:
            raise DeepOriginException(
                title="Complex.from_dir expects a single PDB file",
                message=f"Expected exactly one PDB file in the directory, but found {len(pdb_files)}: {pdb_files}",
            ) from None
        protein_file = pdb_files[0]
        protein = Protein.from_file(protein_file)

        # Create the Complex instance
        instance = cls(
            protein=protein,
            ligands=ligands,
            client=client,
        )

        return instance

    def prepare(
        self,
        ligand: Optional[Ligand] = None,
        *,
        padding: float = 1.0,
        retain_waters: bool = False,
        add_H_atoms: bool = False,  # this nonstandard capitalization is to match the name in the underlying function
        protonate_protein: bool = False,
        use_cache: bool = True,
    ):
        """run system preparation on the protein and one ligand from the Complex

        Args:
            ligand (Ligand): The ligand to prepare.
            padding (float, optional): Padding to add around the system.
            retain_waters (bool, optional): Whether to keep water molecules.
            add_H_atoms (bool, optional): Whether the ligand is already protonated.
            protonate_protein (bool, optional): Whether to protonate the protein.
            use_cache (bool, optional): Whether to use the cache.
        """
        from deeporigin.functions.sysprep import run_sysprep

        if ligand is None:
            from tqdm import tqdm

            responses = []

            for ligand in tqdm(self.ligands, desc="Preparing systems"):
                response = self.prepare(
                    ligand=ligand,
                    padding=padding,
                    retain_waters=retain_waters,
                    add_H_atoms=add_H_atoms,
                    protonate_protein=protonate_protein,
                    use_cache=use_cache,
                )

                self._prepared_systems[ligand.to_hash()] = response
            return responses

        # make sure there are no missing residues in the protein
        data = self.protein.find_missing_residues()
        if len(data.keys()) > 0:
            raise DeepOriginException(
                title="Protein has missing residues",
                message="Protein has missing residues. Please use the loop modelling tool to fill in the missing residues.",
            ) from None

        # run sysprep on the ligand
        response = run_sysprep(
            protein=self.protein,
            padding=padding,
            ligand=ligand,
            retain_waters=retain_waters,
            add_H_atoms=add_H_atoms,
            protonate_protein=protonate_protein,
            use_cache=use_cache,
        )

        # set this complex path as the prepared system
        self._prepared_systems[ligand.to_hash()] = response
        output_files = response["output_files"]
        output_file = [file for file in output_files if file.endswith(".pdb")][0]

        # download the output file
        from deeporigin.platform import file_api

        local_path = file_api.download_file(
            remote_path=output_file,
            client=self.client,
        )

        return Protein.from_file(local_path)

    def _sync_protein_and_ligands(self) -> None:
        """Ensure that the protein and ligands are uploaded to Deep Origin

        Internal method. Do not use."""

        # the reason we are uploading here manually, instead of using ligand.upload()
        # and protein.upload() is so that we can make one call to upload_files, instead
        # of several

        from deeporigin.platform import file_api

        remote_files = file_api.get_object_directory(
            file_path="entities/",
            recursive=True,
            client=self.client,
        )
        remote_files = [file.Key for file in remote_files]

        files_to_upload = {}

        if self.protein._remote_path not in remote_files:
            files_to_upload[str(self.protein.to_pdb())] = self.protein._remote_path
        for ligand in self.ligands:
            if ligand._remote_path not in remote_files:
                files_to_upload[str(ligand.to_sdf())] = ligand._remote_path

        file_api.upload_files(files_to_upload, client=self.client)

    def _repr_pretty_(self, p, cycle):
        """pretty print a Complex object"""

        if cycle:
            p.text("Complex(...)")
        else:
            p.text("Complex(")

            p.text(f"protein={self.protein.name}")
            p.text(f" with {len(self.ligands)} ligands")
            p.text(")")
