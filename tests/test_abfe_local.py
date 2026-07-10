"""Integration tests for ABFE against the local mock server (--env local)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from deeporigin.drug_discovery import ABFE, SystemPrep
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.protein import Protein

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


def test_abfe_sysprep_and_quote_local(
    client: DeepOriginClient,
    registered_protein: Protein,
    registered_ligand: Ligand,
) -> None:
    """BRD pair: system-prep then ABFE quote against the mock server."""
    system = SystemPrep(
        protein=registered_protein,
        ligand=registered_ligand,
        client=client,
    ).run()
    assert system is not None
    assert system.system_pdb_path

    abfe = ABFE(prepared_system=system, client=client)
    abfe.start(quote=True)

    assert abfe.status == "Quoted"
    assert abfe.id is not None
    assert abfe.estimate == pytest.approx(119.2128)
