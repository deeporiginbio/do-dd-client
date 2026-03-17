"""Module to support Drug Discovery workflows using Deep Origin"""

from dataclasses import dataclass, field
import os
from typing import Optional

from deeporigin.drug_discovery.abfe_step import ABFE
from deeporigin.drug_discovery.docking_step import Docking
from deeporigin.drug_discovery.rbfe import RBFE
from deeporigin.drug_discovery.structures import Ligand, LigandSet, Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.functions.result import FunctionResult
from deeporigin.platform.client import DeepOriginClient


@dataclass
class Complex:
    """class to represent a set of a protein and 1 or many ligands"""

    protein: Protein

    # Use a private attribute for ligands
    _ligands: LigandSet = field(default_factory=LigandSet, repr=False)
    client: Optional[DeepOriginClient] = None
    _prepared_systems: dict[str, str] = field(default_factory=dict, repr=False)

    def __init__(
        self,
        *,
        protein: Protein,
        ligands: Optional[LigandSet | list[Ligand] | Ligand] = None,
        client: Optional[DeepOriginClient] = None,
    ):
        """Initialize a Complex object.

        Args:
            protein (Protein): The protein to use in the complex.
            ligands (LigandSet | list[Ligand] | Ligand): The ligands to use in the complex.
        """
        self.protein = protein
        self.ligands = ligands

        if client is None:
            client = DeepOriginClient()
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
        client: Optional[DeepOriginClient] = None,
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

        cif_files = [
            os.path.join(directory, f)
            for f in os.listdir(directory)
            if f.lower().endswith(".cif")
        ]

        if len(pdb_files) + len(cif_files) != 1:
            raise DeepOriginException(
                title="Complex.from_dir expects a single PDB or CIF file",
                message=f"Expected exactly one PDB or CIF file in the directory, but found {len(pdb_files) + len(cif_files)}: {pdb_files + cif_files}",
            ) from None
        protein_file = pdb_files[0] if len(pdb_files) == 1 else cif_files[0]
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
        add_H_atoms: bool = False,  # NOSONAR
        protonate_protein: bool = False,
        quote: bool = False,
    ) -> FunctionResult:
        """Run system preparation on the protein and one or more ligands.

        Args:
            ligand: The ligand to prepare. If None, prepares all ligands
                in the Complex.
            padding: Padding to add around the system.
            retain_waters: Whether to keep water molecules.
            add_H_atoms: Whether to add hydrogen atoms to the ligand.
            protonate_protein: Whether to protonate the protein.
            quote: If True, request a cost estimate without executing.

        Returns:
            FunctionResult with a ``prepared_systems`` attribute containing
            a list of prepared Protein objects (empty when ``quote=True``).
        """
        from deeporigin.functions.sysprep import for_abfe

        if ligand is not None:
            ligands = [ligand]
        else:
            ligands = list(self.ligands)

        data = self.protein.find_missing_residues()
        if len(data.keys()) > 0:
            raise DeepOriginException(
                title="Protein has missing residues",
                message="Protein has missing residues. Please use the loop modelling tool to fill in the missing residues.",
            ) from None

        from tqdm import tqdm

        individual_results = []
        for lig in tqdm(ligands, desc="Preparing systems", disable=len(ligands) == 1):
            individual_results.append(
                for_abfe(
                    protein=self.protein,
                    padding=padding,
                    ligand=lig,
                    retain_waters=retain_waters,
                    add_H_atoms=add_H_atoms,
                    protonate_protein=protonate_protein,
                    client=self.client,
                    quote=quote,
                )
            )

        all_responses = [r.response for r in individual_results]
        result = FunctionResult(all_responses)

        if quote:
            result.prepared_systems = []
        else:
            prepared = []
            for r in individual_results:
                outputs = r.function_outputs[0]
                output_file = outputs["system"]["system_pdb_file_path"]
                local_path = self.client.files.download_file(
                    remote_path=output_file,
                    lazy=True,
                )
                prepared.append(Protein.from_file(local_path))

            result.prepared_systems = prepared

            for lig, r in zip(ligands, individual_results, strict=True):
                self._prepared_systems[lig.to_hash()] = r.function_outputs[0]

        return result

    def _sync_protein_and_ligands(self) -> None:
        """Ensure that the protein and ligands are uploaded to Deep Origin

        Internal method. Do not use."""

        # the reason we are uploading here manually, instead of using ligand.upload()
        # and protein.upload() is so that we can make one call to upload_files, instead
        # of several

        remote_files = self.client.files.list_files_in_dir(
            remote_path="entities/",
            recursive=True,
        )

        files_to_upload = {}

        if self.protein._remote_path not in remote_files:
            files_to_upload[str(self.protein.to_pdb())] = self.protein._remote_path
        for ligand in self.ligands:
            if ligand._remote_path not in remote_files:
                files_to_upload[str(ligand.to_sdf())] = ligand._remote_path

        self.client.files.upload_files(files=files_to_upload)

    def _repr_pretty_(self, p, cycle):
        """pretty print a Complex object"""

        if cycle:
            p.text("Complex(...)")
        else:
            p.text("Complex(")

            p.text(f"protein={self.protein.name}")
            p.text(f" with {len(self.ligands)} ligands")
            p.text(")")
