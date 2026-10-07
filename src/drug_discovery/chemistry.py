"""Contains functions for working with SDF files."""

from collections.abc import Sequence
from pathlib import Path
import re
from typing import Literal, Optional, Tuple

from beartype import beartype
import numpy as np
from rdkit import Chem, RDLogger
from rdkit.Chem import AllChem, SDWriter, rdFMCS, rdMolAlign

KeyType = Literal["smiles", "inchi"]


@beartype
def count_molecules_in_sdf_file(sdf_file: str | Path) -> int:
    """
    Count the number of valid (sanitizable) molecules in an SDF file using RDKit,
    while suppressing RDKit's error logging for sanitization issues.

    Args:
        sdf_file: Path to the SDF file.

    Returns:
        int: The number of molecules successfully read in the SDF file.
    """

    # Disable RDKit error logging to suppress messages about kekulization/sanitization.
    RDLogger.DisableLog("rdApp.error")

    # Use sanitize=False to defer sanitization until we can handle exceptions ourselves.
    supplier = Chem.SDMolSupplier(str(sdf_file), sanitize=False)
    valid_count = 0
    for mol in supplier:
        if mol is None:
            continue
        try:
            # Manually sanitize the molecule.
            Chem.SanitizeMol(mol)
            valid_count += 1
        except Exception:
            # If sanitization fails, skip this molecule.
            continue
    return valid_count


@beartype
def read_property_values(sdf_file: str | Path, key: str):
    """Given a SDF file with more than 1 molecule, return the values of the properties for each molecule

    Args:
        sdf_file: Path to the SDF file.
        key: The key of the property to read.


    """

    suppl = Chem.SDMolSupplier(
        str(sdf_file),
        removeHs=False,
        sanitize=False,
    )
    values = []
    for _, mol in enumerate(suppl, start=1):
        if mol is None:
            value = None
        else:
            if mol.HasProp(key):
                value = mol.GetProp(key).strip()
            else:
                value = None
        values.append(value)
    return values


@beartype
def split_sdf_file(
    *,
    input_sdf_path: str | Path,
    output_prefix: str = "ligand",
    output_dir: Optional[str | Path] = None,
    name_by_property: str = "_Name",
) -> list[Path]:
    """
    Splits a multi-ligand SDF file into individual SDF files, optionally placing
    the output in a user-specified directory. Each output SDF is named using
    the molecule's name (if present) or a fallback prefix.

    Args:
        input_sdf_path: Path to the input SDF file containing multiple ligands.
        output_prefix: Prefix for unnamed ligands. Defaults to "ligand".
        output_dir: Directory to write the output SDF files to. If None,
            output files are written to the same directory as input_sdf_path.

    Returns:
        list[Path]: A list of paths to the generated SDF files.
    """

    values = read_property_values(input_sdf_path, name_by_property)
    n_mols = count_molecules_in_sdf_file(input_sdf_path)

    if len(set(values)) != n_mols:
        raise ValueError(
            f"The number of molecules in the SDF file ({n_mols}) is not consistent with the number of values ({len(set(values))}) extracted from the property {name_by_property}. Use a different property to fix this."
        )

    if not isinstance(input_sdf_path, Path):
        input_sdf_path = Path(input_sdf_path)

    if output_dir is None:
        output_dir = input_sdf_path.parent
    else:
        if not isinstance(output_dir, Path):
            output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    suppl = Chem.SDMolSupplier(
        str(input_sdf_path),
        removeHs=False,
        sanitize=False,
    )

    generated_paths = []

    for i, mol in enumerate(suppl, start=1):
        if mol is None:
            continue

        if mol.HasProp(name_by_property):
            mol_name = mol.GetProp(name_by_property).strip()
        else:
            mol_name = f"{output_prefix}_{i}"

        # Replace unsafe filename characters
        safe_name = re.sub(r"[^a-zA-Z0-9_\-]+", "_", mol_name)

        output_file = output_dir / f"{safe_name}.sdf"

        writer = Chem.SDWriter(str(output_file))
        writer.write(mol)
        writer.close()

        generated_paths.append(output_file)

    return generated_paths


