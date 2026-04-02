"""Constructor and validation tests for :class:`~deeporigin.drug_discovery.molprops.Molprops`."""

import pytest

from deeporigin.drug_discovery import Ligand, Molprops
from deeporigin.functions.molprops import molprops_ligands_payload


def test_molprops_accepts_props_list() -> None:
    lig = Ligand.from_smiles("CCO")
    mp = Molprops(ligands=[lig], props=["ames", "logp"])
    assert mp.props == ("ames", "logp")
    assert mp.properties == frozenset({"ames", "logp"})


def test_molprops_props_and_properties_exclusive() -> None:
    lig = Ligand.from_smiles("CCO")
    with pytest.raises(ValueError, match="only one of props or properties"):
        Molprops(ligands=[lig], props=["logp"], properties={"logp"})


def test_molprops_empty_props_raises() -> None:
    lig = Ligand.from_smiles("CCO")
    with pytest.raises(ValueError, match="non-empty"):
        Molprops(ligands=[lig], props=[])


def test_molprops_ligands_payload_default_ids() -> None:
    """Positional default ``id`` values match the merge key used in API responses."""
    assert molprops_ligands_payload([{"smiles": "C"}, {"smiles": "CC"}]) == [
        {"id": "0", "smiles": "C"},
        {"id": "1", "smiles": "CC"},
    ]


def test_molprops_ligands_payload_explicit_id() -> None:
    assert molprops_ligands_payload([{"id": "lig-a", "smiles": "C"}]) == [
        {"id": "lig-a", "smiles": "C"},
    ]


def test_molprops_ligands_payload_missing_smiles_raises() -> None:
    with pytest.raises(ValueError, match="smiles"):
        molprops_ligands_payload([{}])
