"""Integration tests for RBFE against the local mock server (--env local)."""

from __future__ import annotations

from deeporigin.drug_discovery import (
    BRD_DATA_DIR,
    RBFE,
    Ligand,
    Protein,
    RBFEParams,
    SystemPrep,
)
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.platform.client import DeepOriginClient

MOCK_RBFE_EXECUTION_ID = "a5484958-059f-4b1b-ba2c-664adf23e8e8"


def test_rbfe_from_id_get_results_local(client: DeepOriginClient) -> None:
    """Preloaded execution fixture returns the captured ΔΔG summary."""
    rbfe = RBFE.from_id(MOCK_RBFE_EXECUTION_ID, client=client)
    df = rbfe.get_results()
    assert df is not None
    assert len(df) == 1
    assert df.iloc[0]["protein_id"] == "08BSPN9SNYVEA"
    assert df.iloc[0]["ddG"] == "-3875.483 kcal/mol"


def test_rbfe_sysprep_and_fep_local(client: DeepOriginClient) -> None:
    """BRD pair: system-prep (RBFE mode) then quote → confirm → wait → results."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.sync(client=client)
    ligand1 = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")
    ligand2 = Ligand.from_sdf(BRD_DATA_DIR / "brd-3.sdf")
    ligand1.sync(client=client)
    ligand2.sync(client=client)

    sysprep = SystemPrep(
        protein=protein,
        ligand1=ligand1,
        ligand2=ligand2,
        client=client,
    )
    system = sysprep.run()
    assert system is not None
    assert system.ligand2_id is not None
    assert system.system_pdb_path

    rbfe = RBFE(
        prepared_systems=[system],
        params=RBFEParams(test_run=1),
        client=client,
    )
    rbfe.start(quote=True)
    assert rbfe.status == "Quoted"
    assert rbfe.estimate is not None

    rbfe.confirm()
    rbfe.wait(timeout=30.0, poll_interval=0.5)
    assert rbfe.status == "Succeeded"

    df = rbfe.get_results()
    assert df is not None
    assert len(df) >= 1
    assert df.iloc[0]["ligand1_id"] == ligand1.id
    assert df.iloc[0]["ligand2_id"] == ligand2.id
    assert "kcal/mol" in str(df.iloc[0]["ddG"])


def test_prepared_system_from_result_after_sysprep_local(
    client: DeepOriginClient,
) -> None:
    """PreparedSystem.from_result finds RBFE sysprep rows by ligand ids."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.sync(client=client)
    ligand1 = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")
    ligand2 = Ligand.from_sdf(BRD_DATA_DIR / "brd-3.sdf")
    ligand1.sync(client=client)
    ligand2.sync(client=client)

    system = SystemPrep(
        protein=protein,
        ligand1=ligand1,
        ligand2=ligand2,
        client=client,
    ).run()
    assert system is not None

    found = PreparedSystem.from_result(
        protein_id=protein.id,
        ligand1_id=ligand1.id,
        ligand2_id=ligand2.id,
        client=client,
    )
    assert len(found) >= 1
    assert found[0].system_pdb_path