@beartype
def smiles_to_sdf(smiles: str, sdf_path: str) -> None:
    """convert a SMILES string to a SDF file

    Args:
        smiles (str): SMILES string
        sdf_path (str): Path to the SDF file

    """

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        print(f"Invalid SMILES: {smiles}")

    try:
        Chem.Kekulize(mol)
    except ValueError:
        print(f"Failed to kekulize: {smiles}")

    mol = Chem.AddHs(mol)

    AllChem.EmbedMolecule(mol, AllChem.ETKDG())
    AllChem.UFFOptimizeMolecule(mol)

    with SDWriter(sdf_path) as writer:
        writer.write(mol)


@beartype
def sdf_to_smiles(sdf_file: str | Path) -> list[str]:
    """
    Extracts the SMILES strings of all valid molecules from an SDF file using RDKit.

    Args:
        sdf_file (str | Path): Path to the SDF file.

    Returns:
        list[str]: A list of SMILES strings for all valid molecules in the file.
    """

    if isinstance(sdf_file, Path):
        sdf_file = str(sdf_file)

    suppl = Chem.SDMolSupplier(sdf_file, sanitize=False)
    if not suppl:
        return []

    smiles_list = []
    for mol in suppl:
        if mol is not None:
            smiles_list.append(Chem.MolToSmiles(mol, canonical=True))

    smiles_list = sorted(set(smiles_list))

    return smiles_list


@beartype
def canonicalize_smiles(smiles: str) -> str:
    """Canonicalize a SMILES string.

    Args:
        smiles (str): SMILES string.

    Returns:
        str: Canonicalized SMILES string.
    """

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles}")
    return Chem.MolToSmiles(mol, canonical=True)


def group_by_prop_smiles_to_multiconf(
    sdf_path: str,
    *,
    smiles_prop_name: str = "SMILES",
    keep_hs: bool = False,
    align_conformers: bool = True,
    skip_no_coords: bool = True,
) -> dict[str, Chem.Mol]:
    """
    Read an SDF that contains many poses (possibly for multiple ligands) and group them by
    an SDF property (default: <SMILES>). For each unique value, return one RDKit Mol
    holding all poses as conformers.

    Returns
    -------
    dict[str, Chem.Mol]: {prop_smiles_value -> Mol with N conformers}
    """

    suppl = Chem.SDMolSupplier(sdf_path, sanitize=True, removeHs=False)
    entries = [m for m in suppl if m is not None]
    if not entries:
        raise ValueError("No valid molecules found in SDF.")

    grouped = {}
    ref_graph_by_key: dict[str, Chem.Mol] = {}  # heavy-atom reference used for mapping

    for i, m in enumerate(entries):
        if not m.HasProp(smiles_prop_name):
            raise ValueError(
                f"SDF record {i} is missing <{smiles_prop_name}> property; "
                "set smiles_prop_name accordingly."
            )
        key = m.GetProp(smiles_prop_name).strip()

        # Ensure we have 3D coords
        if m.GetNumConformers() == 0 or not m.GetConformer().Is3D():
            if skip_no_coords:
                continue
            raise ValueError(f"SDF record {i} has no 3D coordinates.")

        # Normalize Hs for robust atom mapping
        m_proc = Chem.Mol(m)
        if not keep_hs:
            m_proc = Chem.RemoveHs(m_proc)

        if key not in grouped:
            # First pose for this ligand: establish container and reference atom order
            base = Chem.Mol(m_proc)
            base.RemoveAllConformers()

            # Copy coordinates as conformer 0
            conf_in = m_proc.GetConformer()
            conf_out = Chem.Conformer(base.GetNumAtoms())
            conf_out.Set3D(True)
            for aidx in range(base.GetNumAtoms()):
                conf_out.SetAtomPosition(aidx, conf_in.GetAtomPosition(aidx))
            base.AddConformer(conf_out, assignId=True)

            grouped[key] = base
            ref_graph_by_key[key] = Chem.Mol(base)  # heavy-atom reference
            continue

        # Subsequent pose: remap into the reference atom order
        ref = grouped[key]
        ref_nh = ref_graph_by_key[key]

        cur_nh = m_proc  # already heavy-atom if keep_hs=False
        if cur_nh.GetNumAtoms() != ref_nh.GetNumAtoms():
            # Different topology; skip this pose (or raise)
            continue

        # mapping[t] = index in cur_nh that corresponds to atom t in ref_nh
        mapping = ref_nh.GetSubstructMatch(cur_nh)
        if not mapping or len(mapping) != ref_nh.GetNumAtoms():
            # Could not find a full-graph mapping; skip (or raise)
            continue

        conf_in = cur_nh.GetConformer()
        conf_out = Chem.Conformer(ref.GetNumAtoms())
        conf_out.Set3D(True)
        for t in range(ref_nh.GetNumAtoms()):
            src = mapping[t]
            conf_out.SetAtomPosition(t, conf_in.GetAtomPosition(src))

        # Optionally carry per-record fields onto the conformer
        # (SDF props -> conformer string props)
        for k in m.GetPropNames():
            try:
                conf_out.SetProp(k, m.GetProp(k))
            except Exception:
                pass

        ref.AddConformer(conf_out, assignId=True)

    # Optional alignment within each ligand
    if align_conformers:
        for mol in grouped.values():
            if mol.GetNumConformers() > 1:
                rdMolAlign.AlignMolConformers(mol)

    # return heavy-atom graphs; caller can AddHs(mol, addCoords=True) if needed
    return grouped


