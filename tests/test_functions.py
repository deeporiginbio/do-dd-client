"""This module contains tests for functions.

These are meant to be run against a live instance.
"""

import pytest

from conftest import check_function_exists
from deeporigin.drug_discovery import (
    Docking,
    Ligand,
    LigandSet,
    Molprops,
    Pocket,
    PocketFinder,
    Protein,
)
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.drug_discovery.sync_function_responses import SyncFunctionResponses
from deeporigin.drug_discovery.system_prep import SystemPrep, for_abfe
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import MOLPROPS_PROPERTY_KEYS


def test_functions_list_lv1(client: DeepOriginClient) -> None:
    """``Functions.list()`` returns definitions and caches the list on the client."""
    first = client.functions.list()
    assert isinstance(first, list), "Expected a list"
    assert len(first) > 0, "Expected at least one function definition"

    fn = first[0]
    for key in [
        "version",
        "enabled",
        "manifestBody",
        "billingCode",
        "resourceId",
    ]:
        assert key in fn, f"Expected function definition to have key {key}"

    second = client.functions.list()
    assert second is first, "Expected repeated list() to return the cached list"


def test_molprops_lv1(client: DeepOriginClient):
    mp = TOOL_KEYS_AND_VERSIONS["mol_props"]
    missing_molprops = [
        f"{mp['function_key_prefix']}-{p}"
        for p in sorted(MOLPROPS_PROPERTY_KEYS)
        if not check_function_exists(client, f"{mp['function_key_prefix']}-{p}")
    ]
    assert not missing_molprops, (
        f"Mol props functions not registered on platform: {missing_molprops}"
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


def test_pocket_finder_quote_lv1(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """PocketFinder.quote() returns an estimate without running the tool."""
    assert check_function_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["pocket_finder"]["function_key"],
        TOOL_KEYS_AND_VERSIONS["pocket_finder"]["function_version"],
    ), "Pocket finder function not registered on platform (expected key/version)."

    pf = PocketFinder(protein=registered_protein, client=client)
    pf.quote()
    assert pf.estimate is not None, "Estimate should be set"
    assert pf.cost is None, (
        "Cost should be None because the pocket finder is not run yet"
    )


@pytest.mark.parametrize(
    "protein_fixture",
    [
        pytest.param("brd_protein", id="backend_only"),
        pytest.param("registered_protein", id="data_platform"),
    ],
)
def test_pocket_finder_lv2(
    client: DeepOriginClient,
    protein_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    """Exercise pocket finder with upload-only vs data-platform–registered protein.

    ``brd_protein`` checks the tool end-to-end using file path only (no platform
    entity in the fixture). ``registered_protein`` additionally asserts
    platform-linked IDs and ``Pocket.from_result`` hydration.
    """
    assert check_function_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["pocket_finder"]["function_key"],
        TOOL_KEYS_AND_VERSIONS["pocket_finder"]["function_version"],
    ), "Pocket finder function not registered on platform (expected key/version)."

    protein: Protein = request.getfixturevalue(protein_fixture)
    num_pockets = 1

    pf = PocketFinder(
        protein,
        pocket_count=num_pockets,
        client=client,
    )
    pockets = pf.run()

    assert len(pockets) == num_pockets, f"Expected {num_pockets} pockets"
    pocket = pockets[0]
    assert isinstance(pocket, Pocket), "Expected Pocket object"

    if protein_fixture == "registered_protein":
        assert pocket.protein_id == protein.id, (
            "Pocket protein_id should match protein.id"
        )
        pockets_from_result = Pocket.from_result(
            execution_id=pf.id,
            client=client,
        )
        assert len(pockets_from_result) == num_pockets, (
            f"Expected {num_pockets} pockets from result"
        )
        pocket_from_result = pockets_from_result[0]
        assert isinstance(pocket_from_result, Pocket), "Expected Pocket object"
        assert pocket_from_result.protein_id == protein.id, (
            "Pocket protein_id should match protein.id"
        )


def test_docking_run_rejects_effort_out_of_range(
    client: DeepOriginClient,
    registered_protein: Protein,
    registered_ligand: Ligand,
    registered_pocket: Pocket,
) -> None:
    """:meth:`Docking.run` raises when ``effort`` is outside 1–5."""
    with pytest.raises(DeepOriginException):
        Docking(
            protein=registered_protein,
            pocket=registered_pocket,
            ligand=registered_ligand,
            client=client,
            effort=0,
        ).run()


def test_docking_lv2(
    client: DeepOriginClient,
    registered_protein: Protein,
    registered_ligand: Ligand,
    registered_pocket: Pocket,
):
    """Exercise synchronous docking via :class:`Docking`."""
    assert check_function_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["docking"]["function_key"],
        TOOL_KEYS_AND_VERSIONS["docking"]["function_version"],
    ), "Docking function not registered on platform (expected key/version)."

    poses = Docking(
        protein=registered_protein,
        pocket=registered_pocket,
        ligand=registered_ligand,
        client=client,
    ).run()

    assert poses is not None
    assert len(poses) >= 1


