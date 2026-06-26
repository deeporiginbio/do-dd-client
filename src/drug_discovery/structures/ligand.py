"""
This module contains the Ligand and LigandSet classes, which allow you to work with ligands (molecules) in drug discovery workflows.
"""

import base64
import concurrent.futures
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import random
import tempfile
from typing import Any, Callable, ClassVar, Literal, Optional, Self, cast
import warnings

from beartype import beartype
from deeporigin_molstar import MoleculeViewer
import numpy as np
import pandas as pd
from rdkit import Chem, RDLogger
from rdkit.Chem import AllChem, SaltRemover, rdMolDescriptors

from deeporigin.drug_discovery.constants import LIGANDS_DIR, SUPPORTED_ATOM_SYMBOLS
from deeporigin.drug_discovery.utils.visualize import jupyter_visualization
from deeporigin.drug_discovery.validation import validate_fragments
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.constants import number
from deeporigin.utils.env import _ensure_do_folder

from .entity import Entity

warnings.filterwarnings("ignore", category=UserWarning, module="rdkit")
RDLogger.DisableLog("rdApp.*")  # ty:ignore[unresolved-attribute]


FILE_FORMATS = Literal["mol", "mol2", "pdb", "pdbqt", "xyz", "sdf"]

# Keys returned by ``deeporigin.mol-props-combined`` rows → Ligand attribute
# names (snake_case). Mirrors the ``molprops[*]`` items in the combined tool's
# output schema.
_MOLPROPS_RESPONSE_TO_ATTR: dict[str, str] = {
    "logS": "log_s",
    "logD": "log_d",
    "logP": "log_p",
    "ames_probability": "ames_probability",
    "herg_inhibition_probability": "herg_inhibition_probability",
    "cyp1a2": "cyp_1a2",
    "cyp2c9": "cyp_2c9",
    "cyp2c19": "cyp_2c19",
    "cyp2d6": "cyp_2d6",
    "cyp3a4": "cyp_3a4",
    "has_pains": "has_pains",
    "pains_fragments": "pains_fragments",
}

# Molprops API row keys that must not be copied into ``properties`` (entity fields
# or merge keys; see :func:`ligands_to_dataframe` column layout).
_MOLPROPS_ROW_SKIP_PROPERTY_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "ligand_id",
        "smiles",
        "SMILES",
    }
)

# Platform ligand pinned columns → molprops combined-tool row keys.
# Mirrors ``pinned-columns.registry.ts`` on the data platform.
_PLATFORM_PINNED_TO_MOLPROPS_ROW: dict[str, str] = {
    "log_p": "logP",
    "pains_flag": "has_pains",
    "logd_predicted": "logD",
    "logs_predicted": "logS",
    "ames_probability": "ames_probability",
    "herg_probability": "herg_inhibition_probability",
    "cyp1a2": "cyp1a2",
    "cyp2c9": "cyp2c9",
    "cyp2c19": "cyp2c19",
    "cyp2d6": "cyp2d6",
    "cyp3a4": "cyp3a4",
}


def _molprops_row_from_platform_record(data: dict[str, Any]) -> dict[str, Any]:
    """Translate pinned molprops columns on a platform ligand record to tool row keys."""

    row: dict[str, Any] = {}
    for platform_key, tool_key in _PLATFORM_PINNED_TO_MOLPROPS_ROW.items():
        if platform_key in data and data[platform_key] is not None:
            row[tool_key] = data[platform_key]
    return row


def _sdf_marker_present_in_prefix(path: Path, *, max_bytes: int = 16384) -> bool:
    """Return True if the start of the file looks like MOL/SDF text."""

    with path.open("rb") as f:
        chunk = f.read(max_bytes)
    if not chunk.strip():
        return False
    text = chunk.decode("utf-8-sig", errors="replace")
    return "$$$$" in text or "V2000" in text or "V3000" in text or "M  END" in text


def _assert_readable_file_with_extension(
    path: Path,
    *,
    suffix: str,
    expected_description: str,
    content_ok: Callable[[Path], bool] | None = None,
    content_error: str | None = None,
) -> None:
    """Raise if ``path`` is not a regular file with the expected suffix (and optional content check)."""

    if not path.exists():
        raise FileNotFoundError(f"The file '{path}' does not exist.")
    if not path.is_file():
        raise DeepOriginException(f"The path '{path}' is not a regular file.")
    if path.suffix.lower() != suffix:
        raise DeepOriginException(
            f"Expected {expected_description}, got suffix {path.suffix!r} for '{path}'."
        )
    if content_ok is not None and not content_ok(path):
        raise DeepOriginException(
            content_error or f"File '{path}' failed content validation."
        )


def _assert_path_is_sdf(path: Path) -> None:
    """Raise if ``path`` is not a readable SDF file (extension and content check)."""

    _assert_readable_file_with_extension(
        path,
        suffix=".sdf",
        expected_description="an SDF file (.sdf extension)",
        content_ok=_sdf_marker_present_in_prefix,
        content_error=(
            f"File '{path}' does not appear to contain a MOL or SDF structure block."
        ),
    )


def _assert_path_is_csv(path: Path) -> None:
    """Raise if ``path`` is not a readable CSV file (extension check)."""

    _assert_readable_file_with_extension(
        path,
        suffix=".csv",
        expected_description="a CSV file (.csv extension)",
    )


