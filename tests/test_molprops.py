"""End-to-end tests for molecular property tools (mol_props) via ``client.executions.create``.

These are meant to be run against a live instance.
"""

import pytest

from deeporigin.drug_discovery import Ligand, LigandSet, Molprops
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import MOLPROPS_PROPERTY_KEYS
from tests.conftest import check_tool_exists


def test_molprops_lv1(client: DeepOriginClient) -> None:
    mp = TOOL_KEYS_AND_VERSIONS["mol_props"]
    missing_molprops = [
        f"{mp['tool_key_prefix']}-{p}"
        for p in sorted(MOLPROPS_PROPERTY_KEYS)
        if not check_tool_exists(client, f"{mp['tool_key_prefix']}-{p}")
    ]
    assert not missing_molprops, (
        f"Mol props tools not registered on platform: {missing_molprops}"
    )

    ligand = Ligand.from_smiles(
        "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12"
    )

    mp = Molprops(
        ligands=[ligand],
        client=client,
        properties={"logs", "logd", "logp", "herg"},
    )
    mp.run()

    assert ligand.get_property("logP") is not None or ligand.log_p is not None
    assert ligand.get_property("logD") is not None or ligand.log_d is not None
    assert ligand.get_property("logS") is not None or ligand.log_s is not None


@pytest.mark.skip(reason="TODO: fix protonation test later")
def test_protonation_lv2(client: DeepOriginClient) -> None:
    """Test protonation returns Protonation with ligands populated after run."""
    from deeporigin.drug_discovery.protonation import Protonation

    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["mol_props"]["protonation_tool_key"],
        TOOL_KEYS_AND_VERSIONS["mol_props"]["tool_version"],
    ), "Protonation tool not registered on platform (expected key/version)."

    ligand = Ligand.from_smiles("C=CCCn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O")

    original_smiles = ligand.smiles
    job = Protonation(ligand=ligand, ph=7.4, client=client)
    job.run()

    assert isinstance(job, Protonation), (
        "Expected Protonation instance after constructing with ligand="
    )
    assert isinstance(job.ligands, LigandSet), "Expected job.ligands to be a LigandSet"
    assert len(job.ligands) == 1, "Expected job.ligands to contain one ligand"
    assert job.ligands.ligands[0] is ligand, (
        "Expected primary output ligand to be the same instance as the input ligand"
    )
    assert ligand.smiles == original_smiles, "Expected SMILES to be the same at pH 7.4"

    job_high_ph = Protonation(ligand=ligand, ph=11.4, client=client)
    job_high_ph.run()

    assert isinstance(job_high_ph, Protonation)
    assert len(job_high_ph.ligands.ligands) == 2
    assert ligand.smiles != original_smiles, (
        "Expected SMILES to be different at pH 11.4"
    )