def raw_rmsd_from_map(
    mol_a: Chem.Mol,
    mol_b: Chem.Mol,
    atom_map: list[Tuple[int, int]],
    conf_id_a: int = 0,
    conf_id_b: int = 0,
) -> float:
    """Compute RMSD directly from coordinates on a given atom mapping. NO alignment, NO centering."""
    cA, cB = mol_a.GetConformer(conf_id_a), mol_b.GetConformer(conf_id_b)
    diffsq = 0.0
    for ia, ib in atom_map:
        pa, pb = cA.GetAtomPosition(ia), cB.GetAtomPosition(ib)
        dx, dy, dz = (pa.x - pb.x), (pa.y - pb.y), (pa.z - pb.z)
        diffsq += dx * dx + dy * dy + dz * dz
    return np.sqrt(diffsq / len(atom_map))


def _full_graph_symmetry_min_rmsd(
    mol_a: Chem.Mol,
    mol_b: Chem.Mol,
    *,
    conf_id_a: int = 0,
    conf_id_b: int = 0,
    ignore_hs: bool = True,
) -> Optional[float]:
    """Lowest no-alignment RMSD over graph isomorphisms and CalcRMS terminal symmetry."""

    a_cmp = Chem.RemoveHs(mol_a) if ignore_hs else mol_a
    b_cmp = Chem.RemoveHs(mol_b) if ignore_hs else mol_b
    if a_cmp.GetNumAtoms() != b_cmp.GetNumAtoms():
        return None
    matches = b_cmp.GetSubstructMatches(a_cmp, uniquify=False, maxMatches=4096)
    if not matches or len(matches[0]) != a_cmp.GetNumAtoms():
        return None

    candidates: list[float] = []
    try:
        candidates.append(
            float(
                rdMolAlign.CalcRMS(
                    mol_b,
                    mol_a,
                    prbId=conf_id_b,
                    refId=conf_id_a,
                )
            )
        )
    except RuntimeError:
        pass
    for match in matches:
        amap = [(i, match[i]) for i in range(a_cmp.GetNumAtoms())]
        candidates.append(raw_rmsd_from_map(a_cmp, b_cmp, amap, conf_id_a, conf_id_b))
    return min(candidates) if candidates else None


def full_graph_map(
    mol_a: Chem.Mol,
    mol_b: Chem.Mol,
    ignore_hs: bool = True,
) -> Optional[list[Tuple[int, int]]]:
    """Return atom map for identical graphs (isomorphic)."""

    A = Chem.RemoveHs(mol_a) if ignore_hs else mol_a
    B = Chem.RemoveHs(mol_b) if ignore_hs else mol_b
    if A.GetNumAtoms() != B.GetNumAtoms():
        return None
    match = B.GetSubstructMatch(A)
    if not match or len(match) != A.GetNumAtoms():
        return None
    # Map indices in A -> B; if we removed Hs, indices still correspond to those versions we’ll compare
    return [(i, match[i]) for i in range(A.GetNumAtoms())]