@dataclass
@beartype
class Ligand(Entity):
    """A class representing a ligand molecule in drug discovery workflows.

    The Ligand class provides functionality to create, manipulate, and analyze small molecules
    (ligands) in computational drug discovery. It supports various input formats and provides
    methods for property prediction, visualization, and file operations.

    After running :class:`~deeporigin.drug_discovery.molprops.Molprops`, predicted ADMET values
    are available on dedicated attributes (``log_s``, ``log_d``, ``log_p``,
    ``ames_probability``, ``herg_inhibition_probability``, ``cyp_1a2``,
    ``cyp_2c9``, ``cyp_2c19``, ``cyp_2d6``, ``cyp_3a4``, ``has_pains``,
    ``pains_fragments``) as well as in :attr:`properties`.

    The RDKit molecule must be passed as the keyword-only argument ``mol`` (typically via
    :meth:`from_smiles`, :meth:`from_rdkit_mol`, or similar factory methods).

    """

    identifier: str | None = None
    smiles: str | None = None
    block_type: str | None = None
    block_content: str | None = None
    name: str | None = None
    seed: int | None = None
    xref_protein: str | None = None
    xref_ins_code: str | None = None
    xref_residue_id: str | None = None
    xref_protein_chain_id: str | None = None
    properties: dict = field(default_factory=dict)
    mol: Chem.Mol = field(kw_only=True)
    protonated_at_ph: float | None = None
    # Molprops / ADMET (populated by Molprops.run(); see _MOLPROPS_RESPONSE_TO_ATTR
    # for the API-key → attribute mapping for the combined molprops tool).
    log_s: float | None = None
    log_d: float | None = None
    log_p: float | None = None
    ames_probability: float | None = None
    herg_inhibition_probability: float | None = None
    cyp_1a2: float | None = None
    cyp_2c9: float | None = None
    cyp_2c19: float | None = None
    cyp_2d6: float | None = None
    cyp_3a4: float | None = None
    has_pains: bool | None = None
    pains_fragments: list[Any] | None = None

    # Additional attributes that are initialized in __post_init__
    available_for_docking: bool = field(init=False, default=True)
    prepared: bool = field(init=False, default=False)

    _remote_path_base = "entities/ligands/"
    _preferred_ext = ".sdf"

    @classmethod
    def from_rdkit_mol(
        cls,
        mol: Chem.rdchem.Mol,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> Self:
        """
        Create a Ligand instance from an RDKit Mol object.

        Args:
            mol (Chem.rdchem.Mol): RDKit molecule object to convert to a Ligand
            name (str, optional): Name of the ligand. Defaults to "".
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
            **kwargs,
        )

    @classmethod
    def from_smiles(
        cls,
        smiles: str,
        name: str = "",
        **kwargs: Any,
    ) -> Self:
        """
        Create a Ligand instance from a SMILES string.

        Args:
            smiles (str): SMILES string representing the ligand
            name (str, optional): Name of the ligand. Defaults to "".
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
            **kwargs,
        )

    @classmethod
    def from_identifier(
        cls,
        identifier: str,
    ) -> Self:
        """
        Create a Ligand instance from a compound name.

        Args:
            identifier (str): The identifier to resolve to a SMILES string.

        Raises:
            DeepOriginException: If no compound is found for the given name
            AssertionError: If neither smiles nor name is provided
        """

        import httpx

        try:
            url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{identifier}/property/smiles/JSON"
            response = httpx.get(url, timeout=5)
            data = response.json()
            smiles = data["PropertyTable"]["Properties"][0]["SMILES"]
        except Exception:
            raise DeepOriginException(
                title="Error resolving SMILES string",
                message=f"Error resolving SMILES string of {identifier}. Could not connect to PubChem.",
                fix="Please try again later or use a different identifier.",
            ) from None

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise DeepOriginException(
                title="Error resolving SMILES string",
                message=f"Invalid SMILES returned for {identifier!r}.",
                fix="Please try a different identifier.",
            )

        return cls(mol=mol, name=identifier)

    @classmethod
    def from_base64(
        cls,
        base64_string: str,
        name: str = "",
        **kwargs: Any,
    ) -> Self:
        """
        Create a Ligand instance from a base64 encoded SDF string.

        Args:
            base64_string (str): Base64 encoded SDF content
            name (str, optional): Name of the ligand. Defaults to "".
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
    def from_file(
        cls,
        file_path: str | Path,
        *,
        sanitize: bool = True,
        remove_hydrogens: bool = False,
    ) -> Self:
        """
        Create a Ligand from a file after verifying it is an SDF (extension and content).

        This delegates to :meth:`from_sdf` after validation.

        Args:
            file_path: Path to the SDF file.
            sanitize: Whether to sanitize molecules. Defaults to True.
            remove_hydrogens: Whether to remove hydrogens. Defaults to False.

        Returns:
            Ligand: The Ligand instance created from the SDF file.

        Raises:
            FileNotFoundError: If the file does not exist.
            DeepOriginException: If the path is not an SDF file or loading fails.
        """
        path = Path(file_path)
        _assert_path_is_sdf(path)
        return cls.from_sdf(path, sanitize=sanitize, remove_hydrogens=remove_hydrogens)

    @classmethod
    def from_sdf(
        cls,
        file_path: str | Path,
        *,
        sanitize: bool = True,
        remove_hydrogens: bool = False,
    ) -> Self:
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
        ligands[0].local_path = str(path)
        return ligands[0]

    @classmethod
    def from_remote_file(
        cls,
        remote_path: str,
        *,
        client: DeepOriginClient | None = None,
        lazy: bool = True,
        sanitize: bool = True,
        remove_hydrogens: bool = False,
    ) -> Self:
        """Create a Ligand from an SDF file stored on the platform.

        Downloads the file via :meth:`deeporigin.platform.files.FilesClient.download`,
        then loads it with :meth:`from_sdf`. The SDF must contain exactly one molecule.

        Args:
            remote_path: Platform file path (e.g. org storage path) to the SDF file.
            client: DeepOrigin client used for download. If ``None``, uses
                ``DeepOriginClient()``.
            lazy: Passed to ``files.download``; if ``True``, skip download when the
                file already exists locally at the default cache location.
            sanitize: Whether to sanitize molecules when reading the SDF (see
                :meth:`from_sdf`).
            remove_hydrogens: Whether to strip hydrogens when reading the SDF (see
                :meth:`from_sdf`).

        Returns:
            Ligand: A ligand with :attr:`~deeporigin.drug_discovery.structures.entity.Entity.remote_path`
            set to ``remote_path`` and :attr:`~deeporigin.drug_discovery.structures.entity.Entity.local_path`
            set to the downloaded file path.
        """
        if client is None:
            client = DeepOriginClient()

        local_file_path = client.files.download(remote_path=remote_path, lazy=lazy)
        ligand = cls.from_sdf(
            local_file_path,
            sanitize=sanitize,
            remove_hydrogens=remove_hydrogens,
        )
        ligand.remote_path = remote_path
        return ligand

    def _reload_mol_from_local_sdf_if_applicable(
        self,
        *,
        sanitize: bool = True,
        remove_hydrogens: bool = False,
    ) -> None:
        """Replace ``mol`` and ``smiles`` from :attr:`local_path` when it is an SDF file.

        Remote-only ligands (for example docking poses built with
        :meth:`Ligand.from_smiles` plus ``remote_path``) keep a 2D molecule until the
        pose file exists locally; this loads that file so coordinates match disk.
        """

        path_str = self.local_path
        if path_str is None:
            return
        if Path(path_str).suffix.lower() != ".sdf":
            return
        prev_props = dict(self.properties)
        reloaded = type(self).from_sdf(
            path_str,
            sanitize=sanitize,
            remove_hydrogens=remove_hydrogens,
        )
        self.mol = reloaded.mol
        self.smiles = reloaded.smiles
        self.properties = {**reloaded.properties, **prev_props}
        if self.name in (None, ""):
            self.name = reloaded.name
        self.prepared = False

    @beartype
    def download(
        self,
        *,
        lazy: bool = True,
        client: DeepOriginClient | None = None,
        sanitize: bool = True,
        remove_hydrogens: bool = False,
    ) -> str:
        """Download the structure file and reload :attr:`mol` from disk when applicable.

        After :meth:`deeporigin.drug_discovery.structures.entity.Entity.download`
        fetches the file, SDF paths trigger a full reload from :attr:`local_path` so
        pose coordinates from the file replace any placeholder 2D structure (for
        example SMILES-only pose rows from :meth:`LigandSet.from_json`).

        Args:
            lazy: Passed through to ``files.download``.
            client: DeepOrigin client; if ``None``, uses ``DeepOriginClient()``.
            sanitize: Passed to :meth:`from_sdf` when rehydrating from SDF.
            remove_hydrogens: Passed to :meth:`from_sdf` when rehydrating from SDF.

        Returns:
            The local file path (same as :meth:`Entity.download`).
        """

        prior_local = self.local_path
        out = super().download(lazy=lazy, client=client)
        if prior_local is None and self.local_path is not None:
            self._reload_mol_from_local_sdf_if_applicable(
                sanitize=sanitize,
                remove_hydrogens=remove_hydrogens,
            )
        return out

    @classmethod
    def _from_platform_record(
        cls,
        data: dict[str, Any],
        *,
        client: DeepOriginClient,
        download: bool = True,
        mol_file_override: str | None = None,
    ) -> Self:
        """Create a Ligand instance from a platform ligand record.

        When the record includes pinned molprops columns (``log_p``, ``cyp2d6``,
        ``logs_predicted``, etc.), they are applied to ADMET attributes and
        :attr:`properties` via :meth:`_apply_molprops_result`.

        Args:
            data: Ligand record returned by the platform entities API.
            client: DeepOrigin client used to download associated files.
            download: If True (default), download the mol file when present.
                If False, build from SMILES only and set :attr:`remote_path` to the
                platform mol file path without downloading.
            mol_file_override: Optional remote path (e.g. from execution ``userInputs``)
                used when ``download`` is False; falls back to ``data['mol_file']``.

        Returns:
            Ligand: A new Ligand instance.

        Raises:
            ValueError: If the ligand data contains neither a mol file nor a
                SMILES string, or if ``download`` is False and a mol file exists
                but no SMILES is available to hydrate the molecule.
        """
        mol_file = (
            mol_file_override if mol_file_override is not None else data.get("mol_file")
        )
        smiles = data.get("smiles") or data.get("canonical_smiles")

        if mol_file and not download:
            if not smiles:
                raise ValueError(
                    f"Ligand {data.get('id')}: cannot rehydrate without download when no "
                    "SMILES is present on the record."
                )
            ligand = cls.from_smiles(smiles=smiles, name=data.get("name") or "")
            ligand.id = data.get("id")
            ligand.remote_path = mol_file
            if data.get("name"):
                ligand.name = data["name"]
            if data.get("project_id") is not None:
                ligand.project_id = str(data["project_id"])
            molprops_row = _molprops_row_from_platform_record(data)
            if molprops_row:
                ligand._apply_molprops_result(molprops_row)
            return ligand

        if mol_file:
            local_file_path = client.files.download(remote_path=mol_file, lazy=True)
            ligand = cls.from_sdf(file_path=local_file_path)
            ligand.remote_path = mol_file
        elif smiles:
            ligand = cls.from_smiles(smiles=smiles)
        else:
            raise ValueError(
                f"Ligand {data.get('id')} has neither a mol file nor a SMILES string. "
                "Cannot create Ligand instance."
            )

        ligand.id = data.get("id")

        if data.get("name"):
            ligand.name = data["name"]

        if data.get("project_id") is not None:
            ligand.project_id = str(data["project_id"])

        molprops_row = _molprops_row_from_platform_record(data)
        if molprops_row:
            ligand._apply_molprops_result(molprops_row)

        return ligand

    @classmethod
    def from_id(
        cls,
        id: str,
        *,
        client: Optional[DeepOriginClient] = None,
        download: bool = True,
    ) -> Self:
        """Create a Ligand instance from a Deep Origin Data Platform ID.

        Fetches the ligand record from the platform. If the record has an
        associated mol file it is downloaded and used to construct the ligand;
        otherwise the SMILES string is used.

        Args:
            id: The Deep Origin Data Platform ID of the ligand.
            client: Optional DeepOriginClient instance. If not provided, uses
                the default client.
            download: If False, skip mol file download and hydrate from SMILES with
                ``remote_path`` set to the platform mol file path.

        Returns:
            Ligand: A new Ligand instance.

        Raises:
            ValueError: If the ligand data contains neither a mol file nor a
                SMILES string.
        """
        if client is None:
            client = DeepOriginClient()

        assert client.entities is not None, "client.entities is None"
        data = client.entities.get_ligand(id=id)
        return cls._from_platform_record(data=data, client=client, download=download)

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

    def unsupported_atom_symbols(self) -> list[str]:
        """Sorted unique atom symbols in :attr:`mol` not in ``SUPPORTED_ATOM_SYMBOLS``."""
        return sorted(
            {
                sym
                for sym in (a.GetSymbol() for a in self.mol.GetAtoms())
                if sym not in SUPPORTED_ATOM_SYMBOLS
            }
        )

    def has_unsupported_atoms(self) -> bool:
        """Whether :attr:`mol` contains any atom type not supported for docking workflows."""
        return bool(self.unsupported_atom_symbols())

    def prepare(self, *, remove_hydrogens: bool = False) -> Self:
        """Prepare the ligand for downstream workflows.

        The routine performs the following using RDKit and internal utilities:
        - Salt removal
        - Kekulization
        - Fragment validation (rejects multiple non-identical fragments)
        - Wildcard atom validation (rejects '*' atoms)
        - Validation of atom types against supported symbols

        Args:
            remove_hydrogens (bool): Whether to remove hydrogens from the SMILES representation.
                                   Defaults to False (preserve hydrogens).

        Returns:
            Ligand: The prepared ligand (self), for chaining.

        Raises:
            DeepOriginException: If preparation fails, unsupported atom types are present, or
                               multiple non-identical fragments are detected.
        """
        # Start from current molecule
        # 1) Salt removal and kekulization (reuse process_mol)
        self.process_mol()

        # 2) Fragment validation
        try:
            self.mol = validate_fragments(self.mol)
        except ValueError as e:
            raise DeepOriginException(f"Fragment validation failed: {str(e)}") from e

        # 3) Sanity sanitize and generate 2D coords if missing
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
            AllChem.Compute2DCoords(self.mol)  # ty:ignore[unresolved-attribute]

        # 4) Validate atom types
        atom_symbols = [atom.GetSymbol() for atom in self.mol.GetAtoms()]

        # Check for wildcard atoms first (explicit check)
        wildcard_atoms = [sym for sym in atom_symbols if sym == "*"]
        if wildcard_atoms:
            raise DeepOriginException(
                "Ligand contains wildcard ('*') atoms, which are not supported."
            )

        # Check for other unsupported atom types
        unsupported = self.unsupported_atom_symbols()
        if unsupported:
            smiles_hint = (
                self.smiles
                if self.smiles is not None
                else Chem.MolToSmiles(self.mol, canonical=True)
            )
            raise DeepOriginException(
                f"Unsupported atom types found in ligand: {', '.join(unsupported)}",
                f"For ligand with SMILES: {smiles_hint!r}",
            )

        # Update smiles and properties to reflect prepared state
        if remove_hydrogens:
            self.smiles = Chem.MolToSmiles(Chem.RemoveHs(self.mol), canonical=True)
        else:
            self.smiles = Chem.MolToSmiles(self.mol, canonical=True)
        self.prepared = True

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

        AllChem.EmbedMolecule(self.mol, randomSeed=seed)  # ty: ignore[unresolved-attribute]
        self.set_conformer_id(0)

    def add_hydrogens(self, add_coordinates: bool = True):
        """
        Add hydrogens to the molecule.

        Args:
            add_coordinates (bool): Whether to generate coordinates for added hydrogens
        """
        self.mol = Chem.AddHs(self.mol, addCoords=add_coordinates)
        self.smiles = Chem.MolToSmiles(self.mol, canonical=True)

    def has_hydrogens(self) -> bool:
        """
        Check if the molecule contains hydrogen atoms.

        This method determines if hydrogens are present by comparing the canonical
        SMILES string of the molecule with and without explicit hydrogens added.
        If the SMILES strings differ, the molecule contains hydrogens.

        Returns:
            bool: True if the molecule contains hydrogen atoms, False otherwise
        """
        mol = Chem.AddHs(self.mol)
        smiles = Chem.MolToSmiles(mol, canonical=True)
        return smiles == self.smiles

    def has_3d_structure(self) -> bool:
        """
        Check if the ligand has 3D coordinates (not just 2D).

        This method checks if the molecule has conformers with 3D coordinates.
        Ligands created from SMILES typically have 2D coordinates (z=0 for all atoms),
        while ligands with actual 3D structure have non-zero z coordinates.

        Returns:
            bool: True if the ligand has 3D coordinates (non-zero z values),
                False if it only has 2D coordinates or no conformers.
        """
        if self.mol.GetNumConformers() == 0:
            return False

        # Check if any atom has non-zero z coordinate (indicating 3D structure)
        coords = self.get_coordinates(0)
        if coords.shape[1] < 3:
            return False

        # Check if any z coordinate is significantly non-zero (not just 2D)
        z_coords = coords[:, 2]
        return bool(np.any(np.abs(z_coords) > 1e-3))

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
        Finalize a Ligand after construction (canonical SMILES, 2D coords, file props).

        Pass a molecule via the keyword argument ``mol`` (see class factories such as
        :meth:`from_smiles` and :meth:`from_rdkit_mol`).
        """

        self.process_mol()
        self.smiles = Chem.MolToSmiles(Chem.RemoveHs(self.mol), canonical=True)

        if not self.mol.GetConformers():
            AllChem.Compute2DCoords(self.mol)  # type: ignore[attr-defined]

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

    @property
    def formal_charge(self) -> int:
        """Compute the formal charge of the ligand molecule.

        Returns:
            int: The sum of formal charges of all atoms in the molecule.
        """
        return sum(atom.GetFormalCharge() for atom in self.mol.GetAtoms())

    @property
    def molecular_weight(self) -> float:
        """Compute the exact molecular weight of the ligand molecule.

        Returns:
            float: The exact molecular weight in atomic mass units.
        """
        return rdMolDescriptors.CalcExactMolWt(self.mol)

    @property
    def hbond_donor_count(self) -> int:
        """Compute the number of hydrogen bond donors in the ligand molecule.

        Returns:
            int: The number of hydrogen bond donors.
        """
        return rdMolDescriptors.CalcNumHBD(self.mol)

    @property
    def hbond_acceptor_count(self) -> int:
        """Compute the number of hydrogen bond acceptors in the ligand molecule.

        Returns:
            int: The number of hydrogen bond acceptors.
        """
        return rdMolDescriptors.CalcNumHBA(self.mol)

    @property
    def rotatable_bond_count(self) -> int:
        """Compute the number of rotatable bonds in the ligand molecule.

        Returns:
            int: The number of rotatable bonds.
        """
        return rdMolDescriptors.CalcNumRotatableBonds(self.mol)

    @property
    def tpsa(self) -> float:
        """Compute the Topological Polar Surface Area (TPSA) of the ligand molecule.

        Returns:
            float: The TPSA value in square Angstroms.
        """
        return rdMolDescriptors.CalcTPSA(self.mol)

    @property
    def canonical_smiles(self) -> str:
        """
        Canonical (RDKit) SMILES for this ligand.

        Notes:
        - Canonicalization is RDKit-specific.
        - Returns implicit-H SMILES by default (explicit Hs removed).
        - Preserves stereochemistry if present.
        """
        # Remove explicit Hs so we don't emit `[H]...` everywhere
        mol = Chem.RemoveHs(self.mol)

        # ensure sanitization:
        Chem.SanitizeMol(mol)

        return Chem.MolToSmiles(
            mol,
            canonical=True,
            isomericSmiles=True,  # keep stereochem
        )

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
        writer = cast(Callable[..., str | Path], self.write_to_file)
        return writer(output_path=output_path, output_format="mol")

    @beartype
    def to_sdf(
        self,
        output_path: Optional[str] = None,
    ) -> str:
        """Write the ligand to an SDF file.

        This is a local operation: it serializes the current :attr:`mol`. If the ligand
        has :attr:`remote_path` but no local file yet, raise; rehydrate with
        :meth:`download` first.

        Args:
            output_path: Path for the SDF file, or default under ``LIGANDS_DIR``.
        """

        self._assert_rehydrated_for_file_export(
            entity_label="Ligand",
            format_name="SDF",
        )

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
    def to_file(self, file_path: Optional[str | Path] = None) -> str:
        """Dump state to a file.

        Args:
            file_path: Path where the file will be written. If None, uses default path.

        Returns:
            str: Path to the written file.
        """
        return self.to_sdf(file_path)

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

        # Use a unique temp file per call to avoid race conditions when
        # multiple ligands are hashed in parallel (e.g. via run_func_in_parallel).
        fd, temp_sdf_path = tempfile.mkstemp(suffix=".sdf")
        os.close(fd)

        try:
            self.to_sdf(temp_sdf_path)

            with open(temp_sdf_path, "r", newline="") as f:
                sdf_text = f.read()

            # Normalize line endings for OS-agnostic hashing
            normalized_text = sdf_text.replace("\r\n", "\n").replace("\r", "\n")
            if not normalized_text.endswith("\n"):
                normalized_text = f"{normalized_text}\n"
            hash_hex = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        finally:
            os.remove(temp_sdf_path)

        return hash_hex

    @beartype
    def register(
        self,
        *,
        client: Optional[DeepOriginClient] = None,
        remote_path: Optional[str] = None,
        variant_name_tag: str = "",
    ) -> None:
        """Register the ligand as a new record in the data platform.

        Uploads the ligand file to remote storage (if available) and creates
        a new ligand record. Platform identity is
        ``(canonical_smiles, variant_name_tag)``; pass a unique
        ``variant_name_tag`` when you need a distinct row for the same SMILES.

        Args:
            client: DeepOriginClient instance. If None, uses DeepOriginClient().
            remote_path: Custom remote path to upload to. Overrides the
                default hash-based path.
            variant_name_tag: Optional variant tag included in the platform
                uniqueness key. Defaults to empty string.

        Returns:
            None. As a side effect, uploads the ligand and sets ``self.id``
            to the newly created record's ID.

        Note:
            If the ligand was created from a SMILES string without an SDF file,
            only the SMILES will be used (no file upload will occur).
        """
        if client is None:
            client = DeepOriginClient()

        mol_file: str | None = None
        if self.local_path is not None:
            self.upload(client=client, remote_path=remote_path)
            mol_file = self.remote_path

        kwargs: dict[str, Any] = {
            "smiles": self.smiles if self.smiles is not None else self.canonical_smiles,
        }

        if mol_file is not None:
            kwargs["mol_file"] = mol_file

        if self.name is not None:
            kwargs["name"] = self.name

        if variant_name_tag:
            kwargs["variant_name_tag"] = variant_name_tag

        try:
            kwargs["formal_charge"] = self.formal_charge
        except Exception:
            pass

        proj_id = self.resolved_project_id(client=client)
        if proj_id is not None:
            kwargs["project_id"] = proj_id

        result = client.entities.create_ligand(**kwargs)  # ty: ignore[unresolved-attribute]

        if "data" in result and "id" in result["data"]:
            self.id = result["data"]["id"]

    def sync(
        self,
        *,
        lazy: bool = False,
        client: Optional[DeepOriginClient] = None,
        remote_path: Optional[str] = None,
    ) -> None:
        """Sync the ligand to the data platform.

        Uploads the ligand file and links to an existing record if one with
        the same canonical SMILES already exists (setting ``id`` and
        ``remote_path`` from the record's ``mol_file`` when present), otherwise
        creates a new record via :meth:`register`.

        Args:
            lazy: If True, skip syncing when the ligand already has an ID.
                Defaults to False.
            client: DeepOriginClient instance. If None, uses DeepOriginClient().
            remote_path: Custom remote path to upload to. Overrides the
                default hash-based path.

        Note:
            If the ligand was created from a SMILES string without an SDF file, only the SMILES
            will be used for syncing (no file upload will occur).
        """

        if lazy and self.id is not None:
            return

        if client is None:
            client = DeepOriginClient()

        if remote_path is not None:
            self.remote_path = remote_path

        proj_id = self.resolved_project_id(client=client)
        scope_filter: dict[str, Any] = {}
        if proj_id is not None:
            scope_filter["project_id"] = proj_id

        smiles_value = self.smiles if self.smiles is not None else self.canonical_smiles
        response = client.entities.search_ligands(  # ty: ignore[unresolved-attribute]
            smiles=smiles_value,
            filter_dict=scope_filter if scope_filter else None,
        )
        data = response["data"]

        if not data:
            response = client.entities.search_ligands(  # ty: ignore[unresolved-attribute]
                canonical_smiles=self.canonical_smiles,
                filter_dict=scope_filter if scope_filter else None,
            )
            data = response["data"]

        if data:
            existing_ligand = data[0]
            if "id" in existing_ligand:
                self.id = existing_ligand["id"]
            mol_file = existing_ligand.get("mol_file")
            if mol_file:
                self.remote_path = mol_file
            return

        self.register(client=client, remote_path=remote_path)

    @beartype
    def update(
        self,
        *,
        client: Optional[DeepOriginClient] = None,
        remote_path: Optional[str] = None,
    ) -> None:
        """Update the ligand's ``mol_file`` on an existing platform record.

        Uploads the local structure file when present, then PATCHes
        ``mol_file`` on the record identified by ``self.id``. Use
        :meth:`sync` to link or create by identity; use ``update`` when you
        already have a platform ID.

        Args:
            client: DeepOriginClient instance. If None, uses DeepOriginClient().
            remote_path: Explicit remote path to set as ``mol_file``. When
                omitted, uploads ``local_path`` and uses the resulting path.

        Returns:
            None. Refreshes ``self.remote_path`` from the platform response.

        Raises:
            ValueError: If ``self.id`` is unset or no file path can be resolved.
        """
        if self.id is None:
            raise ValueError(
                "Cannot update a ligand without a platform id; "
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

        result = client.entities.update_ligand(self.id, mol_file=path)  # ty: ignore[unresolved-attribute]

        row = result.get("data")
        if isinstance(row, list):
            row = row[0] if row else None
        if isinstance(row, dict):
            mol_file = row.get("mol_file")
            if mol_file:
                self.remote_path = mol_file

    def _to_row(self, *, client: DeepOriginClient | None = None) -> dict[str, Any]:
        """Build a batch-create row dict from this ligand.

        Args:
            client: Used with :meth:`resolved_project_id` when ``project_id``
                is not set on this ligand.

        Returns:
            Dict suitable for ``batch_create_ligands`` rows.
        """
        smiles_value = self.smiles if self.smiles is not None else self.canonical_smiles
        row: dict[str, Any] = {
            "smiles": smiles_value,
            "variant_name_tag": "",
        }
        if self.local_path is not None:
            if self.remote_path is None:
                raise ValueError(
                    "remote_path is required when local_path is set; call upload() first."
                )
            row["mol_file"] = self.remote_path
        if self.name is not None:
            row["name"] = self.name
        try:
            row["formal_charge"] = self.formal_charge
        except Exception:
            warnings.warn(
                f"Could not compute molecular descriptors for "
                f"'{smiles_value}'; formal_charge defaults to 0.",
                stacklevel=2,
            )
            row.setdefault("formal_charge", 0)

        proj_id = self.resolved_project_id(client=client)
        if proj_id is not None:
            row["project_id"] = proj_id
        return row

    @beartype
    def to_pdb(self, output_path: Optional[str] = None) -> str | Path:
        """Write the ligand to a PDB file."""
        writer = cast(Callable[..., str | Path], self.write_to_file)
        return writer(output_path=output_path, output_format="pdb")

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

    def _ligand_viewer_html(self) -> str:
        """Raw HTML from the molstar viewer for this ligand (no iframe / display)."""
        sdf_file = self.to_sdf()
        viewer = MoleculeViewer(str(sdf_file), format="sdf")
        ligand_config = viewer.get_ligand_visualization_config()
        return viewer.render_ligand(ligand_config=ligand_config)

    def show(self) -> str | None:
        """
        Visualize the current state of the ligand molecule.

        Returns:
        - str: HTML representation of the visualization.

        Raises:
        - Exception: If visualization fails.


        """
        try:
            html = self._ligand_viewer_html()

            from deeporigin.utils.notebook import render_html

            return render_html(html)
        except Exception as e:
            raise DeepOriginException(f"Visualization failed: {str(e)}") from e

    def _repr_html_(self) -> str | None:
        """
        Return the HTML representation of the object for Jupyter Notebook.

        Returns:
            str: The HTML content.
        """
        try:
            print(self.mol)
            html = self._ligand_viewer_html()
            from deeporigin.utils.notebook import get_notebook_environment, render_html

            if get_notebook_environment() == "marimo":
                return render_html(html)
            return render_html(html, return_iframe_string=True)
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
        ligands_base_dir = _ensure_do_folder() / "ligands"
        ligands_base_dir.mkdir(parents=True, exist_ok=True)

        return str(ligands_base_dir)

    @beartype
    def _apply_molprops_result(self, props: dict[str, Any]) -> None:
        """Apply merged molprops API row to ADMET fields and ``properties``."""

        for api_key, attr_name in _MOLPROPS_RESPONSE_TO_ATTR.items():
            if api_key in props:
                setattr(self, attr_name, props[api_key])
        for key, value in props.items():
            if key in _MOLPROPS_ROW_SKIP_PROPERTY_KEYS:
                continue
            self.set_property(key, value)

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
                title="Invalid molecule",
                message="Invalid file format or file path or failed to sanitize the molecule",
                fix="Please check the file format and file path, and try again.",
            )

        return mol_rdk


