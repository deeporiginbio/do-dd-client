"""Unit tests for inline-vs-file ligand inputs."""

from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from deeporigin.drug_discovery.ligand_list_file import (
    ligand_rows_from_inputs,
    ligands_from_rows,
    ligands_input,
    parse_ligand_list,
)
from deeporigin.utils.constants import INLINE_LIGAND_CAP


class _Files:
    def __init__(self, root: Path) -> None:
        self.root = root

    def upload(self, local: str, remote: str) -> None:
        dest = self.root / remote
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(local, dest)

    def download(self, remote: str, direct: bool = False) -> str:
        return str(self.root / remote)


def test_ligands_inline_at_cap_and_file_above(tmp_path: Path) -> None:
    """Exactly the cap stays inline; one more uploads and round-trips."""
    client = SimpleNamespace(files=_Files(tmp_path))
    rows = [{"id": f"L{i}", "smiles": "CCO"} for i in range(INLINE_LIGAND_CAP + 1)]

    assert ligands_input(rows[:-1], client=client, prefix="t/") == {
        "ligands": rows[:-1]
    }

    inputs = ligands_input(rows, client=client, prefix="t/")
    assert set(inputs) == {"ligands_file", "ligands_count"}
    assert inputs["ligands_count"] == INLINE_LIGAND_CAP + 1
    assert inputs["ligands_file"].startswith("t/")
    assert ligand_rows_from_inputs(inputs, client=client, label="T") == rows


def test_ligands_from_rows_restores_smiles_and_ids() -> None:
    """Rows rebuild ligands; numeric ids become strings, missing ids stay unset."""
    ligands = ligands_from_rows(
        [{"smiles": "CCO", "id": 7}, {"smiles": "CCN"}], label="T"
    )
    assert [(lig.smiles, lig.id) for lig in ligands] == [("CCO", "7"), ("CCN", None)]


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        (b"\xff", "not valid UTF-8"),
        (b"{", "not valid JSON"),
        (b"[]", "non-empty JSON array"),
        (b'{"smiles": "CCO"}', "non-empty JSON array"),
    ],
)
def test_parse_ligand_list_rejects_bad_bodies(payload: bytes, match: str) -> None:
    """Corrupt list files raise ValueError naming the caller."""
    with pytest.raises(ValueError, match=f"Cannot rehydrate T: .*{match}"):
        parse_ligand_list(payload, label="T")