def mcs_map(
    mol_a: Chem.Mol,
    mol_b: Chem.Mol,
    ignore_hs: bool = True,
    ring_matches_ring_only: bool = True,
    complete_rings_only: bool = True,
    match_valences: bool = True,
    match_chiral_tag: bool = False,
    timeout: int = 10,
) -> Optional[list[Tuple[int, int]]]:
    """Return an atom map for the maximum common substructure (subset comparison)."""

    A = Chem.RemoveHs(mol_a) if ignore_hs else mol_a
    B = Chem.RemoveHs(mol_b) if ignore_hs else mol_b
    params = rdFMCS.MCSParameters()
    params.AtomCompare = rdFMCS.AtomCompare.CompareElements
    params.BondCompare = rdFMCS.BondCompare.CompareOrder
    params.RingMatchesRingOnly = ring_matches_ring_only
    params.CompleteRingsOnly = complete_rings_only
    params.MatchValences = match_valences
    params.MatchChiralTag = match_chiral_tag
    params.Timeout = timeout
    res = rdFMCS.FindMCS([A, B], params)
    if res.canceled or res.numAtoms == 0:
        return None
    q = Chem.MolFromSmarts(res.smartsString)
    if q is None:
        return None
    mA = A.GetSubstructMatches(q, uniquify=True, maxMatches=1024)
    mB = B.GetSubstructMatches(q, uniquify=False, maxMatches=4096)
    if not mA or not mB:
        return None
    # Fix atom order using first match in A, then choose B’s match minimizing RAW (unaligned) RMSD
    ref = mA[0]
    best_map, best_rms = None, None
    for cand in mB:
        amap = list(zip(ref, cand, strict=False))
        rms = raw_rmsd_from_map(A, B, amap)  # still NO alignment
        if best_rms is None or rms < best_rms:
            best_rms, best_map = rms, amap
    return best_map


def pose_rmsd(
    mol_a: Chem.Mol,
    mol_b: Chem.Mol,
    *,
    conf_id_a: int = 0,
    conf_id_b: int = 0,
    ignore_hs: bool = True,
    use_mcs_if_needed: bool = True,
) -> Optional[float]:
    """
    Pose-sensitive RMSD: NO alignment, NO centering. High if the same structure is translated/rotated.
    Tries full-graph mapping; if that fails and use_mcs_if_needed=True, uses MCS subset mapping.
    Returns None if no mapping found.
    """

    # Sanity: need 3D confs
    if (
        mol_a.GetNumConformers() <= conf_id_a
        or not mol_a.GetConformer(conf_id_a).Is3D()
    ):
        raise ValueError("mol_a lacks a 3D conformer at conf_id_a")
    if (
        mol_b.GetNumConformers() <= conf_id_b
        or not mol_b.GetConformer(conf_id_b).Is3D()
    ):
        raise ValueError("mol_b lacks a 3D conformer at conf_id_b")

    full_rmsd = _full_graph_symmetry_min_rmsd(
        mol_a,
        mol_b,
        conf_id_a=conf_id_a,
        conf_id_b=conf_id_b,
        ignore_hs=ignore_hs,
    )
    if full_rmsd is not None:
        return full_rmsd

    if not use_mcs_if_needed:
        return None
    amap = mcs_map(mol_a, mol_b, ignore_hs=ignore_hs)
    if amap is None:
        return None
    a_cmp = Chem.RemoveHs(mol_a) if ignore_hs else mol_a
    b_cmp = Chem.RemoveHs(mol_b) if ignore_hs else mol_b
    return raw_rmsd_from_map(a_cmp, b_cmp, amap, conf_id_a, conf_id_b)


@beartype
def pairwise_pose_rmsd(
    mols: Sequence[Chem.Mol],
    *,
    conf_id: int = 0,
    ignore_hs: bool = True,
    use_mcs_if_needed: bool = True,
    fill_value_for_unmapped: float = np.nan,
):
    """
    NxN matrix of pose-sensitive RMSDs (no alignment).
    If two mols can’t be mapped, entry is fill_value_for_unmapped (default NaN).
    """
    n = len(mols)
    M = np.zeros((n, n), float)
    for i in range(n):
        for j in range(i + 1, n):
            r = pose_rmsd(
                mols[i],
                mols[j],
                conf_id_a=conf_id,
                conf_id_b=conf_id,
                ignore_hs=ignore_hs,
                use_mcs_if_needed=use_mcs_if_needed,
            )
            M[i, j] = M[j, i] = r if r is not None else fill_value_for_unmapped
    return M