@beartype
def ligands_to_dataframe(ligands: list[Ligand]) -> pd.DataFrame:
    """Build a DataFrame from ligands, including platform ids and SMILES.

    Each row uses :attr:`~deeporigin.drug_discovery.structures.entity.Entity.id`
    (may be ``None`` if the ligand was never synced). Property key ``id`` is not
    duplicated as its own column; the entity id column wins.

    Args:
        ligands: Ligands to serialize as rows.

    Returns:
        DataFrame with columns ``id``, ``SMILES``, known molprops output keys
        (in schema order when present), then any other property keys sorted.
    """

    skip_property_keys = {
        "_Name",
        "_SMILES",
        "initial_smiles",
    } | _MOLPROPS_ROW_SKIP_PROPERTY_KEYS

    all_keys: set[str] = set()
    for ligand in ligands:
        all_keys.update(ligand.properties.keys())

    property_keys = sorted(k for k in all_keys if k not in skip_property_keys)
    molprops_keys = [k for k in _MOLPROPS_RESPONSE_TO_ATTR if k in property_keys]
    other_keys = sorted(set(property_keys) - set(molprops_keys))

    property_columns: dict[str, list[Any]] = {}
    for key in molprops_keys + other_keys:
        property_columns[key] = [ligand.properties.get(key, None) for ligand in ligands]

    data: dict[str, list[Any]] = {"id": [ligand.id for ligand in ligands]}
    data["SMILES"] = [ligand.smiles for ligand in ligands]
    data.update(property_columns)

    column_order = ["id", "SMILES", *molprops_keys, *other_keys]
    return pd.DataFrame(data)[column_order]


