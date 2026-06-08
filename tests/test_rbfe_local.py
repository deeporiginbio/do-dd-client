"""Integration tests for RBFE against the local mock server (--env local)."""

from __future__ import annotations

from datetime import datetime, timezone

from deeporigin.drug_discovery import (
    BRD_DATA_DIR,
    RBFE,
    Ligand,
    Protein,
    RBFEParams,
    SystemPrep,
)
from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.progress_tree_display import is_v2_progress_tree
from tests.mock_server.routers.tools import (
    _find_progress_nodes,
    build_rbfe_progress_tree,
)

MOCK_RBFE_EXECUTION_ID = "a5484958-059f-4b1b-ba2c-664adf23e8e8"

_SAMPLE_RBFE_INPUTS = {
    "steps": ["rbfe"],
    "prepared_systems": [
        {
            "ligand1_id": "08DK80B7DYTXH",
            "ligand2_id": "08DKACBCXYTXX",
            "protein_id": "08BSPN9SNYVEA",
            "binding_xml_file_path": (
                "tool-runs/d037ce61-c52e-49bc-9507-1f300993d9fe/bsm_system.xml"
            ),
            "solvation_xml_ligand_file_path": (
                "tool-runs/d037ce61-c52e-49bc-9507-1f300993d9fe/solvation_ligand.xml"
            ),
        }
    ],
}


def _tree_at(fraction: float) -> dict:
    """Build a sample RBFE progress tree at *fraction* for unit tests."""
    return build_rbfe_progress_tree(
        execution_id="test-exec-id",
        user_inputs=_SAMPLE_RBFE_INPUTS,
        start_dt=datetime(2026, 6, 8, 17, 40, 40, tzinfo=timezone.utc),
        duration_s=100.0,
        fraction=fraction,
    )


def test_build_rbfe_progress_tree_early_stages() -> None:
    """Only prepare-inputs is visible early in the mock run."""
    tree = _tree_at(0.05)
    assert is_v2_progress_tree(tree)
    top = [c.get("displayName") for c in tree.get("children") or []]
    assert top == ["prepare-inputs"]
    assert tree["children"][0]["status"] == "Running"


def test_build_rbfe_progress_tree_mid_pipeline() -> None:
    """Skipped konnektor/system-prep; resolve running before rbfe-e2e appears."""
    tree = _tree_at(0.30)
    assert is_v2_progress_tree(tree)
    top_names = [c.get("displayName") for c in tree.get("children") or []]
    assert top_names[:3] == ["prepare-inputs", "run-konnektor", "build-pair-list"]
    assert tree["children"][1]["status"] == "Skipped"
    pair_nodes = _find_progress_nodes(tree, display_prefix="pair-pipeline")
    assert len(pair_nodes) == 1
    inner = [c.get("displayName") for c in pair_nodes[0].get("children") or []]
    assert inner == ["system-prep-task", "resolve-prepared-system"]
    assert _find_progress_nodes(tree, display_prefix="rbfe-e2e-task") == []
    resolve = _find_progress_nodes(tree, display_prefix="resolve-prepared-system")[0]
    assert resolve["status"] == "Running"


def test_build_rbfe_progress_tree_rbfe_ramp() -> None:
    """rbfe-e2e-task exposes ramping toolProgress.complete while Running."""
    tree = _tree_at(0.70)
    rbfe_nodes = _find_progress_nodes(tree, display_prefix="rbfe-e2e-task")
    assert len(rbfe_nodes) == 1
    node = rbfe_nodes[0]
    assert node["status"] == "Running"
    complete = node.get("toolProgress", {}).get("complete")
    assert isinstance(complete, int)
    assert 0 < complete < 100


def test_build_rbfe_progress_tree_complete() -> None:
    """Final tree marks every stage Succeeded with complete=100 on rbfe-e2e."""
    tree = _tree_at(1.0)
    assert tree["status"] == "Succeeded"
    rbfe_nodes = _find_progress_nodes(tree, display_prefix="rbfe-e2e-task")
    assert rbfe_nodes[0]["status"] == "Succeeded"
    assert rbfe_nodes[0]["toolProgress"]["complete"] == 100


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
    dto = client.executions.get(rbfe.id)  # ty:ignore[unresolved-attribute]
    if dto.get("status") == "Running":
        report = dto.get("progressReport")
        assert is_v2_progress_tree(report)

    rbfe.wait(timeout=30.0, poll_interval=0.5)
    assert rbfe.status == "Succeeded"

    df = rbfe.get_results()
    assert df is not None
    assert len(df) >= 1
    assert df.iloc[0]["ligand1_id"] == ligand1.id
    assert df.iloc[0]["ligand2_id"] == ligand2.id
    assert "kcal/mol" in str(df.iloc[0]["ddG"])

    logs = rbfe.get_user_logs()
    assert logs is not None
    assert not logs.empty
    assert list(logs.columns) == Execution.USER_LOG_COLUMNS
    assert logs.iloc[0]["tool_key"] == "rbfe"

    nohup_path = f"tool-runs/{rbfe.id}/workflow-mock/binding_nohup.out"
    nohup = client.files.download(remote_path=nohup_path, lazy=False)
    assert nohup is not None


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
