"""Unit tests for :class:`~deeporigin.drug_discovery.molprops.Molprops`."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from deeporigin.drug_discovery import Ligand, Molprops
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS


def test_molprops_run_syncs_status_from_execution_dto() -> None:
    """A normal ``run()`` applies ``update_from_dto`` so status is not left at ``Quoted``."""
    ligand = Ligand.from_smiles("CCO")
    client = MagicMock(spec=DeepOriginClient)
    job = Molprops(ligands=[ligand], props=["logp"], client=client)
    job.status = "Quoted"
    job._id = "prior-quote-id"
    job._estimate = 0.14

    mp_cfg = TOOL_KEYS_AND_VERSIONS["mol_props"]
    raw_dto: dict = {
        "executionId": "exec-run-1",
        "tool": {"key": mp_cfg["tool_key"], "version": mp_cfg["tool_version"]},
        "status": "Succeeded",
        "quotationResult": {"successfulQuotations": [{"priceTotal": 0.14}]},
        "jobOutputs": {"molprops": [{"ligand_id": "0", "logp": 1.2}]},
    }
    rows = [{"ligand_id": "0", "logp": 1.2}]

    with patch(
        "deeporigin.drug_discovery.molprops.run_molprops_combined",
        return_value=(rows, raw_dto),
    ):
        job.run()

    assert job.status == "Completed"
    assert job.id == "exec-run-1"
    assert job.cost == 0.14