def _tool_user_inputs_params(dto: dict[str, Any]) -> dict[str, Any]:
    """Return the inner docking ``inputs`` dict from an execution payload.

    Args:
        dto: Raw execution DTO from ``client.executions.create`` /
            ``client.executions.get``, or any dict carrying ``userInputs`` /
            ``inputs``.

    Returns:
        The dict that holds ``ligands`` (either ``userInputs`` itself or nested
        ``userInputs.inputs``).
    """

    root = dto.get("userInputs") or dto.get("inputs") or {}
    if not isinstance(root, dict):
        return {}
    inner = root.get("inputs")
    if isinstance(inner, dict):
        return inner
    return root


def _ligand_smiles_map_from_tool_payload(dto: dict[str, Any]) -> dict[str, str]:
    """Build ligand entity id -> SMILES from user inputs embedded in ``dto``."""

    params = _tool_user_inputs_params(dto)
    ligands = params.get("ligands") or []
    out: dict[str, str] = {}
    if not isinstance(ligands, list):
        return out
    for row in ligands:
        if not isinstance(row, dict):
            continue
        lid = row.get("id")
        smi = row.get("smiles")
        if lid is not None and isinstance(smi, str) and smi.strip():
            out[str(lid)] = smi.strip()
    return out


@dataclass
@beartype
class LigandSet:
    """
    A class representing a set of Ligand objects.

    Attributes:
        ligands (list[Ligand]): A list of Ligand instances contained in the set.

    """

    ligands: list[Ligand] = field(default_factory=list)

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

    def batches(self, batch_size: int | None) -> list[list[Ligand]]:
        """Split this set into consecutive chunks of ligands (same order as :attr:`ligands`).

        Args:
            batch_size: Maximum ligands per chunk. ``None`` returns a single chunk
                containing all ligands (including when the set is empty). Must be an
                ``int`` when not ``None``; other types are rejected by runtime type
                checking. When the number of ligands is not a multiple of ``batch_size``,
                the **last** batch is shorter (it holds the remainder only).

        Returns:
            Non-empty list of batches when ``batch_size`` is ``None``; otherwise a list
            of one or more consecutive slices of :attr:`ligands`.

        Raises:
            ValueError: If ``batch_size`` is set and not positive.
            beartype.roar.BeartypeCallHintParamViolation: If ``batch_size`` is neither
                ``None`` nor an ``int`` (e.g. a ``float`` or ``str``).
        """

        if batch_size is None:
            return [self.ligands]
        if batch_size <= 0:
            raise ValueError("batch_size must be positive when set.")
        out: list[list[Ligand]] = []
        ligands = self.ligands
        for i in range(0, len(ligands), batch_size):
            out.append(ligands[i : i + batch_size])
        return out

    def to_dict(self) -> list[dict[str, str]]:
        """Convert this set to a list of dicts, one per ligand.

        Each dict has ``id`` (platform id when set, else ``"0"``, ``"1"``, … by
        position in this set) and ``smiles``. For batched API calls with globally
        unique ids, ensure each :class:`Ligand` ``id`` is set before building the set.

        Returns:
            One ``{"id": ..., "smiles": ...}`` dict per ligand, in order.

        Raises:
            ValueError: If a ligand has no non-empty ``smiles``.
        """

        out: list[dict[str, str]] = []
        for j, lg in enumerate(self.ligands):
            sm = lg.smiles
            if sm is None or sm == "":
                raise ValueError(
                    f'ligands[{j}] must include a non-empty "smiles" string.'
                )
            lid = lg.id if lg.id is not None else str(j)
            out.append({"id": lid, "smiles": sm})
        return out

    def random_sample(self, n: int) -> Self:
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

    def filter_unsupported(self) -> Self:
        """
        Return a new set excluding ligands whose molecules contain atom types
        outside :data:`~deeporigin.drug_discovery.constants.SUPPORTED_ATOM_SYMBOLS`
        (see :meth:`Ligand.has_unsupported_atoms`).
        """
        return LigandSet(
            ligands=[lg for lg in self.ligands if not lg.has_unsupported_atoms()]
        )

    def __str__(self) -> str:
        """Return string representation of the LigandSet.

        Returns:
            str: String representation showing the number of ligands and unique SMILES.
        """
        num_ligands = len(self.ligands)
        if num_ligands == 0:
            return "LigandSet(0 ligands)"

        unique_smiles = len({ligand.smiles for ligand in self.ligands if ligand.smiles})
        return f"LigandSet({num_ligands} ligands, {unique_smiles} unique SMILES)"

    def __repr__(self) -> str:
        """Return string representation of the LigandSet.

        Returns:
            str: String representation showing the number of ligands and unique SMILES.
        """
        return self.__str__()

    def _render_view(self) -> str:
        """Render a custom widget view for the LigandSet.

        Returns:
            str: HTML string representing the LigandSet summary.
        """
        num_ligands = len(self.ligands)

        # Calculate unique SMILES to determine if these are poses of the same ligand
        unique_smiles = (
            len(
                {
                    ligand.properties.get("SMILES", ligand.smiles)
                    for ligand in self.ligands
                    if ligand.smiles
                }
            )
            if num_ligands > 0
            else 0
        )

        # Build summary HTML
        # Use "poses" only when there are multiple ligands with the same SMILES
        if unique_smiles == 1 and num_ligands > 1:
            ligand_word = "poses"
        else:
            ligand_word = "ligand" if num_ligands == 1 else "ligands"
        html_parts = [
            "<div style='width: 500px; padding: 15px; border: 1px solid #ddd; border-radius: 6px; background-color: #f9f9f9;'>",
            f"<h3 style='margin-top: 0; color: #333;'>LigandSet with {num_ligands} {ligand_word}</h3>",
        ]

        if num_ligands > 0:
            # Check if all ligands are prepared
            all_prepared = all(ligand.prepared for ligand in self.ligands)

            # Check protonation status
            any_not_protonated = any(
                ligand.protonated_at_ph is None for ligand in self.ligands
            )
            # Check if all ligands are protonated at the same pH
            all_protonated_at_same_ph = False
            common_ph = None
            if not any_not_protonated and num_ligands > 0:
                ph_values = {
                    ligand.protonated_at_ph
                    for ligand in self.ligands
                    if ligand.protonated_at_ph is not None
                }
                if len(ph_values) == 1:
                    all_protonated_at_same_ph = True
                    common_ph = ph_values.pop()

            # Check 3D structure status
            all_have_3d = all(ligand.has_3d_structure() for ligand in self.ligands)
            all_have_2d = all(not ligand.has_3d_structure() for ligand in self.ligands)

            # Add summary statistics
            if unique_smiles == 1:
                # Get the SMILES string (all ligands have the same one)
                smiles_str = next(
                    (ligand.smiles for ligand in self.ligands if ligand.smiles), None
                )
                if smiles_str:
                    smiles_line = f"<p style='margin: 8px 0;'><strong>SMILES:</strong> {smiles_str}"
                    if all_prepared:
                        smiles_line += " <span class='badge text-bg-primary' style='font-variant: small-caps;'>PREPARED</span>"
                    if any_not_protonated:
                        smiles_line += " <span class='badge text-bg-secondary' style='font-variant: small-caps;'>NOT PROTONATED</span>"
                    elif all_protonated_at_same_ph:
                        smiles_line += f" <span class='badge text-bg-success' style='font-variant: small-caps;'>PROTONATED (pH={common_ph})</span>"
                    if all_have_2d:
                        smiles_line += " <span class='badge text-bg-info' style='font-variant: small-caps;'>2D</span>"
                    elif all_have_3d:
                        smiles_line += " <span class='badge text-bg-info' style='font-variant: small-caps;'>3D</span>"
                    smiles_line += "</p>"
                    html_parts.append(smiles_line)
            else:
                unique_smiles_line = f"<p style='margin: 8px 0;'><strong>{unique_smiles}</strong> unique SMILES"
                if all_prepared:
                    unique_smiles_line += " <span class='badge text-bg-primary' style='font-variant: small-caps;'>PREPARED</span>"
                if any_not_protonated:
                    unique_smiles_line += " <span class='badge text-bg-secondary' style='font-variant: small-caps;'>NOT PROTONATED</span>"
                elif all_protonated_at_same_ph:
                    unique_smiles_line += f" <span class='badge text-bg-success' style='font-variant: small-caps;'>PROTONATED (pH={common_ph})</span>"
                if all_have_2d:
                    unique_smiles_line += " <span class='badge text-bg-info' style='font-variant: small-caps;'>2D</span>"
                elif all_have_3d:
                    unique_smiles_line += " <span class='badge text-bg-info' style='font-variant: small-caps;'>3D</span>"
                unique_smiles_line += "</p>"
                html_parts.append(unique_smiles_line)

            # Show property summary if available
            if self.ligands and self.ligands[0].properties:
                all_props = set()
                for ligand in self.ligands:
                    all_props.update(ligand.properties.keys())
                sorted_props = sorted(all_props)
                props_display = ", ".join(sorted_props[:10])
                if len(sorted_props) > 10:
                    props_display += f" and {len(sorted_props) - 10} more..."
                html_parts.append(
                    f"<p style='margin: 8px 0;'>Properties: {props_display}</p>"
                )

            # Add action hints
            action_hints = []
            action_hints.append(
                "Use <code>.to_dataframe()</code> to convert to a dataframe, "
                "<code>.show_df()</code> to view dataframewith structures, "
                "or <code>.show()</code> for 3D visualization"
            )

            # Add prepare hint if any ligand is not prepared
            if not all_prepared:
                action_hints.append(
                    "<code>.prepare()</code> to prepare ligands for docking"
                )

            html_parts.append(
                "<div style='margin-top: 12px; padding-top: 12px; border-top: 1px solid #ddd;'>"
                "<p style='margin: 4px 0; font-size: 0.9em; color: #666;'>"
                f"<em>{', '.join(action_hints)}</em>"
                "</p>"
                "</div>"
            )
        else:
            html_parts.append(
                "<p style='margin: 8px 0; color: #999;'><em>Empty LigandSet</em></p>"
            )

        html_parts.append("</div>")
        return "".join(html_parts)

    def _repr_html_(self) -> str | None:
        """Return HTML representation for Jupyter notebooks.

        Displays a summary of the LigandSet including the number of ligands
        and key statistics.

        Returns:
            str: HTML string representing the LigandSet summary.
        """
        return self._render_view()

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

        PandasTools.AddMoleculeColumnToFrame(df, smilesCol="SMILES", molCol="Ligand")
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
        file_path: str | Path,
        smiles_column: str = "smiles",
    ) -> Self:
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
    def from_file(
        cls,
        file_path: str | Path,
        *,
        sanitize: bool = True,
        remove_hydrogens: bool = False,
        smiles_column: str = "smiles",
    ) -> Self:
        """
        Create a LigandSet from an SDF or CSV file.

        ``.sdf`` paths are validated as SDF (extension and content) and loaded with
        :meth:`from_sdf`. ``.csv`` paths are validated as CSV (extension) and loaded with
        :meth:`from_csv`.

        Args:
            file_path: Path to an ``.sdf`` or ``.csv`` file.
            sanitize: Whether to sanitize molecules (SDF only). Defaults to True.
            remove_hydrogens: Whether to remove hydrogens (SDF only). Defaults to False.
            smiles_column: Name of the SMILES column (CSV only). Defaults to ``"smiles"``.

        Returns:
            LigandSet: Ligands created from the file.

        Raises:
            FileNotFoundError: If the file does not exist.
            DeepOriginException: If the path is not a supported file type or loading fails.
        """
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix == ".sdf":
            _assert_path_is_sdf(path)
            return cls.from_sdf(
                path, sanitize=sanitize, remove_hydrogens=remove_hydrogens
            )
        if suffix == ".csv":
            _assert_path_is_csv(path)
            return cls.from_csv(path, smiles_column=smiles_column)
        raise DeepOriginException(
            f"Unsupported file type {suffix!r} for '{path}'. Expected .sdf or .csv."
        )

    @classmethod
    def from_sdf(
        cls,
        file_path: str | Path,
        *,
        sanitize: bool = True,
        remove_hydrogens: bool = False,
    ) -> Self:
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
                    ligand.local_path = str(path)
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
    ) -> Self:
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

    @staticmethod
    def _strip_nonempty_str(value: Any) -> str | None:
        """Return stripped string if ``value`` is a non-empty str, else None."""

        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
        return None

    @staticmethod
    def _path_points_to_existing_local_file(path: str) -> bool:
        """Return True if ``path`` refers to an existing regular file on disk."""

        try:
            return Path(path).expanduser().is_file()
        except (OSError, ValueError):
            return False

    @staticmethod
    def _apply_file_path_to_paths(
        *,
        remote_path: str | None,
        file_path: str,
    ) -> tuple[str | None, str | None]:
        """Set local and/or remote path from a ``file_path`` field (pose / API shape)."""

        local_path: str | None = None
        out_remote = remote_path
        is_local_file = LigandSet._path_points_to_existing_local_file(file_path)
        if out_remote is None:
            if is_local_file:
                local_path = file_path
            else:
                out_remote = file_path
        elif is_local_file:
            local_path = file_path
        return local_path, out_remote

    @staticmethod
    def _resolve_pose_entry_paths(
        entry: dict[str, Any], idx: int
    ) -> tuple[str | None, str | None]:
        """Extract ``(local_path, remote_path)`` from a pose dict (mirrors pocket path rules).

        Args:
            entry: Single pose dict (``file_path``, ``local_path``, and/or ``remote_path``).
            idx: Index in the pose list (for error messages).

        Returns:
            At least one of ``local_path`` or ``remote_path`` is non-``None``.

        Raises:
            ValueError: If no usable path is present.
        """

        remote_path = LigandSet._strip_nonempty_str(entry.get("remote_path"))
        file_path = LigandSet._strip_nonempty_str(entry.get("file_path"))
        explicit_local = LigandSet._strip_nonempty_str(entry.get("local_path"))

        local_path: str | None = None

        if file_path is not None:
            local_path, remote_path = LigandSet._apply_file_path_to_paths(
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

    _POSE_JSON_RESERVED: ClassVar[frozenset[str]] = frozenset(
        {
            "file_path",
            "local_path",
            "remote_path",
            "smiles",
            "canonical_smiles",
            "ligand_id",
            "name",
            "project_id",
            "id",
        }
    )

    @classmethod
    def _ligand_from_pose_dict(
        cls,
        entry: dict[str, Any],
        idx: int,
        *,
        client: Optional[DeepOriginClient],
        sanitize: bool,
        remove_hydrogens: bool,
    ) -> Ligand:
        """Materialize one :class:`Ligand` from a pose metadata dict."""

        local_path, remote_path = cls._resolve_pose_entry_paths(entry, idx)
        reserved = cls._POSE_JSON_RESERVED

        if local_path is not None:
            lig = Ligand.from_sdf(
                local_path,
                sanitize=sanitize,
                remove_hydrogens=remove_hydrogens,
            )
            if remote_path is not None:
                lig.remote_path = remote_path
        else:
            smiles = (
                entry.get("smiles")
                or entry.get("canonical_smiles")
                or entry.get("ligand_smiles")
            )
            if not isinstance(smiles, str) or not smiles.strip():
                raise ValueError(
                    f"Pose at index {idx} has remote SDF {remote_path!r} but no "
                    f"'smiles' or 'canonical_smiles'; add SMILES to the pose dict or "
                    f"merge inputs from the docking execution before calling from_json."
                )
            lig = Ligand.from_smiles(
                smiles=smiles.strip(),
                name=(entry.get("name") or "") or "",
            )
            if remote_path is None:
                raise ValueError(
                    f"Pose at index {idx} resolved to no remote_path for lazy SDF load."
                )
            lig.remote_path = remote_path

        lid = entry.get("ligand_id")
        if lid is not None:
            lig.id = str(lid)

        proj = LigandSet._strip_nonempty_str(entry.get("project_id"))
        if proj is None and client is not None:
            proj = getattr(client, "project_id", None)
        if proj is not None:
            lig.project_id = proj

        rex = entry.get("id")
        if rex is not None:
            lig.properties["id"] = str(rex)

        for key, val in entry.items():
            if key in reserved:
                continue
            lig.properties[str(key)] = val

        return lig

    @classmethod
    def from_json(
        cls,
        data: list[dict[str, Any]],
        *,
        client: Optional[DeepOriginClient] = None,
        sanitize: bool = True,
        remove_hydrogens: bool = False,
    ) -> Self:
        """Build a ``LigandSet`` from pose metadata (no SDF download).

        Each entry follows the docking ``poses[]`` shape: a ``file_path`` that is
        either a platform remote key or an existing local SDF, optional
        ``local_path`` / ``remote_path``, plus optional ``smiles`` /
        ``canonical_smiles``. When only a **remote** path is available, a
        non-empty SMILES field is required so an RDKit molecule can be built;
        the pose SDF is then loaded lazily via :meth:`Ligand.download`.

        Args:
            data: List of pose dicts (for example merged ``jobOutputs.poses``).
            client: Optional client; ``project_id`` falls back to the client's
                ``project_id`` when missing on an entry.
            sanitize: Passed to :meth:`from_sdf` when a local SDF path is used.
            remove_hydrogens: Passed to :meth:`from_sdf` when a local SDF path is used.

        Returns:
            One :class:`Ligand` per pose entry, ordered as in ``data``.

        Raises:
            ValueError: If a remote-only entry lacks SMILES, or paths are invalid.
        """

        ligands_out: list[Ligand] = []
        for idx, raw in enumerate(data):
            if not isinstance(raw, dict):
                raise ValueError(
                    f"Pose at index {idx} must be a dict, got {type(raw)!r}."
                )
            entry = dict(raw)
            ligands_out.append(
                cls._ligand_from_pose_dict(
                    entry,
                    idx,
                    client=client,
                    sanitize=sanitize,
                    remove_hydrogens=remove_hydrogens,
                )
            )

        return cls(ligands=ligands_out)

    @classmethod
    def from_result(
        cls,
        *,
        protein_id: str | None = None,
        execution_id: str | None = None,
        best_pose: bool | None = None,
        client: Optional[DeepOriginClient] = None,
    ) -> Self:
        """Load docking poses from the data platform without downloading SDF files.

        Fetches result-explorer rows via ``client.results.get_poses``, resolves
        SMILES from each row's ``compute_job_id`` execution (``userInputs``) when
        absent on the pose payload, then delegates to :meth:`from_json`.

        Args:
            protein_id: Optional protein id filter.
            execution_id: Optional compute job / execution id filter.
            best_pose: If True, restrict to best pose per ligand. If False,
                include all poses. If None (default), no filter is applied.
            client: Optional ``DeepOriginClient``; defaults to a new client.

        Returns:
            A ``LigandSet`` with one ligand per pose record.

        Raises:
            ValueError: If no pose records match, or a pose cannot be built.
        """

        if client is None:
            client = DeepOriginClient()

        get_poses_kwargs: dict[str, Any] = dict(
            protein_id=protein_id,
            compute_job_id=execution_id,
            limit=None,
        )
        if best_pose is not None:
            get_poses_kwargs["best_pose"] = best_pose

        response = client.results.get_poses(**get_poses_kwargs)
        records = response.get("data", [])

        if not records:
            raise ValueError(
                "No docking pose results found for "
                f"protein_id={protein_id!r} execution_id={execution_id!r}."
            )

        job_ids: set[str] = set()
        if execution_id:
            job_ids.add(str(execution_id))
        for rec in records:
            jid = rec.get("compute_job_id")
            if jid:
                job_ids.add(str(jid))

        smiles_by_job: dict[str, dict[str, str]] = {}
        for jid in job_ids:
            try:
                dto = client.executions.get(jid)  # ty:ignore[unresolved-attribute]
            except Exception:
                smiles_by_job[jid] = {}
            else:
                smiles_by_job[jid] = _ligand_smiles_map_from_tool_payload(dto)

        rows: list[dict[str, Any]] = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            data = rec.get("data")
            if not isinstance(data, dict):
                data = {}
            row = dict(data)
            jid = str(rec.get("compute_job_id") or execution_id or "")
            smi_map = smiles_by_job.get(jid, {})
            lid = row.get("ligand_id")
            if (
                not (isinstance(row.get("smiles"), str) and row["smiles"].strip())
                and not (
                    isinstance(row.get("canonical_smiles"), str)
                    and row["canonical_smiles"].strip()
                )
                and lid is not None
            ):
                sm = smi_map.get(str(lid))
                if sm:
                    row["smiles"] = sm
            rid = rec.get("id")
            if rid is not None:
                row["id"] = str(rid)
            rows.append(row)

        return cls.from_json(rows, client=client)

    @classmethod
    def from_dir(cls, directory: str | Path) -> Self:
        """
        Create a LigandSet instance from a directory containing SDF files.
        """
        directory = Path(directory)
        if not directory.is_dir():
            raise ValueError(f"{directory} is not a valid directory")

        ligands = []

        # Process SDF files
        sdf_files = list(directory.glob("*.sdf"))
        for sdf_file in sdf_files:
            this_file = str(sdf_file)
            this_set = cls.from_sdf(this_file)
            for ligand in this_set.ligands:
                ligand.local_path = this_file
            ligands.extend(this_set.ligands)

        # Process CSV files
        csv_files = list(directory.glob("*.csv"))
        for csv_file in csv_files:
            this_file = str(csv_file)
            this_set = cls.from_csv(this_file)
            for ligand in this_set.ligands:
                ligand.local_path = this_file
            ligands.extend(this_set.ligands)

        return cls(ligands=ligands)

    def add_hydrogens(self) -> None:
        """Add hydrogens to all ligands in the set."""
        for ligand in self.ligands:
            ligand.add_hydrogens()

    @jupyter_visualization
    def show(self) -> str | None:
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

    def prepare(self, *, remove_hydrogens: bool = False) -> Self:
        """
        Prepare all ligands in the set for downstream workflows.

        This calls the prepare() method on each Ligand in the set, which performs:
        - Salt removal
        - Kekulization
        - Fragment validation (rejects multiple non-identical fragments)
        - Validation of atom types against supported symbols

        Args:
            remove_hydrogens (bool): Whether to remove hydrogens from the SMILES representation.
                                   Defaults to False (preserve hydrogens).

        Returns:
            LigandSet: The prepared LigandSet (self), for chaining.

        Raises:
            DeepOriginException: If preparation fails for any ligand, unsupported atom types are present,
                               or multiple non-identical fragments are detected.
        """
        for ligand in self.ligands:
            ligand.prepare(remove_hydrogens=remove_hydrogens)
        return self

    def embed(self):
        """
        Minimize all ligands in the set using their 3D optimization routines.
        This calls the embed() method on each Ligand in the set.
        """
        for ligand in self.ligands:
            ligand.embed()
        return self

    @beartype
    def to_sdf(
        self,
        output_path: Optional[str] = None,
    ) -> str:
        """Write all ligands to one SDF file, preserving properties from each ``mol``.

        This is a local operation. Each ligand must already be rehydrated if it has
        ``remote_path`` but no local file (call :meth:`Ligand.download` or
        :meth:`LigandSet.download` first, or use ``from_id(..., download=True)``).

        Args:
            output_path: Path to the output SDF file.

        Returns:
            Path to the written SDF file.
        """
        from pathlib import Path

        from rdkit import Chem

        if output_path is None:
            output_path = f"{tempfile.mkstemp()[1]}.sdf"

        path = Path(output_path)
        writer = Chem.SDWriter(str(path))
        try:
            for ligand in self.ligands:
                ligand._assert_rehydrated_for_file_export(
                    entity_label="Ligand",
                    format_name="SDF",
                )
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

    @beartype
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
        """Download platform files for ligands that have ``remote_path`` but no local file.

        Selects ligands where :attr:`~Ligand.remote_path` is set and
        :attr:`~Ligand.local_path` is ``None``,         fetches distinct remotes in parallel with
        :meth:`deeporigin.platform.files.FilesClient.download_many`, assigns each
        ligand's :attr:`~Ligand.local_path` from the returned remote→local mapping,
        then reloads :attr:`~Ligand.mol` from SDF when applicable.

        Ligands without ``remote_path``, with empty ``remote_path``, or that already
        have ``local_path`` set are left unchanged.

        Args:
            client: DeepOrigin client. If ``None``, uses ``DeepOriginClient()``.
            lazy: Passed to ``download_many``; when ``True``, existing cache files are
                reused.
            max_workers: Maximum concurrent downloads for ``download_many``.
            skip_errors: When ``False`` (default), any failed download in the batch
                raises. When ``True``, per-ligand failures during path assignment or SDF
                reload are skipped and that ligand keeps prior state.
            sanitize: Passed to :meth:`Ligand.from_sdf` when rehydrating SDF downloads.
            remove_hydrogens: Passed to :meth:`Ligand.from_sdf` when rehydrating.

        Raises:
            RuntimeError: If ``skip_errors`` is ``False`` and ``download_many`` reports
                failures.
        """

        pending = [
            lg for lg in self.ligands if lg.remote_path and lg.local_path is None
        ]
        if not pending:
            return
        if client is None:
            client = DeepOriginClient()
        remotes = list(
            dict.fromkeys(rp for rp in (lg.remote_path for lg in pending) if rp)
        )
        paths_by_remote = client.files.download_many(
            files=remotes,
            lazy=lazy,
            max_workers=max_workers,
            skip_errors=skip_errors,
        )
        for lg in pending:
            rp = lg.remote_path
            if not rp:
                continue
            local_path = paths_by_remote.get(rp)
            if local_path is None:
                if skip_errors:
                    continue
                raise RuntimeError(
                    f"download_many returned no path for remote_path={rp!r}"
                )
            try:
                lg.local_path = local_path
                lg._reload_mol_from_local_sdf_if_applicable(
                    sanitize=sanitize,
                    remove_hydrogens=remove_hydrogens,
                )
            except Exception:
                if skip_errors:
                    continue
                raise

    def to_smiles(self) -> list[str]:
        """Convert all ligands in the set to SMILES strings."""
        return [ligand.smiles for ligand in self.ligands]

    @staticmethod
    def _index_by_canonical_smiles(records: list[dict]) -> dict[str, dict]:
        """Build a ``canonical_smiles → record`` mapping from API records.

        Args:
            records: List of dicts returned by a search or batch-create call.

        Returns:
            Dict keyed by canonical_smiles.
        """
        index: dict[str, dict] = {}
        for record in records:
            cs = record.get("canonical_smiles")
            if cs is not None:
                index[cs] = record
        return index

    @beartype
    def upload(
        self,
        *,
        client: Optional[DeepOriginClient] = None,
        max_workers: int = 20,
    ) -> None:
        """Upload structure files for ligands that have a local file.

        For each ligand with non-``None`` :attr:`~Ligand.local_path`, serializes
        and assigns :attr:`~Ligand.remote_path` (same contract as
        :meth:`Ligand.upload`), then uploads all files in parallel via
        :meth:`deeporigin.platform.files.FilesClient.upload_many`. Ligands
        without ``local_path`` are skipped.

        Args:
            client: DeepOrigin client. If None, uses ``DeepOriginClient()``.
            max_workers: Maximum concurrent uploads (passed to ``upload_many``).
        """

        to_upload = [lig for lig in self.ligands if lig.local_path is not None]
        if not to_upload:
            return
        if client is None:
            client = DeepOriginClient()
        files: dict[str, str] = {}
        for lig in to_upload:
            stashed_remote_path = lig.remote_path
            lig.remote_path = None
            try:
                local_file = lig.to_file()
            finally:
                lig.remote_path = stashed_remote_path

            if lig.remote_path is None:
                lig.remote_path = (
                    f"{lig._remote_path_base}{lig.to_hash()}{lig._preferred_ext}"
                )
            files[str(local_file)] = lig.remote_path

        client.files.upload_many(files=files, max_workers=max_workers)

    def sync(
        self,
        *,
        lazy: bool = False,
        client: Optional[DeepOriginClient] = None,
    ) -> None:
        """Sync the ligand set to the data platform.

        For every ligand in the set this method:

        1. Searches the data platform for existing ligands whose
           ``canonical_smiles`` match (batched into a single request via
           ``search_ligands(smiles_list=…)``).
        2. For ligands that already exist remotely, updates the local ``id`` and
           sets ``remote_path`` from the record's ``mol_file`` when present.
        3. For ligands that are new, uploads files to remote storage (if a
           local_path is present) and batch-creates them in a single API call.
           Ligands sharing a canonical SMILES (e.g. multiple poses of the
           same molecule in an SDF) are deduplicated before the create call;
           all duplicates end up pointing at the single platform record.
        4. Updates the local ``id`` values from the created records.

        .. note::
            The batch-create step is all-or-nothing: if it fails (e.g.
            network error, invalid data), none of the new ligands will
            receive an ``id``.

        Args:
            lazy: If True, skip syncing ligands that already have an id.
            client: DeepOriginClient instance. If None, uses
                DeepOriginClient().

        Raises:
            DeepOriginException: If any ligand to be synced contains atom types
                outside :data:`~deeporigin.drug_discovery.constants.SUPPORTED_ATOM_SYMBOLS`.
            ValueError: If any ligand to be synced has no ``canonical_smiles``.
        """
        if not self.ligands:
            return

        ligands_to_sync = (
            [lig for lig in self.ligands if lig.id is None]
            if lazy
            else list(self.ligands)
        )
        if not ligands_to_sync:
            return

        unsupported = [lig for lig in ligands_to_sync if lig.has_unsupported_atoms()]
        if unsupported:
            symbols = sorted(
                {s for lig in unsupported for s in lig.unsupported_atom_symbols()}
            )
            raise DeepOriginException(
                f"Cannot sync ligand set: {len(unsupported)} ligand(s) contain "
                f"unsupported atom type(s) for docking workflows: {', '.join(symbols)}. "
                "Fix or remove those atoms before calling sync()."
            )

        invalid = [lig for lig in ligands_to_sync if lig.canonical_smiles is None]
        if invalid:
            raise ValueError(
                f"{len(invalid)} ligand(s) have no canonical_smiles and "
                "cannot be synced. Ensure every ligand has a valid SMILES or "
                "mol before calling sync()."
            )

        if client is None:
            client = DeepOriginClient()

        proj_id = (
            ligands_to_sync[0].resolved_project_id(client=client)
            if ligands_to_sync
            else None
        )
        scope_filter: dict[str, Any] = {}
        if proj_id is not None:
            scope_filter["project_id"] = proj_id

        # De-duplicate the search by canonical SMILES -- ``smiles_list`` maps
        # to an ``in`` filter, so duplicates add no information but inflate
        # the request.
        unique_smiles_list = list({lig.canonical_smiles for lig in ligands_to_sync})
        response = client.entities.search_ligands(
            smiles_list=unique_smiles_list,
            # Do not cap at len(unique_smiles_list): the platform may return
            # multiple rows per canonical SMILES, and a tight limit can exclude
            # less-common matches (e.g. CCCO) when duplicates (e.g. CCO) fill the page.
            limit=None,
            filter_dict=scope_filter if scope_filter else None,
        )
        existing_by_smiles = self._index_by_canonical_smiles(response.get("data", []))

        to_create: list[Ligand] = []
        for lig in ligands_to_sync:
            record = existing_by_smiles.get(lig.canonical_smiles)
            if record is not None:
                lig.id = record["id"]
                mol_file = record.get("mol_file")
                if mol_file:
                    lig.remote_path = mol_file
            else:
                to_create.append(lig)

        if not to_create:
            return

        # The platform enforces a uniqueness constraint on
        # ``(project_scope_key, canonical_smiles, variant_name_tag)``, so a
        # batch can contain at most one row per canonical SMILES. A single
        # input (e.g. a bulk docking SDF) can easily include the same molecule
        # multiple times as different poses/conformers, which all share the
        # same canonical SMILES. Pick one representative per canonical SMILES
        # for the create call, then fan the resulting id/mol_file back out to
        # every duplicate.
        representatives: list[Ligand] = []
        duplicates_by_smiles: dict[str, list[Ligand]] = {}
        for lig in to_create:
            cs = lig.canonical_smiles
            if cs not in duplicates_by_smiles:
                duplicates_by_smiles[cs] = []
                representatives.append(lig)
            duplicates_by_smiles[cs].append(lig)

        LigandSet(ligands=representatives).upload(client=client)

        rows = [lig._to_row(client=client) for lig in representatives]
        result = client.entities.batch_create_ligands(rows=rows)
        created_by_smiles = self._index_by_canonical_smiles(result.get("data", []))

        for cs, duplicates in duplicates_by_smiles.items():
            record = created_by_smiles.get(cs)
            if record is None:
                continue
            mol_file = record.get("mol_file")
            for lig in duplicates:
                lig.id = record["id"]
                if mol_file:
                    lig.remote_path = mol_file

    @classmethod
    def from_smiles(cls, smiles: list[str] | set[str]) -> Self:
        """Create a LigandSet from a list of SMILES strings.

        Args:
            smiles: SMILES strings to convert into ligands.

        Returns:
            A new LigandSet containing one Ligand per SMILES string.
        """
        return cls(ligands=[Ligand.from_smiles(s) for s in smiles])

    @classmethod
    def from_ids(
        cls,
        ids: list[str],
        *,
        client: DeepOriginClient | None = None,
        download: bool = True,
        ligand_inputs: list[dict[str, Any]] | None = None,
    ) -> Self:
        """Create a LigandSet by fetching ligands from the platform by ID.

        Args:
            ids: List of Deep Origin Data Platform ligand IDs.
            client: Optional API client. Uses the default if not provided.
            download: If True (default), download mol files when present. If False,
                hydrate from SMILES and set ``remote_path`` from the record (or
                ``mol_file`` on the matching ``ligand_inputs`` row) without downloading.
            ligand_inputs: Optional list of dicts (e.g. execution ``userInputs.ligands``)
                keyed by ``id``; ``mol_file`` on a row overrides the API path when
                ``download`` is False.

        Returns:
            A new LigandSet containing the rehydrated ligands.

        Notes:
            This delegates entity retrieval to ``client.entities.get_ligands()``
            and preserves the order of the requested IDs.
        """
        if client is None:
            client = DeepOriginClient()
        records = client.entities.get_ligands(ids=ids)
        records_by_id = {record["id"]: record for record in records if record.get("id")}
        missing_ids = [ligand_id for ligand_id in ids if ligand_id not in records_by_id]
        if missing_ids:
            raise ValueError(
                f"Failed to rehydrate all requested ligands. Missing IDs: {missing_ids}"
            )

        def _mol_file_override(ligand_id: str) -> str | None:
            if not ligand_inputs:
                return None
            for row in ligand_inputs:
                if row.get("id") == ligand_id:
                    return row.get("mol_file")
            return None

        def _build(ligand_id: str) -> Ligand:
            return Ligand._from_platform_record(
                data=records_by_id[ligand_id],
                client=client,
                download=download,
                mol_file_override=_mol_file_override(ligand_id),
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            ligands = list(executor.map(_build, ids))

        return cls(ligands=ligands)

    def to_rdkit_mols(self) -> list[Chem.Mol]:
        """
        Convert all ligands in the set to RDKit molecules.
        """
        return [ligand.mol for ligand in self.ligands]

    def mcs(self) -> Chem.Mol:
        """
        Generates the Most Common Substructure (MCS) for ligands in a LigandSet

        Returns:
            smartsString (str) : SMARTS string representing the MCS

        """

        from deeporigin.drug_discovery import align

        return align.mcs(self.to_rdkit_mols())

    def filter_top_poses(self, *, by_pose_score: bool = True) -> Self:
        """
        Filter ligands to keep only the best pose for each unique molecule.

        Groups ligands by SMILES string and retains only the one with:
        - Minimum binding energy (default), or
        - Maximum pose score (when by_pose_score=True)

        Args:
            by_pose_score (bool): If True, select by maximum pose score.
                                If False, select by minimum binding energy.

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
        props = ligand.properties
        if "POSE SCORE" in props:
            pose_score_str = props["POSE SCORE"]
        elif "pose_score" in props:
            pose_score_str = props["pose_score"]
        else:
            pose_score_str = None
        if pose_score_str is None:
            raise DeepOriginException(
                f"Ligand {ligand.name or 'unnamed'} missing 'POSE SCORE' or 'pose_score' property"
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
        x: str = "POSE SCORE",
        y: str = "Binding Energy",
        output_file: Optional[str] = None,
        y_lim_max: Optional[float] = 0,
        width: int = 800,
        height: int = 800,
    ):
        """Create a scatter plot of ligands using specified attributes for the axes.

        The plot displays molecule images on hover and can be displayed inline or saved to an HTML file.

        Args:
            x_label: Label for the x-axis. Defaults to "Pose Score".
            y_label: Label for the y-axis. Defaults to "Binding Energy (kcal/mol)".
            x: The name of the ligand property to use for the x-axis. Defaults to "POSE SCORE".
            y: The name of the ligand property to use for the y-axis. Defaults to "Binding Energy".
            output_file: Optional file path to save the HTML figure. If provided, the plot is saved to this file instead of being displayed. Defaults to None.

        Raises:
            ValueError: If the specified x or y properties are not found in the ligand data.
        """
        from deeporigin.plots import scatter

        df = self.to_dataframe()

        scatter(
            x=df[x],
            y=df[y],
            smiles_list=df["SMILES"],
            x_label=x_label,
            y_label=y_label,
            title="Binding Energy vs POSE SCORE",
            output_file=output_file,
            y_lim_max=y_lim_max,
            width=width,
            height=height,
        )
