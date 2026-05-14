"""End-to-end tests for molecular property tools (mol_props) via ``client.executions.create``.

These are meant to be run against a live instance.
"""

import pytest

from deeporigin.drug_discovery import Ligand, LigandSet, Molprops
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from tests.conftest import check_tool_exists


def test_molprops_lv1(client: DeepOriginClient) -> None:
    mp = TOOL_KEYS_AND_VERSIONS["mol_props"]
    assert check_tool_exists(client, mp["tool_key"], mp["tool_version"]), (
        f"Combined molprops tool {mp['tool_key']} (version {mp['tool_version']}) "
        "is not registered on the platform."
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


def test_molprops_run_quote_true_full_payload(
    client: DeepOriginClient,
) -> None:
    """``run(quote=True)`` uses one request for all ligands; ``batch_size`` is ignored."""
    mp_cfg = TOOL_KEYS_AND_VERSIONS["mol_props"]
    assert check_tool_exists(
        client,
        mp_cfg["tool_key"],
        mp_cfg["tool_version"],
    ), (
        f"Combined molprops tool {mp_cfg['tool_key']} "
        f"(version {mp_cfg['tool_version']}) is not registered on the platform."
    )

    lig1 = Ligand.from_smiles("CCO")
    lig2 = Ligand.from_smiles("CCN")
    job = Molprops(
        ligands=[lig1, lig2],
        props=["logp"],
        batch_size=1,
        client=client,
    )
    assert job.run(quote=True) is job
    assert job.estimate is not None
    assert getattr(job, "status", None) == "Quoted"
    assert job.cost is None
    assert lig1.log_p is None and lig2.log_p is None


@pytest.mark.skip(reason="TODO: fix protonation test later")
def test_protonation_lv2(client: DeepOriginClient) -> None:
    """Test protonation returns Protonation with ligands populated after run."""
    from deeporigin.drug_discovery.protonation import Protonation

    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["protonation"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["protonation"]["tool_version"],
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
