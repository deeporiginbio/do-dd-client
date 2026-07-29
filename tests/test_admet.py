"""End-to-end tests for ``deeporigin.admet-properties`` via :class:`~deeporigin.drug_discovery.admet.Admet`.

Run against dev with ``--env dev`` after the tool is registered on the platform.
"""

from __future__ import annotations

import pytest

from deeporigin.drug_discovery import Admet, Ligand
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from tests.conftest import check_tool_exists

_ADMET_PROPERTIES = [
    "hERG_classification",
    "AMES_classification",
    "PPB_regression",
]


def test_admet_lv1(client: DeepOriginClient) -> None:
    """Run Admet against dev with a small property subset."""
    cfg = TOOL_KEYS_AND_VERSIONS["admet"]
    assert check_tool_exists(client, cfg["tool_key"], cfg["tool_version"]), (
        f"ADMET tool {cfg['tool_key']} (version {cfg['tool_version']}) "
        "is not registered on the platform."
    )

    ligand = Ligand.from_smiles(
        "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12"
    )
    job = Admet(ligands=[ligand], properties=_ADMET_PROPERTIES, client=client)
    df = job.run()

    if df.empty:
        pytest.skip("Admet returned no predictions; platform tool may be unavailable.")

    assert job.status == "Completed"
    assert job.id is not None
    assert "ligand_id" in df.columns
    assert "smiles" in df.columns
    for prop in _ADMET_PROPERTIES:
        assert prop in df.columns
        value = df[prop].iloc[0]
        assert value is not None
        if prop.endswith("_classification"):
            assert 0.0 <= float(value) <= 1.0


def test_admet_run_quote_true(client: DeepOriginClient) -> None:
    """``run(quote=True)`` returns the job with estimate and does not produce a DataFrame."""
    cfg = TOOL_KEYS_AND_VERSIONS["admet"]
    assert check_tool_exists(client, cfg["tool_key"], cfg["tool_version"])

    ligand = Ligand.from_smiles("CCO")
    job = Admet(ligands=[ligand], properties=["hERG_classification"], client=client)
    result = job.run(quote=True)

    assert result is job
    assert job.estimate is not None
    assert getattr(job, "status", None) == "Quoted"
