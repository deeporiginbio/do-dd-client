"""Scientific SDK use must not require the legacy notebook viewer."""

import subprocess
import sys
import textwrap
from types import SimpleNamespace
from unittest.mock import Mock


def test_scientific_operations_without_legacy_molstar():
    """Exercise fresh imports and local molecular operations with Mol* absent."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import sys
                sys.modules["deeporigin_molstar"] = None

                import pandas as pd
                from deeporigin.drug_discovery import (
                    ABFE, RBFE, BRD_DATA_DIR, ConstrainedDocking, Docking,
                    Ligand, LigandSet, Pocket, PocketFinder, Protein, ProteinPrep,
                )
                from deeporigin.drug_discovery.utils import render_smiles_in_dataframe

                protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
                ligand = Ligand.from_smiles("CCO")
                assert protein is not None
                assert ligand.smiles == "CCO"
                frame = render_smiles_in_dataframe(pd.DataFrame({"SMILES": ["CCO"]}), "SMILES")
                assert frame.loc[0, "Structure"] is not None
                """
            ),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_notebook_decorator_still_displays_generated_html(monkeypatch):
    """The optional viewer receives the same HTML and its result is returned."""
    from deeporigin.drug_discovery.utils.visualize import jupyter_visualization

    display = Mock(return_value="displayed")
    monkeypatch.setitem(
        sys.modules,
        "deeporigin_molstar",
        SimpleNamespace(JupyterViewer=SimpleNamespace(visualize=display)),
    )
    generate = Mock(return_value="<div>molecular view</div>")

    assert jupyter_visualization(generate)("protein", style="cartoon") == "displayed"
    generate.assert_called_once_with("protein", style="cartoon")
    display.assert_called_once_with("<div>molecular view</div>")
