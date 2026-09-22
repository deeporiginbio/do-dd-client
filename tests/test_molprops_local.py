"""Local mock-server tests for :class:`~deeporigin.drug_discovery.molprops.Molprops`."""

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
    assert ligand.log_p is not None
    assert ligand.sa_score is None


def test_molprops_run_applies_sa_score(client: DeepOriginClient) -> None:
    """``sa_score`` lands on a named Ligand attribute, not ``properties``."""
    mp_cfg = TOOL_KEYS_AND_VERSIONS["mol_props"]
    assert check_tool_exists(client, mp_cfg["tool_key"], mp_cfg["tool_version"])

    ligand = Ligand.from_smiles("CCO")
    Molprops(ligands=[ligand], props=["sa_score"], client=client).run()

    assert ligand.sa_score is not None
    assert "sa_score" not in ligand.properties


def test_molprops_default_props_are_full_enum() -> None:
    """Omitting props requests every tool input key."""
    from deeporigin.utils.constants import MOLPROPS_PROPERTY_KEYS

    ligand = Ligand.from_smiles("CCO")
    job = Molprops(ligands=[ligand])
    assert job.properties == MOLPROPS_PROPERTY_KEYS
