"""Unit tests for ligand create/update field filtering."""

from deeporigin.platform.entities import _writable_ligand_set_fields


def test_writable_ligand_set_fields_strips_molprops_columns() -> None:
    """Molprops-computed ligand columns must not be sent on create/update."""
    payload = {
        "smiles": "CCO",
        "name": "ethanol",
        "formal_charge": 0,
        "molecular_weight": 46.0,
        "hbond_donor_count": 1,
        "hbond_acceptor_count": 1,
        "rotatable_bond_count": 0,
        "tpsa": 20.2,
    }

    filtered = _writable_ligand_set_fields(payload)

    assert filtered == {
        "smiles": "CCO",
        "name": "ethanol",
        "formal_charge": 0,
    }
