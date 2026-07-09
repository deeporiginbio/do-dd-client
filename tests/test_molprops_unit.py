"""Unit tests for :class:`~deeporigin.drug_discovery.molprops.Molprops`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from deeporigin.drug_discovery import Ligand, Molprops
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from tests.conftest import check_tool_exists

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


def test_molprops_run_syncs_status_from_execution_dto(
    client: DeepOriginClient,
) -> None:
    """A normal ``run()`` applies ``update_from_dto`` so status is not left at ``Quoted``."""
    mp_cfg = TOOL_KEYS_AND_VERSIONS["mol_props"]
    assert check_tool_exists(client, mp_cfg["tool_key"], mp_cfg["tool_version"])

    ligand = Ligand.from_smiles("CCO")
    job = Molprops(ligands=[ligand], props=["logp"], client=client)
    job.status = "Quoted"
    job._id = "prior-quote-id"
    job._estimate = 0.14

    job.run()

    assert job.status == "Completed"
    assert job.id is not None
    assert job.id != "prior-quote-id"
