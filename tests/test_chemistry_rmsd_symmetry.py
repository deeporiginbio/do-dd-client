"""Symmetry-aware pose RMSD regressions (DDOS-8260)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pytest
from rdkit import Chem
from rdkit.Chem import AllChem, rdFMCS

from deeporigin.drug_discovery import chemistry
from deeporigin.drug_discovery.structures.ligand import LigandSet

_FIXTURES = Path(__file__).resolve().parent / "fixtures"

_SYMMETRIC_LIGAND_SMILES = [
    ("benzoic_acid", "O=C(O)c1ccccc1"),
    ("ibuprofen", "CC(C)Cc1ccc(cc1)C(C)C(=O)O"),
    ("imatinib", "Cc1ccc(cc1Nc1nccc(n1)c2ccc3ccccc3n2)C(=O)Nc4ccc(cc4)N(C)C"),
    (
        "celecoxib",
        "Cc1ccc(cc1)-c1cc(nn1-c1ccc(cc1)S(N)(=O)=O)C(F)(F)F",
    ),
]


def _embed_heavy(smiles: str, seed: int = 7) -> Chem.Mol:
    mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
    assert mol is not None
    AllChem.EmbedMolecule(mol, randomSeed=seed)
    return Chem.RemoveHs(mol)


def _symmetry_relabeled_copy(mol: Chem.Mol) -> Chem.Mol:
    n = mol.GetNumAtoms()
    perm = next(
        p
        for p in mol.GetSubstructMatches(mol, uniquify=False)
        if list(p) != list(range(n))
    )
    copy = Chem.Mol(mol)
    conf = copy.GetConformer()
    ref = mol.GetConformer()
    for i in range(n):
        conf.SetAtomPosition(i, ref.GetAtomPosition(perm[i]))
    return copy


@pytest.mark.parametrize(("name", "smiles"), _SYMMETRIC_LIGAND_SMILES)
def test_pose_rmsd_zero_for_symmetric_relabel(name: str, smiles: str) -> None:
    """Relabeled symmetric copies compare to ~0 Å."""
    mol_a = _embed_heavy(smiles)
    mol_b = _symmetry_relabeled_copy(mol_a)
    rmsd = chemistry.pose_rmsd(mol_a, mol_b)
    assert rmsd is not None
    assert rmsd == pytest.approx(0.0, abs=1e-6)


def test_pose_rmsd_unchanged_for_asymmetric_molecules() -> None:
    """Caffeine vs nicotine: no symmetry to fix; value is stable and finite."""
    caffeine = _embed_heavy("CN1C=NC2=C1C(=O)N(C(=O)N2C)C", seed=3)
    nicotine = _embed_heavy("CN1CCC[C@H]1c2cccnc2", seed=5)
    rmsd = chemistry.pose_rmsd(caffeine, nicotine)
    assert rmsd is not None
    assert rmsd > 0.5


def test_pose_rmsd_toluene_on_ethylbenzene_mcs() -> None:
    """Common-substructure path: ring relabel on ethylbenzene gives 0 Å."""
    ethylbenzene = _embed_heavy("CCc1ccccc1", seed=11)
    toluene = _embed_heavy("Cc1ccccc1", seed=11)
    amap = chemistry.mcs_map(toluene, ethylbenzene)
    assert amap is not None
    t_conf = toluene.GetConformer()
    e_conf = ethylbenzene.GetConformer()
    for ti, ei in amap:
        t_conf.SetAtomPosition(ti, e_conf.GetAtomPosition(ei))
    ethyl_relabel = _symmetry_relabeled_copy(ethylbenzene)
    rmsd = chemistry.pose_rmsd(toluene, ethyl_relabel, use_mcs_if_needed=True)
    assert rmsd is not None
    assert rmsd == pytest.approx(0.0, abs=1e-6)


def test_mcs_map_order_independent_for_shared_sites() -> None:
    """MCS embeddings on both sides keep pose_rmsd(a,b) == pose_rmsd(b,a)."""
    a = _embed_heavy("CCc1ccccc1", seed=11)
    b = _embed_heavy("Cc1ccccc1", seed=13)
    forward = chemistry.pose_rmsd(a, b, use_mcs_if_needed=True)
    reverse = chemistry.pose_rmsd(b, a, use_mcs_if_needed=True)
    assert forward is not None and reverse is not None
    assert forward == pytest.approx(reverse, abs=1e-9)


def _legacy_mcs_map(
    mol_a: Chem.Mol,
    mol_b: Chem.Mol,
    *,
    ignore_hs: bool = True,
) -> Optional[list[tuple[int, int]]]:
    """Pre-DDOS-8260 MCS mapping (symmetric matches in B deduplicated)."""

    A = Chem.RemoveHs(mol_a) if ignore_hs else mol_a
    B = Chem.RemoveHs(mol_b) if ignore_hs else mol_b
    params = rdFMCS.MCSParameters()
    params.AtomCompare = rdFMCS.AtomCompare.CompareElements
    params.BondCompare = rdFMCS.BondCompare.CompareOrder
    params.RingMatchesRingOnly = True
    params.CompleteRingsOnly = True
    params.MatchValences = True
    params.MatchChiralTag = False
    params.Timeout = 10
    res = rdFMCS.FindMCS([A, B], params)
    if res.canceled or res.numAtoms == 0:
        return None
    q = Chem.MolFromSmarts(res.smartsString)
    if q is None:
        return None
    mA = A.GetSubstructMatches(q, uniquify=True, maxMatches=1024)
    mB = B.GetSubstructMatches(q, uniquify=True, maxMatches=4096)
    if not mA or not mB:
        return None
    ref = mA[0]
    best_map, best_rms = None, None
    for cand in mB:
        amap = list(zip(ref, cand, strict=False))
        rms = chemistry.raw_rmsd_from_map(A, B, amap)
        if best_rms is None or rms < best_rms:
            best_rms, best_map = rms, amap
    return best_map


def _legacy_pose_rmsd(
    mol_a: Chem.Mol,
    mol_b: Chem.Mol,
    *,
    conf_id_a: int = 0,
    conf_id_b: int = 0,
    ignore_hs: bool = True,
    use_mcs_if_needed: bool = True,
) -> Optional[float]:
    amap = chemistry.full_graph_map(mol_a, mol_b, ignore_hs=ignore_hs)
    if amap is None and use_mcs_if_needed:
        amap = _legacy_mcs_map(mol_a, mol_b, ignore_hs=ignore_hs)
    if amap is None:
        return None
    a_cmp = Chem.RemoveHs(mol_a) if ignore_hs else mol_a
    b_cmp = Chem.RemoveHs(mol_b) if ignore_hs else mol_b
    return chemistry.raw_rmsd_from_map(a_cmp, b_cmp, amap, conf_id_a, conf_id_b)


def _legacy_pairwise(mols: list[Chem.Mol]) -> np.ndarray:
    n = len(mols)
    m = np.zeros((n, n), float)
    for i in range(n):
        for j in range(i + 1, n):
            r = _legacy_pose_rmsd(mols[i], mols[j])
            val = r if r is not None else np.nan
            m[i, j] = m[j, i] = val
    return m


def _mols_from_sdf(path: Path, *, max_records: int | None = None) -> list[Chem.Mol]:
    ligands = LigandSet.from_sdf(str(path))
    mols = ligands.to_rdkit_mols()
    if max_records is not None:
        return mols[:max_records]
    return mols


@pytest.mark.slow
@pytest.mark.parametrize(
    ("fixture_name", "max_records"),
    [
        ("docked-poses.sdf", None),
        ("brd-all-poses.sdf", 60),
        ("42-ligands.sdf", None),
    ],
)
def test_pairwise_pose_rmsd_never_increases_vs_legacy(
    fixture_name: str,
    max_records: int | None,
) -> None:
    """New symmetry-aware RMSD is <= legacy first-match RMSD for every pair."""
    path = _FIXTURES / fixture_name
    mols = _mols_from_sdf(path, max_records=max_records)
    new_m = chemistry.pairwise_pose_rmsd(mols)
    old_m = _legacy_pairwise(mols)
    n = len(mols)
    for i in range(n):
        for j in range(i + 1, n):
            old_v = old_m[i, j]
            new_v = new_m[i, j]
            if np.isnan(old_v):
                # Legacy could not map; new may still succeed (NaN or finite).
                continue
            assert not np.isnan(new_v), (
                f"{fixture_name} pair ({i},{j}): new lost mapping "
                f"(NaN) while legacy={old_v}"
            )
            assert new_v <= old_v + 1e-9, (
                f"{fixture_name} pair ({i},{j}): new={new_v} > legacy={old_v}"
            )
