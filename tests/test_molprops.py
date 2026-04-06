"""Constructor and validation tests for :class:`~deeporigin.drug_discovery.molprops.Molprops`."""

import pytest

from deeporigin.drug_discovery import Ligand, LigandSet, Molprops


def test_molprops_accepts_props_list() -> None:
    lig = Ligand.from_smiles("CCO")
    mp = Molprops(ligands=[lig], props=["ames", "logp"])
    assert mp.props == ("ames", "logp")
    assert mp.properties == frozenset({"ames", "logp"})


def test_molprops_batch_size_property() -> None:
    lig = Ligand.from_smiles("C")
    mp = Molprops(ligands=[lig], props=["logp"], batch_size=5)
    assert mp.batch_size == 5
    mp_default = Molprops(ligands=[lig], props=["logp"])
    assert mp_default.batch_size is None


def test_molprops_props_and_properties_exclusive() -> None:
    lig = Ligand.from_smiles("CCO")
    with pytest.raises(ValueError, match="only one of props or properties"):
        Molprops(ligands=[lig], props=["logp"], properties={"logp"})


def test_molprops_empty_props_raises() -> None:
    lig = Ligand.from_smiles("CCO")
    with pytest.raises(ValueError, match="non-empty"):
        Molprops(ligands=[lig], props=[])


def test_ligand_set_to_dict_default_ids() -> None:
    """Positional default ``id`` values match the merge key used in API responses."""
    ls = LigandSet(
        ligands=[Ligand.from_smiles("C"), Ligand.from_smiles("CC")],
    )
    assert ls.to_dict() == [
        {"id": "0", "smiles": "C"},
        {"id": "1", "smiles": "CC"},
    ]


def test_ligand_set_to_dict_explicit_id() -> None:
    ls = LigandSet(ligands=[Ligand.from_smiles("C", id="lig-a")])
    assert ls.to_dict() == [{"id": "lig-a", "smiles": "C"}]


def test_ligand_set_to_dict_missing_smiles_raises() -> None:
    lig = Ligand.from_smiles("C")
    lig.smiles = ""
    with pytest.raises(ValueError, match="smiles"):
        LigandSet(ligands=[lig]).to_dict()
