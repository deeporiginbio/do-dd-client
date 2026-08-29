"""Tests for Prepared Protein stamp helpers and stamp-preserving Protein I/O."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from deeporigin.drug_discovery.structures.prepared_protein_stamp import (
    has_prepared_protein_stamp,
    stamp_prepared_protein_pdb,
    text_has_prepared_protein_stamp,
)
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.utils.constants import PREPARED_PROTEIN_STAMP_LINE

_MINIMAL_ATOM = (
    "ATOM      1  N   ALA A   1      11.104  13.207   9.068  1.00  0.00           N\n"
    "END\n"
)


def test_text_has_prepared_protein_stamp_detects_canonical_line() -> None:
    """Canonical REMARK  99 DO_PREPARED before ATOM is detected."""
    text = f"{PREPARED_PROTEIN_STAMP_LINE}\n{_MINIMAL_ATOM}"
    assert text_has_prepared_protein_stamp(text) is True


def test_text_has_prepared_protein_stamp_lenient_whitespace() -> None:
    """One-space REMARK 99 still matches (reader is lenient)."""
    text = f"REMARK 99 DO_PREPARED\n{_MINIMAL_ATOM}"
    assert text_has_prepared_protein_stamp(text) is True


def test_text_has_prepared_protein_stamp_false_after_atom() -> None:
    """Stamp after the first ATOM/HETATM does not count."""
    text = f"{_MINIMAL_ATOM}{PREPARED_PROTEIN_STAMP_LINE}\n"
    assert text_has_prepared_protein_stamp(text) is False


def test_text_has_prepared_protein_stamp_absent() -> None:
    """Unstamped PDB text returns False."""
    assert text_has_prepared_protein_stamp(_MINIMAL_ATOM) is False


def test_stamp_prepared_protein_pdb_is_idempotent(tmp_path: Path) -> None:
    """stamp_prepared_protein_pdb prepends once and is a no-op thereafter."""
    pdb_path = tmp_path / "protein.pdb"
    pdb_path.write_text(_MINIMAL_ATOM)
    assert has_prepared_protein_stamp(pdb_path) is False

    stamp_prepared_protein_pdb(pdb_path)
    assert has_prepared_protein_stamp(pdb_path) is True
    first = pdb_path.read_bytes()

    stamp_prepared_protein_pdb(pdb_path)
    assert pdb_path.read_bytes() == first
    assert pdb_path.read_text().startswith(PREPARED_PROTEIN_STAMP_LINE + "\n")


def test_protein_to_pdb_preserves_do_prepared_stamp(tmp_path: Path) -> None:
    """biotite rewrite via to_pdb re-prepends DO_PREPARED when the source had it."""
    stamped = tmp_path / "stamped.pdb"
    stamped.write_text(f"{PREPARED_PROTEIN_STAMP_LINE}\n{_MINIMAL_ATOM}")
    protein = Protein.from_file(stamped)
    assert has_prepared_protein_stamp(stamped) is True

    out = tmp_path / "rewritten.pdb"
    protein.to_pdb(out)
    assert has_prepared_protein_stamp(out) is True
    assert out.read_text().startswith(PREPARED_PROTEIN_STAMP_LINE + "\n")


def test_protein_to_pdb_does_not_add_stamp_when_source_unstamped(
    tmp_path: Path,
) -> None:
    """to_pdb does not invent a stamp for unstamped sources."""
    plain = tmp_path / "plain.pdb"
    plain.write_text(_MINIMAL_ATOM)
    protein = Protein.from_file(plain)

    out = tmp_path / "rewritten.pdb"
    protein.to_pdb(out)
    assert has_prepared_protein_stamp(out) is False


def test_protein_sync_lazy_skips_upload_when_remote_path_set() -> None:
    """sync(lazy=True) still resolves an id, but skips upload, when remote_path
    is already populated and no id is set yet."""
    from deeporigin.platform.client import DeepOriginClient

    protein = Protein(
        name="prepared",
        structure=None,
        remote_path="entities/proteins/prepared.pdb",
    )
    client = MagicMock(spec=DeepOriginClient)
    client.project_id = None
    client.entities = MagicMock()
    client.entities.search_proteins.return_value = {
        "data": [{"id": "prot-existing", "project_id": None}]
    }

    with patch.object(protein, "upload") as upload:
        protein.sync(lazy=True, client=client)

    upload.assert_not_called()
    assert protein.id == "prot-existing"
    assert protein.remote_path == "entities/proteins/prepared.pdb"


def test_protein_sync_skips_upload_but_registers_when_remote_path_only() -> None:
    """Non-lazy sync with remote_path set skips upload and still registers."""
    from deeporigin.platform.client import DeepOriginClient

    protein = Protein(
        name="prepared",
        structure=None,
        remote_path="entities/proteins/prepared.pdb",
    )
    client = MagicMock(spec=DeepOriginClient)
    client.project_id = None
    client.entities = MagicMock()
    client.entities.search_proteins.return_value = {"data": []}
    client.entities.create_protein.return_value = {"data": {"id": "prot-new"}}

    with patch.object(protein, "upload") as upload:
        protein.sync(lazy=False, client=client)

    upload.assert_not_called()
    client.entities.search_proteins.assert_called_once_with(
        file_path="entities/proteins/prepared.pdb",
    )
    client.entities.create_protein.assert_called_once()
    assert protein.id == "prot-new"
    assert protein.remote_path == "entities/proteins/prepared.pdb"


def test_protein_sync_links_existing_without_upload_when_remote_path_set() -> None:
    """Non-lazy sync finds an existing row by file_path without uploading."""
    from deeporigin.platform.client import DeepOriginClient

    protein = Protein(
        name="prepared",
        structure=None,
        remote_path="entities/proteins/prepared.pdb",
    )
    client = MagicMock(spec=DeepOriginClient)
    client.project_id = None
    client.entities = MagicMock()
    client.entities.search_proteins.return_value = {
        "data": [{"id": "prot-existing", "project_id": None}],
    }

    with patch.object(protein, "upload") as upload:
        protein.sync(lazy=False, client=client)

    upload.assert_not_called()
    client.entities.create_protein.assert_not_called()
    assert protein.id == "prot-existing"
