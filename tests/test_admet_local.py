"""Local mock-server tests for :class:`~deeporigin.drug_discovery.admet.Admet`."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from deeporigin.drug_discovery import Admet, Ligand
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from tests.conftest import check_tool_exists
from tests.mock_server.routers.tools import _synthesize_admet_prediction_row

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

_ADMET_PROPERTIES = ["hERG_classification", "AMES_classification"]


def test_admet_run_returns_dataframe(client: DeepOriginClient) -> None:
    """Normal ``run()`` returns a DataFrame with deterministic mock predictions."""
    cfg = TOOL_KEYS_AND_VERSIONS["admet"]
    assert check_tool_exists(client, cfg["tool_key"], cfg["tool_version"])

    lig1 = Ligand.from_smiles("CCO")
    lig2 = Ligand.from_smiles("CCN")
    job = Admet(ligands=[lig1, lig2], properties=_ADMET_PROPERTIES, client=client)

    df = job.run()

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    for prop in _ADMET_PROPERTIES:
        assert prop in df.columns
    assert job.status == "Completed"
    assert job.id is not None

    expected_lig1 = _synthesize_admet_prediction_row(
        smiles="CCO",
        ligand_id="0",
        requested=_ADMET_PROPERTIES,
    )
    row1 = df[df["ligand_id"] == "0"].iloc[0]
    for prop in _ADMET_PROPERTIES:
        assert row1[prop] == expected_lig1[prop]


def test_admet_run_quote_true(client: DeepOriginClient) -> None:
    """``run(quote=True)`` returns the job with estimate; ligands are unchanged."""
    cfg = TOOL_KEYS_AND_VERSIONS["admet"]
    assert check_tool_exists(client, cfg["tool_key"], cfg["tool_version"])

    ligand = Ligand.from_smiles("CCO")
    job = Admet(ligands=[ligand], properties=_ADMET_PROPERTIES, client=client)
    result = job.run(quote=True)

    assert result is job
    assert job.estimate is not None
    assert job.status == "Quoted"
