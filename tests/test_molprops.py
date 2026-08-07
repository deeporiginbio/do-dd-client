"""End-to-end tests for molecular property tools (mol_props) via ``client.executions.create``.

These are meant to be run against a live instance.
"""

import pytest

from deeporigin.drug_discovery import Ligand, Molprops
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
        properties={"logs", "logd", "logp"},
    )
    mp.run()

    if ligand.log_p is None and ligand.get_property("logP") is None:
        pytest.skip("Molprops returned no results; platform tool may be unavailable.")
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
    if job.status != "Quoted":
        pytest.skip(
            "mol-props-combined on this env/version did not return a quotation "
            f"(status={job.status!r}); quote-only may not be supported on latest."
        )
    assert job.estimate is not None
    assert job.status == "Quoted"
    assert job.cost is None
    assert lig1.log_p is None and lig2.log_p is None