@pytest.mark.parametrize(
    ("protein_fixture", "ligand_fixture"),
    [
        pytest.param("brd_protein", "brd_ligand", id="backend_only"),
        pytest.param("registered_protein", "registered_ligand", id="data_platform"),
    ],
)
def test_sysprep_lv2(
    client: DeepOriginClient,
    protein_fixture: str,
    ligand_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    """Exercise ABFE system prep with upload-only vs data-platform entities.

    ``brd_*`` checks the tool end-to-end with file paths only. ``registered_*``
    additionally checks the result-explorer row for this job (tool key, protein
    id, stored ``data`` payload).
    """
    assert check_function_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["sysprep"]["function_key"],
        TOOL_KEYS_AND_VERSIONS["sysprep"]["function_version"],
    ), "System prep function not registered on platform (expected key/version)."

    protein: Protein = request.getfixturevalue(protein_fixture)
    ligand: Ligand = request.getfixturevalue(ligand_fixture)

    if protein_fixture == "brd_protein":
        result = for_abfe(
            protein=protein,
            ligand=ligand,
            client=client,
            add_H_atoms=True,
            protonate_protein=True,
        )
        assert isinstance(result, SyncFunctionResponses)
        assert result.response.get("status") == "Completed"
        return

    sysprep = SystemPrep(
        protein=protein,
        ligand=ligand,
        client=client,
        add_H_atoms=True,
        protonate_protein=True,
    )
    prepared = sysprep.run()

    assert isinstance(prepared, PreparedSystem), (
        "Expected SystemPrep.run() to return PreparedSystem"
    )

    execution_id = sysprep.id
    assert execution_id is not None
    assert prepared.binding_xml_path
    assert prepared.solvation_xml_path
    assert prepared.system_pdb_path

    response = client.results.get_prepared_systems(
        compute_job_id=execution_id,
        protein_id=protein.id,
    )
    records = response["data"]
    assert len(records) >= 1, "Expected a prepared-system row for this compute job"
    record = records[0]
    assert record.get("compute_job_id") == execution_id
    assert record.get("tool_key") == TOOL_KEYS_AND_VERSIONS["sysprep"]["function_key"]
    data = record["data"]
    assert isinstance(data, dict) and len(data) > 0
    assert data.get("protein_id") == protein.id


@pytest.mark.skip(reason="TODO: fix protonation test later")
def test_protonation_lv2(client: DeepOriginClient):
    """Test protonation returns Protonation with ligands populated after run."""
    from deeporigin.drug_discovery.protonation import Protonation

    assert check_function_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["mol_props"]["protonation_function_key"],
        TOOL_KEYS_AND_VERSIONS["mol_props"]["function_version"],
    ), "Protonation function not registered on platform (expected key/version)."

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
